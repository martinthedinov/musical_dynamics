"""Format-independent payload pipeline (concatenated code).

A carrier exposes a flat array of 1-bit *slots* (low bit-planes of its samples). Layout:

    payload --frame(name+len+crc)--> [zlib?] --> [AES-GCM?] --> fountain symbols
    each symbol --> + inner CRC16 --> Reed-Solomon parity --> wire bytes
    slots = [ self-checking numeric HEADER, replicated & spread across the whole carrier ]
            [ RS-wrapped fountain symbols, spread evenly into cells across the carrier   ]

Redundancy is two-layered and tunable:
  * inner Reed-Solomon repairs scattered bit/byte flips *within* a symbol (light noise);
  * each symbol occupies a contiguous cell, and cells are spread across the whole carrier, so a
    localized edit/overwrite erases a *proportional* set of whole symbols, which the outer
    fountain (LT) rebuilds from any K'~K survivors. A payload embedded at R× tolerates losing
    ~(1-1/R) of the carrier; embedding at "fill" maximizes R and thus damage tolerance.
The header is replicated R_HEADER× (each copy self-checked by CRC) and spread, so it is read by
majority vote (beats scattered noise) with a single-intact-copy fallback (beats huge overwrites).
Decode is fail-safe: header CRC, per-symbol CRC, and a final payload CRC must all pass.
"""
import math, struct, zlib
import numpy as np
from .bitio import bytes_to_bits, bits_to_bytes, crc16
from .fountain import Fountain, blocks_of, decode as lt_decode
from . import crypto

class PipelineError(Exception): pass

MAGIC       = b"MDX1"
VERSION     = 1
R_HEADER    = 11
_HDR_FMT    = ">4sBBHIIIIBBI"                     # magic,ver,flags,block_size,K,seed,coded_len,n_sym,n_lsb,rs_nsym,crc
HEADER_BYTES = struct.calcsize(_HDR_FMT)          # 30
FLAG_ZLIB, FLAG_AES = 1, 2
DEFAULT_BLOCK, DEFAULT_RS = 64, 20

def _rscodec(nsym):
    if nsym <= 0: return None
    from reedsolo import RSCodec
    return RSCodec(nsym)

def _rs_decode(rsc, chunk):
    out = rsc.decode(chunk)
    return bytes(out[0] if isinstance(out, tuple) else out)

# ---------- frame (filename + integrity) ----------
def _frame(payload, filename):
    name = (filename or "payload.bin").encode("utf-8")[:65535]
    return struct.pack(">HII", len(name), len(payload), zlib.crc32(payload) & 0xffffffff) + name + payload

def _unframe(buf):
    if len(buf) < 10: raise PipelineError("frame too short")
    name_len, data_len, crc = struct.unpack(">HII", buf[:10])
    name = buf[10:10 + name_len].decode("utf-8", "replace")
    data = buf[10 + name_len:10 + name_len + data_len]
    if len(data) != data_len: raise PipelineError("payload truncated")
    if (zlib.crc32(data) & 0xffffffff) != crc: raise PipelineError("payload CRC-32 mismatch (corrupted beyond recovery)")
    return name, data

# ---------- compress + encrypt middle layer ----------
def pack(payload, filename="payload.bin", password=None):
    frame = _frame(payload, filename); flags = 0
    comp = zlib.compress(frame, 9); coded = frame
    if len(comp) < len(frame): coded = comp; flags |= FLAG_ZLIB
    if password: coded = crypto.encrypt(coded, password); flags |= FLAG_AES
    return coded, flags

def unpack(coded, flags, password=None):
    if flags & FLAG_AES:  coded = crypto.decrypt(coded, password)
    if flags & FLAG_ZLIB: coded = zlib.decompress(coded)
    return _unframe(coded)

# ---------- header ----------
def _make_header(flags, block_size, K, seed, coded_len, n_sym, n_lsb, rs_nsym):
    h = struct.pack(_HDR_FMT, MAGIC, VERSION, flags, block_size, K, seed, coded_len, n_sym, n_lsb, rs_nsym, 0)
    return h[:-4] + struct.pack(">I", zlib.crc32(h[:-4]) & 0xffffffff)

def _read_header_bytes(hbytes):
    if hbytes[:4] != MAGIC: return None
    _, ver, flags, block_size, K, seed, coded_len, n_sym, n_lsb, rs_nsym, crc = struct.unpack(_HDR_FMT, hbytes)
    if (zlib.crc32(hbytes[:-4]) & 0xffffffff) != crc: return None
    return dict(version=ver, flags=flags, block_size=block_size, K=K, seed=seed,
                coded_len=coded_len, n_sym=n_sym, n_lsb=n_lsb, rs_nsym=rs_nsym)

def _step_bytes(block_size, rs_nsym):
    # RS path carries data(B)+inner CRC16(2) under RS parity (CRC catches RS mis-corrections,
    # e.g. an overwrite-to-silence is a valid all-zero RS codeword and must be rejected).
    return (block_size + 2 + rs_nsym) if rs_nsym > 0 else (2 + block_size)

# ---------- deterministic slot layout (shared with the JS app) ----------
def _layout(cap):
    """(header_positions, body_positions). Header spread by a wide stride into R_HEADER full,
       self-checking copies; the body takes the remaining slots in order (then cell-spread)."""
    nbits = HEADER_BYTES * 8
    header_total = R_HEADER * nbits
    if cap < header_total + 1:
        return None
    stride = cap // header_total
    hpos = np.arange(header_total, dtype=np.int64) * stride      # copy-major: copy c occupies slice c
    mask = np.ones(cap, dtype=bool); mask[hpos] = False
    return hpos, np.flatnonzero(mask)

def _cell(i, n_fit, n_sym):
    return (i * n_fit) // n_sym                                   # spread n_sym symbols across n_fit cells

# ---------- slot-level embed / extract ----------
def embed_slots(slot_bits, payload, filename, password=None, block_size=DEFAULT_BLOCK,
                n_lsb=1, redundancy=None, rs_nsym=DEFAULT_RS):
    if rs_nsym > 0 and block_size + 2 + rs_nsym > 255:
        raise PipelineError("block_size + 2 + rs_nsym must be <= 255 (Reed-Solomon GF(256) limit)")
    coded, flags = pack(payload, filename, password)
    seed = zlib.crc32(coded) & 0xffffffff
    blocks, K = blocks_of(coded, block_size)
    fnt = Fountain(K, block_size, seed); rsc = _rscodec(rs_nsym)
    cap = len(slot_bits)
    lay = _layout(cap)
    if lay is None: raise PipelineError("carrier far too small")
    hpos, body = lay
    step = _step_bytes(block_size, rs_nsym); symbol_slots = step * 8
    n_fit = len(body) // symbol_slots
    if n_fit < K:
        raise PipelineError("carrier too small: fits %d symbols but payload needs >= %d" % (n_fit, K))
    n_sym = n_fit if redundancy is None else int(min(n_fit, max(K, math.ceil(K * redundancy))))
    out = slot_bits.copy()
    header = _make_header(flags, block_size, K, seed, len(coded), n_sym, n_lsb, rs_nsym)
    out[hpos] = np.tile(bytes_to_bits(header), R_HEADER)
    for i in range(n_sym):
        sym = fnt.encode_symbol(blocks, i).tobytes()
        wire = bytes(rsc.encode(sym + struct.pack(">H", crc16(sym)))) if rsc else (struct.pack(">H", crc16(sym)) + sym)
        c = _cell(i, n_fit, n_sym)
        out[body[c * symbol_slots:(c + 1) * symbol_slots]] = bytes_to_bits(wire)
    info = dict(K=K, block_size=block_size, rs_nsym=rs_nsym, n_symbols=n_sym, redundancy=round(n_sym / K, 2),
                coded_len=len(coded), flags=flags, capacity_slots=cap, n_lsb=n_lsb,
                tolerates_symbol_loss="%.0f%%" % (100 * (1 - K / n_sym)))
    return out, info

def extract_slots(slot_bits, hdr):
    cap = len(slot_bits)
    hpos, body = _layout(cap)
    B, K, seed, coded_len, n_sym, rs_nsym = (hdr["block_size"], hdr["K"], hdr["seed"],
                                             hdr["coded_len"], hdr["n_sym"], hdr["rs_nsym"])
    step = _step_bytes(B, rs_nsym); symbol_slots = step * 8
    n_fit = len(body) // symbol_slots
    fnt = Fountain(K, B, seed); rsc = _rscodec(rs_nsym)
    symbols, recovered = {}, 0
    for i in range(n_sym):
        c = _cell(i, n_fit, n_sym)
        wire = bits_to_bytes(slot_bits[body[c * symbol_slots:(c + 1) * symbol_slots]])
        if len(wire) < step: continue
        if rsc is not None:
            try: inner = _rs_decode(rsc, wire)
            except Exception: continue
            data = inner[:B]; (crc,) = struct.unpack(">H", inner[B:B + 2])
            if crc16(data) == crc: symbols[i] = data; recovered += 1
        else:
            (crc,) = struct.unpack(">H", wire[:2]); data = wire[2:]
            if crc16(data) == crc: symbols[i] = data; recovered += 1
    coded_padded = lt_decode(symbols, fnt)
    if coded_padded is None:
        raise PipelineError("too many symbols lost — payload unrecoverable (%d/%d symbols usable)" % (recovered, n_sym))
    return coded_padded[:coded_len]

def read_header(slot_bits):
    lay = _layout(len(slot_bits))
    if lay is None: return None
    hpos, _ = lay; nbits = HEADER_BYTES * 8
    copies = slot_bits[hpos].reshape(R_HEADER, nbits)
    maj = _read_header_bytes(bits_to_bytes((copies.sum(axis=0) * 2 > R_HEADER).astype(np.uint8)))
    if maj: return maj                                           # majority vote: beats scattered noise
    for c in range(R_HEADER):                                    # fallback: any one intact copy beats huge overwrites
        h = _read_header_bytes(bits_to_bytes(copies[c].astype(np.uint8)))
        if h: return h
    return None

# ---------- what carriers call upward ----------
def embed(carrier, payload, filename="payload.bin", password=None, block_size=DEFAULT_BLOCK,
          n_lsb=1, redundancy=None, rs_nsym=DEFAULT_RS):
    bits = carrier.get_bits(n_lsb)
    new_bits, info = embed_slots(bits, payload, filename, password, block_size, n_lsb, redundancy, rs_nsym)
    carrier.set_bits(new_bits, n_lsb)
    return info

def extract(carrier, password=None, n_lsb_candidates=(1, 2, 3, 4)):
    for n_lsb in n_lsb_candidates:
        bits = carrier.get_bits(n_lsb)
        hdr = read_header(bits)
        if hdr is None or hdr["n_lsb"] != n_lsb:
            continue
        coded = extract_slots(bits, hdr)
        name, data = unpack(coded, hdr["flags"], password)
        return name, data, dict(hdr, n_lsb=n_lsb)
    raise PipelineError("no MDX1 header found (not a stego carrier, or too corrupted to read)")
