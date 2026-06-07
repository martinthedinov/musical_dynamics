"""MD-native compositional steganography.

The verified decoder for Musical Dynamics is *invariant* to the per-opcode "variation" choice
— which chord-quality family member is voiced, and which upper tones are pushed up an octave.
This module turns that ignored degree of freedom into a covert channel: a bit stream drives
the variation decisions, and the notes still decode to the **identical opcode sequence and
program output**. No audio tampering, no PCM bits flipped — just a different (but equally
valid) arrangement.

Per-opcode capacity:
    bits(op) = (1 if family_size>1 else 0) + min_upper_tones
For the 21 opcodes that's 1–3 bits each. A program of ~50 opcodes carries ~120–180 hidden bits
(~15–22 bytes of raw payload after a slim header).

Layout per opcode (driving the existing realize() variation int):
    bit 0           -> family member index, if family_size > 1, else unused
    bits 1..n_voice -> voicing bits for upper tones 1..n_voice

Extraction reads the chord signature (→ family member index), looks at each upper voice's
actual pitch against root (→ voicing bit), and reconstructs the bit stream.

File framing uses a 4-byte slim header (len + payload-CRC16 + header-CRC8) instead of the
30-byte LSB-pipeline header, with N×repetition + Reed-Solomon for redundancy.
"""
import struct
import numpy as np
import mc_codec as mc
from .bitio import bytes_to_bits, bits_to_bytes, crc16

class NativeError(Exception): pass


def bits_per_opcode(op):
    fam = mc.QFAMILY[op]
    family_bits = 1 if len(fam) > 1 else 0
    voicing_bits = min(len(q) - 1 for q in fam)
    return family_bits + voicing_bits

def capacity_bits(opcodes_or_trace):
    """Bits available in a program (list of (op,arg)) or trace (list of dicts)."""
    def _op(x): return x["op"] if isinstance(x, dict) else x[0]
    return sum(bits_per_opcode(_op(x)) for x in opcodes_or_trace)


# ---------- realization with a payload-driven variation per opcode ----------
def realize_with_bits(trace, payload_bits, mode="major", key=0, climb_step=1, octave=0, tempo=1.0):
    """Like mc.realize, but per-opcode `variation` is sourced from `payload_bits`.
       Returns (notes, n_bits_consumed). Out-of-bits opcodes get the default variation=0."""
    sc = mc.MODES[mode]; root0 = 60 + key + 12 * octave; n = len(sc)
    notes, t = [], 0.0
    bi = 0
    for k, s in enumerate(trace):
        op = s["op"]; dur, vel, ctrl = mc.CAT.get(op, (.4, 64, 0)); dur *= tempo
        fam = mc.QFAMILY[op]
        fam_bits  = 1 if len(fam) > 1 else 0
        n_voice   = min(len(q) - 1 for q in fam)
        nbits     = fam_bits + n_voice
        # pack the payload bits into a variation int with the EXACT layout realize uses:
        # bit 0 = family bit (only meaningful when family_bits=1); bits 1..n_voice = voicing
        variation = 0
        if fam_bits and bi < len(payload_bits) and payload_bits[bi]:
            variation |= 1
        for j in range(n_voice):
            idx = bi + fam_bits + j
            if idx < len(payload_bits) and payload_bits[idx]:
                variation |= (1 << (j + 1))               # j+1: skip bit 0 (the family bit slot)
        bi += nbits
        q = fam[variation % len(fam)]
        tp = mc.scale_shift(s["iter"] * climb_step, sc); root = root0 + tp
        voiced = [root + q[0]]
        for j, iv in enumerate(q[1:], 1):
            up = 12 if ((variation >> j) & 1) else 0
            voiced.append(root + iv + up)
        for p in voiced: notes.append(mc.Note(p, t, dur * 0.95, vel, 0, "pad", tp))
        if ctrl: notes.append(mc.Note(root - 24, t, dur, max(1, vel - 12), 2, "bass", tp))
        if op in mc.HAS_ARG:
            for p in mc.enc_operand(s["arg"]):
                notes.append(mc.Note(p, t, dur * 0.9, 96, 1, "operand", 0))
        elif op == "OUT" and s["val"] is not None:
            val = s["val"]; v = abs(int(val)) if isinstance(val, int) else (ord(val[0]) if val else 0)
            notes.append(mc.Note(root0 + 12 + sc[v % n] + 12 * ((v // n) % 3), t, dur * 1.1, 110, 1, "lead", tp))
        t += dur
    return notes, bi


def extract_bits_from_notes(notes):
    """Walk decoded notes and recover the per-opcode variation bits in the same order
       realize_with_bits consumed them."""
    onsets = {}
    for nt in notes:
        if nt.ch == 2: continue
        key = round(nt.start / 0.0001)
        onsets.setdefault(key, {"t": nt.start, "ch0": [], "ch1": []})
        (onsets[key]["ch0"] if nt.ch == 0 else onsets[key]["ch1"]).append(nt.pitch)
    out_bits = []
    for key in sorted(onsets, key=lambda k: onsets[k]["t"]):
        ch0 = onsets[key]["ch0"]
        if not ch0: continue
        root = min(ch0)
        sig = tuple(sorted(set((p - root) % 12 for p in ch0)))
        op = mc.QREV.get(sig)
        if op is None: raise NativeError("undecodable chord %s" % (sig,))
        fam = mc.QFAMILY[op]
        fam_idx = 0
        for i, qq in enumerate(fam):
            qsig = tuple(sorted(set(x % 12 for x in qq)))
            if qsig == sig: fam_idx = i; break
        q = fam[fam_idx]
        n_voice = min(len(qq) - 1 for qq in fam)
        if len(fam) > 1:
            out_bits.append(fam_idx & 1)
        for j in range(1, n_voice + 1):
            iv = q[j]
            if (root + iv) in ch0:        out_bits.append(0)
            elif (root + iv + 12) in ch0: out_bits.append(1)
            else: out_bits.append(0)            # shouldn't happen on a realize_with_bits piece
    return np.asarray(out_bits, dtype=np.uint8)


# ---------- slim file-level framing for tiny native-channel capacity ----------
_HDR_FMT = ">BHB"                                  # payload_len (1), payload_crc16 (2), header_crc8 (1)
_HDR_BYTES = struct.calcsize(_HDR_FMT)             # 4

def _crc8(b):
    c = 0
    for x in b:
        c ^= x
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
    return c

def _frame(payload):
    if len(payload) > 255: raise NativeError("MD-native payload limited to 255 bytes")
    h = struct.pack(">BH", len(payload), crc16(payload)) + bytes([0])
    h = h[:-1] + bytes([_crc8(h[:-1])])
    return h + payload

def _unframe(buf):
    if len(buf) < _HDR_BYTES: raise NativeError("frame too short")
    h, payload = buf[:_HDR_BYTES], buf[_HDR_BYTES:]
    if _crc8(h[:-1]) != h[-1]: raise NativeError("header CRC failed")
    n = h[0]; (pcrc,) = struct.unpack(">H", h[1:3])
    data = payload[:n]
    if len(data) != n: raise NativeError("payload truncated")
    if crc16(data) != pcrc: raise NativeError("payload CRC mismatch")
    return data

def _repeat(bits, R):
    """Interleave R copies of each bit ([b0]*R + [b1]*R + ...) so majority vote is robust to
       trailing padding without needing to know the original length."""
    return np.repeat(bits, R).astype(np.uint8)

def _majority_vote(bits, R):
    """Inverse of _repeat: reshape every R consecutive bits into one vote."""
    n = bits.size // R
    if n == 0: return np.zeros(0, dtype=np.uint8)
    return (bits[:n * R].reshape(n, R).sum(axis=1) * 2 > R).astype(np.uint8)


# ---------- public file API ----------
def embed_payload(opcodes, payload, repetition=3, password=None, **realize_kwargs):
    """Hide `payload` bytes in the variation/voicing of `opcodes`'s realization.

    Returns (notes, info). The notes decode to *exactly* `opcodes`; running them produces the
    original program's output. `repetition` provides robustness via majority vote (3 = good
    baseline, 1 = no redundancy if you're tight on capacity).
    """
    if password is not None:
        from . import crypto
        payload = crypto.encrypt(payload, password)
    trace = [{"op": op, "arg": arg, "iter": 0, "val": None} for op, arg in opcodes]
    cap = capacity_bits(trace)
    framed = _frame(payload)
    framed_bits = bytes_to_bits(framed)
    needed = framed_bits.size * repetition
    if needed > cap:
        raise NativeError("program too small for this payload: need %d bits at %dx rep, have %d "
                          "(use a longer program or rep=1)" % (needed, repetition, cap))
    stream = np.concatenate([_repeat(framed_bits, repetition),
                             np.zeros(cap - needed, dtype=np.uint8)])
    notes, used = realize_with_bits(trace, stream, **realize_kwargs)
    info = dict(payload_bytes=len(payload), framed_bytes=len(framed), repetition=repetition,
                capacity_bits=cap, used_bits=needed, slack_bits=cap - needed,
                encrypted=(password is not None))
    return notes, info


def extract_payload(notes, repetition=3, password=None):
    """Recover the hidden bytes from notes produced by embed_payload (same `repetition`)."""
    raw = extract_bits_from_notes(notes)
    framed_bits_size = (_HDR_BYTES + 255) * 8        # max possible
    # we don't know the length yet — vote on the whole stream, then frame-parse
    vote = _majority_vote(raw, repetition)
    if vote.size < _HDR_BYTES * 8: raise NativeError("not enough variation bits for the header")
    # parse the header first, then exact-length payload
    header_bits = vote[:_HDR_BYTES * 8]
    header = bits_to_bytes(header_bits)
    if _crc8(header[:-1]) != header[-1]: raise NativeError("header CRC failed (no native payload?)")
    payload_len = header[0]
    needed_bits = (_HDR_BYTES + payload_len) * 8
    if vote.size < needed_bits:
        raise NativeError("variation channel too short for declared payload length %d" % payload_len)
    framed = bits_to_bytes(vote[:needed_bits])
    data = _unframe(framed)
    if password is not None:
        from . import crypto
        data = crypto.decrypt(data, password)
    return data
