"""Self-test for the stego package:  python -m stego.selftest

Synthesizes a music carrier, hides an arbitrary binary file in it (WAV and FLAC), proves
bit-exact recovery, then damages the carrier to show the fountain+Reed-Solomon redundancy
at work, and checks AES-GCM round-trip + wrong-password rejection.
"""
import os, tempfile
import numpy as np
from . import pipeline, crypto
from .carriers import open_carrier, embed_file, extract_file, capacity

def _synth_wav(path, seconds=8.0, sr=44100):
    import soundfile as sf
    prog = [[57, 60, 64, 69], [53, 57, 60, 65], [48, 52, 55, 60], [55, 59, 62, 67]]  # Am F C G
    seg_n = int(sr * seconds / len(prog)); out = []
    for chord in prog:
        t = np.linspace(0, seconds / len(prog), seg_n, endpoint=False); s = np.zeros(seg_n)
        for m in chord:
            s += np.sin(2 * np.pi * (440 * 2 ** ((m - 69) / 12)) * t) / len(chord)
        env = np.minimum(1, np.minimum(t * 8, (seconds / len(prog) - t) * 8)); out.append(s * env)
    mono = np.concatenate(out); mono /= np.max(np.abs(mono)) + 1e-9
    stereo = np.stack([mono * 0.3, np.roll(mono, 7) * 0.3], axis=1)
    sf.write(path, (stereo * 32767).astype(np.int16), sr, subtype="PCM_16", format="WAV")

def _max_lsb_delta(a_path, b_path):
    import soundfile as sf
    a, _ = sf.read(a_path, dtype="int16"); b, _ = sf.read(b_path, dtype="int16")
    return int(np.max(np.abs(a.astype(np.int32) - b.astype(np.int32))))

def main():
    d = tempfile.mkdtemp(prefix="stego_")
    wav = os.path.join(d, "carrier.wav"); _synth_wav(wav)
    print("== capacity ==");  print("  ", capacity(wav))

    # an arbitrary binary "file" (incompressible random bytes)
    payload = os.urandom(6000)
    pf = os.path.join(d, "secret.bin"); open(pf, "wb").write(payload)

    print("\n== WAV round trip ==")
    info = embed_file(wav, os.path.join(d, "stego.wav"), pf)
    print("  embed:", {k: info[k] for k in ("K", "n_symbols", "redundancy", "rs_nsym", "payload_bytes", "n_lsb")})
    print("  max sample delta (imperceptibility):", _max_lsb_delta(wav, os.path.join(d, "stego.wav")))
    out, hdr = extract_file(os.path.join(d, "stego.wav"), d)
    got = open(out, "rb").read()
    print("  recovered file name:", os.path.basename(out), "| bit-exact:", got == payload)

    print("\n== FLAC carrier (lossless re-encode) ==")
    info = embed_file(wav, os.path.join(d, "stego.flac"), pf)
    out, _ = extract_file(os.path.join(d, "stego.flac"), d)
    print("  FLAC bit-exact recovery:", open(out, "rb").read() == payload)

    print("\n== redundancy under damage (fountain + Reed-Solomon) ==")
    # embed at 'fill' so symbols cover the whole carrier (max damage tolerance)
    c = open_carrier(wav); rinfo = pipeline.embed(c, payload, "secret.bin", redundancy=None)
    c.write(os.path.join(d, "rdx.wav"))
    print("  embedded at redundancy %sx -> tolerates losing %s of symbols" % (rinfo["redundancy"], rinfo["tolerates_symbol_loss"]))
    base = open_carrier(os.path.join(d, "rdx.wav")).flat.copy()
    rng = np.random.RandomState(0)
    for label, mutate in [
        ("scattered 0.5% LSB flips", lambda s: _flip(s, rng, int(0.005 * s.size))),
        ("scattered 1% LSB flips",   lambda s: _flip(s, rng, int(0.01 * s.size))),
        ("scattered 2% LSB flips",   lambda s: _flip(s, rng, int(0.02 * s.size))),
        ("contiguous 30% overwrite", lambda s: _overwrite(s, 0.30)),
        ("contiguous 60% overwrite", lambda s: _overwrite(s, 0.60)),
        ("contiguous 80% overwrite", lambda s: _overwrite(s, 0.80)),
    ]:
        c2 = open_carrier(os.path.join(d, "rdx.wav")); c2.flat = mutate(base.copy())
        try:
            name, data, _ = pipeline.extract(c2); ok = (data == payload)
        except Exception as e:
            ok = "REFUSED: %s" % type(e).__name__
        print("  %-26s -> recovered=%s" % (label, ok))

    print("\n== AES-GCM password ==")
    embed_file(wav, os.path.join(d, "enc.wav"), pf, password="hunter2")
    out, hdr = extract_file(os.path.join(d, "enc.wav"), d, password="hunter2")
    print("  correct password  -> bit-exact:", open(out, "rb").read() == payload, "| flags:", hdr["flags"])
    try:
        extract_file(os.path.join(d, "enc.wav"), d, password="wrong"); print("  wrong password     -> (should not reach here)")
    except crypto.CryptoError:
        print("  wrong password     -> rejected ✓")

    print("\n== MP3 carrier (lossy spread-spectrum watermark) ==")
    try:
        from .carriers.mp3 import _encode, _decode, _LOSSY_EXTS
        # synthesize a longer signal so MP3 capacity is enough for a short payload
        sr_mp3 = 44100; secs = 90
        t = np.linspace(0, secs, secs*sr_mp3, endpoint=False)
        s = 0.4*np.sin(2*np.pi*110*t) + 0.3*np.sin(2*np.pi*220*t) + 0.3*np.sin(2*np.pi*(1200 + 200*np.sin(2*np.pi*0.3*t))*t)
        s /= np.max(np.abs(s)+1e-9)
        stereo = np.stack([(s*30000).astype(np.int16), (np.roll(s,17)*30000).astype(np.int16)])
        mp3_in = os.path.join(d, "song.mp3"); _encode(stereo, sr_mp3, mp3_in, _LOSSY_EXTS[".mp3"])
        msg = b"hidden in an MP3 via DSSS"
        mp3_pl = os.path.join(d, "msg.txt"); open(mp3_pl, "wb").write(msg)
        info = embed_file(mp3_in, os.path.join(d, "stego.mp3"), mp3_pl,
                          redundancy=None, block_size=16, rs_nsym=6)
        print("  embed:", {k: info[k] for k in ('K','n_symbols','redundancy','payload_bytes')})
        out, _ = extract_file(os.path.join(d, "stego.mp3"), d)
        print("  single MP3 round-trip -> bit-exact:", open(out, "rb").read() == msg)
        # second encoding generation
        s2, _ = _decode(os.path.join(d, "stego.mp3"))
        _encode(s2, sr_mp3, os.path.join(d, "stego_re.mp3"), _LOSSY_EXTS[".mp3"])
        try:
            out2, _ = extract_file(os.path.join(d, "stego_re.mp3"), d)
            print("  double MP3 encode    -> bit-exact:", open(out2, "rb").read() == msg)
        except Exception as e:
            print("  double MP3 encode    -> failed (acceptable; survival depends on track):", e)
    except ImportError:
        print("  PyAV not installed — MP3 carrier disabled (lossless WAV/FLAC still works).")

def _flip(s, rng, n):
    idx = rng.choice(s.size, size=n, replace=False)
    s[idx] = (s[idx].astype(np.int32) ^ 1).astype(np.int16)   # flip LSB
    return s

def _overwrite(s, frac):
    n = int(frac * s.size); start = (s.size - n) // 2
    s[start:start + n] = 0
    return s

if __name__ == "__main__":
    main()
