"""
mc_stego — hide arbitrary bytes (text, a JPEG, anything) inside an EXISTING musical piece
by toggling the least-significant bit of 16-bit PCM samples. The change is ~ -96 dBFS:
inaudible to a human, exactly recoverable by software.

ERROR CHECKING + REDUNDANCY (the requested robustness):
  * a fixed-size, fixed-redundancy HEADER (repetition R_H=11) stores body redundancy R and
    the container length, so the decoder can bootstrap with no side channel.
  * the BODY (the data container) is repetition-coded R× and PSEUDO-RANDOMLY INTERLEAVED
    across the carrier, so bursts/periodic noise are spread over many copies; decode is
    majority-vote per bit (corrects up to (R-1)/2 flips per bit).
  * CRC-32 over the payload detects any residual corruption (graceful failure, never silent
    wrong data). A 4-byte MAGIC guards against decoding a non-stego file.

This is a SIDE feature of the musiclang / Musical-Dynamics project, not its core.
"""
import numpy as np, wave, zlib, struct, io

MAGIC   = b"MDS1"                 # container magic
HMAGIC  = b"MD"                   # header magic
R_H     = 11                      # header repetition (fixed, known to both sides)
HDR_BYTES = 12                    # hmagic(2) R(1) rsvd(1) clen(4) hcrc(4)
SEED_H, SEED_B = 0x6D6431, 0x6D6432
TYPES = {0:"raw",1:"text",2:"jpeg",3:"png"}

# ---------- bit helpers ----------
def _bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))
def _unbits(bits: np.ndarray) -> bytes:
    return np.packbits(bits.astype(np.uint8)).tobytes()
def _perm(n, seed):
    return np.random.RandomState(seed).permutation(n)

# ---------- container framing ----------
def _frame(payload: bytes, ptype: int) -> bytes:
    return MAGIC + bytes([ptype]) + struct.pack(">I", len(payload)) + struct.pack(">I", zlib.crc32(payload) & 0xffffffff) + payload
def _unframe(buf: bytes):
    if buf[:4] != MAGIC: raise ValueError("no MAGIC — not a musiclang-stego payload")
    ptype = buf[4]; (length,) = struct.unpack(">I", buf[5:9]); (crc,) = struct.unpack(">I", buf[9:13])
    payload = buf[13:13+length]
    if len(payload) != length: raise ValueError("truncated payload")
    if (zlib.crc32(payload) & 0xffffffff) != crc: raise ValueError("CRC-32 mismatch — payload corrupted beyond correction")
    return ptype, payload

# ---------- repetition encode/decode over a permuted carrier region ----------
def _embed_region(lsb_target: np.ndarray, container_bits: np.ndarray, R: int, seed: int):
    M = len(container_bits); L = R * M
    if L > len(lsb_target): raise ValueError("region too small")
    perm = _perm(L, seed)
    slot_bit = np.arange(L) % M                     # which container bit each slot carries
    vals = container_bits[slot_bit]                 # bit value per slot (R copies of each bit)
    lsb_target[perm] = vals                         # scatter into carrier LSBs
def _read_region(lsb_src: np.ndarray, M: int, R: int, seed: int) -> np.ndarray:
    L = R * M; perm = _perm(L, seed)
    got = lsb_src[perm]                             # recover per-slot bits
    slot_bit = np.arange(L) % M
    votes = np.zeros(M, dtype=np.int32)
    np.add.at(votes, slot_bit, got.astype(np.int32))
    return (votes * 2 > R).astype(np.uint8)         # majority vote per bit

# ---------- public: embed / extract on int16 sample arrays ----------
def embed(samples: np.ndarray, payload: bytes, ptype: int = 0, max_R: int = 9) -> tuple:
    samples = samples.astype(np.int16).copy()
    N = len(samples)
    container = _frame(payload, ptype); clen = len(container)
    Mb = clen * 8
    Lh = R_H * (HDR_BYTES * 8)
    # choose body redundancy: largest odd R in [3..max_R] that fits after the header
    R = 0
    for cand in range(min(max_R, 9), 1, -1):
        if cand % 2 == 0: continue
        if Lh + cand * Mb <= N: R = cand; break
    if R == 0: raise ValueError(f"carrier too small: need ≥ {Lh + 3*Mb} samples for 3× redundancy, have {N}")
    # header
    header = HMAGIC + bytes([R, 0]) + struct.pack(">I", clen)
    header += struct.pack(">I", zlib.crc32(header) & 0xffffffff)
    lsb = (samples & 1).astype(np.uint8)
    _embed_region(lsb[:Lh], _bits(header), R_H, SEED_H)
    _embed_region(lsb[Lh:Lh + R*Mb], _bits(container), R, SEED_B)
    stego = (samples & np.int16(-2)) | lsb.astype(np.int16)
    info = dict(N=N, container_bytes=clen, body_R=R, header_slots=Lh, body_slots=R*Mb,
                capacity_bits=N, used_bits=Lh + R*Mb, correct_per_bit=(R-1)//2)
    return stego.astype(np.int16), info

def extract(samples: np.ndarray):
    samples = samples.astype(np.int16)
    lsb = (samples & 1).astype(np.uint8)
    Lh = R_H * (HDR_BYTES * 8)
    hbits = _read_region(lsb[:Lh], HDR_BYTES*8, R_H, SEED_H)
    header = _unbits(hbits)
    if header[:2] != HMAGIC: raise ValueError("no header MAGIC — not a stego carrier")
    if (zlib.crc32(header[:8]) & 0xffffffff) != struct.unpack(">I", header[8:12])[0]:
        raise ValueError("header CRC failed")
    R = header[2]; (clen,) = struct.unpack(">I", header[4:8]); Mb = clen*8
    cbits = _read_region(lsb[Lh:Lh + R*Mb], Mb, R, SEED_B)
    return _unframe(_unbits(cbits))

# ---------- WAV file wrappers ----------
def read_wav(path):
    wf = wave.open(path, "rb"); p = wf.getparams()
    assert p.sampwidth == 2, "need 16-bit PCM"
    data = np.frombuffer(wf.readframes(p.nframes), dtype=np.int16).copy(); wf.close()
    return data, p
def write_wav(path, samples, params):
    wf = wave.open(path, "wb"); wf.setparams(params)
    wf.writeframes(samples.astype(np.int16).tobytes()); wf.close()
def embed_file(in_wav, out_wav, payload, ptype=0):
    s, p = read_wav(in_wav); st, info = embed(s, payload, ptype); write_wav(out_wav, st, p); return info
def extract_file(in_wav):
    s, _ = read_wav(in_wav); return extract(s)

# ---------- helpers for the demo ----------
def synth_carrier(seconds=6.0, sr=44100):
    """A gentle stereo chord pad to act as the 'existing musical piece'."""
    prog = [[57,60,64,69],[53,57,60,65],[48,52,55,60],[55,59,62,67]]  # Am F C G
    t_chord = seconds/len(prog); out = []
    for chord in prog:
        n = int(sr*t_chord); tt = np.linspace(0, t_chord, n, endpoint=False); seg = np.zeros(n)
        for m in chord:
            f = 440*2**((m-69)/12); seg += np.sin(2*np.pi*f*tt)/len(chord)
        env = np.minimum(1, np.minimum(tt*8, (t_chord-tt)*8)); out.append(seg*env)
    mono = np.concatenate(out); mono /= np.max(np.abs(mono))+1e-9
    stereo = np.stack([mono*0.25, np.roll(mono,7)*0.25], axis=1).reshape(-1)  # interleaved L/R
    return (stereo*32767).astype(np.int16), sr
def metrics(orig, stego):
    orig=orig.astype(np.float64); stego=stego.astype(np.float64); noise=stego-orig
    p_s=np.mean(orig**2)+1e-12; p_n=np.mean(noise**2)+1e-12
    return dict(max_sample_delta=int(np.max(np.abs(noise))), snr_db=round(10*np.log10(p_s/p_n),1),
                changed=int(np.count_nonzero(noise)), total=len(orig))

if __name__ == "__main__":
    sr_samples, sr = synth_carrier(6.0)
    params = wave._wave_params(2, 2, sr, len(sr_samples)//2, "NONE", "not compressed")

    print("=== TEXT message ===")
    msg = "musiclang: the music you are hearing secretly contains this sentence. 🎵".encode()
    stego, info = embed(sr_samples, msg, ptype=1)
    print("  embed info:", info)
    print("  imperceptibility:", metrics(sr_samples, stego))
    ptype, got = extract(stego)
    print("  type:", TYPES[ptype], "| recovered exactly:", got == msg)
    print("  decoded text:", got.decode())

    print("\n=== JPEG image ===")
    from PIL import Image
    img = Image.new("RGB",(96,96))
    px=[]
    for y in range(96):
        for x in range(96):
            px.append(((x*8//3)%256,(y*8//3)%256,((x+y)*4//3)%256))
    img.putdata(px)
    bio=io.BytesIO(); img.save(bio,format="JPEG",quality=80); jpeg=bio.getvalue()
    print("  jpeg size:", len(jpeg), "bytes")
    stego2, info2 = embed(sr_samples, jpeg, ptype=2)
    print("  embed info:", info2)
    print("  imperceptibility:", metrics(sr_samples, stego2))
    ptype2, got2 = extract(stego2)
    print("  type:", TYPES[ptype2], "| recovered exactly:", got2 == jpeg)
    Image.open(io.BytesIO(got2)).verify(); print("  recovered bytes re-open as a valid JPEG: True")

    print("\n=== ERROR RECOVERY (redundancy at work) ===")
    rng = np.random.RandomState(0)
    # 1) scatter random bit-flips across the data LSBs
    for rate in (0.005, 0.02, 0.05, 0.10):
        noisy = stego2.copy()
        L = info2["header_slots"] + info2["body_slots"]
        idx = rng.choice(L, size=int(rate*L), replace=False)
        noisy[idx] ^= 1
        try:
            t,g = extract(noisy); ok = (g==jpeg)
        except Exception as e:
            ok = f"DETECTED+rejected ({e})"
        print(f"  random {rate*100:4.1f}% LSBs flipped (R={info2['body_R']}, corrects {(info2['body_R']-1)//2}/copy): recovered={ok}")
    # 2) a contiguous BURST (interleaving should defend)
    burst = stego2.copy(); burst[2000:2000+4000] ^= 1
    try: t,g = extract(burst); print("  4000-sample burst flipped: recovered =", g==jpeg)
    except Exception as e: print("  burst:", e)

    # 3) round trip through an actual .wav file on disk
    import os, tempfile
    wavpath = os.path.join(tempfile.gettempdir(), "carrier_stego.wav")
    write_wav(wavpath, stego2, params)
    pt,gg = extract_file(wavpath)
    print("\n  round trip through", wavpath + ":", gg==jpeg, "| type", TYPES[pt])
