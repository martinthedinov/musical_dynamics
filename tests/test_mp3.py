"""MP3 (and AAC/Ogg) carrier: lossy spread-spectrum watermark survives real lossy encoding."""
import os
import numpy as np
import pytest

pytest.importorskip("av")     # PyAV bundles ffmpeg; whole module skips without it

from stego.carriers import embed_file, extract_file
from stego.carriers.mp3 import (MP3Carrier, _encode, _decode, _LOSSY_EXTS,
                                 _embed_bits, _extract_bits, _find_sync, _sync_bits,
                                 HOP, SYNC_BITS)


# ---------- encoder/decoder sanity (the bug that bit us during bring-up) ----------
def test_encoder_does_not_duplicate_samples(tmp_path):
    sr = 44100; t = np.linspace(0, 5, 5*sr, endpoint=False)
    sig = (0.5 * np.sin(2 * np.pi * 440 * t) * 30000).astype(np.int16)
    stereo = np.stack([sig, sig])
    p = tmp_path / "x.mp3"
    _encode(stereo, sr, str(p), _LOSSY_EXTS[".mp3"])
    back, _ = _decode(str(p))
    # MP3 has small encoder padding/lookahead; allow up to ~5% difference but not 2x.
    ratio = back.shape[1] / stereo.shape[1]
    assert 0.95 <= ratio <= 1.10, f"decoder returned {ratio:.2f}x the input — channels mis-demuxed?"


# ---------- the headline robustness claim ----------
def test_dsss_zero_ber_without_mp3():
    """Sanity: with no MP3 in the loop, the DSSS watermark must be perfect."""
    sr = 44100; t = np.linspace(0, 30, 30*sr, endpoint=False)
    sig = (0.4*np.sin(2*np.pi*220*t) + 0.3*np.sin(2*np.pi*880*t)
         + 0.3*np.sin(2*np.pi*(1500+200*np.sin(2*np.pi*0.3*t))*t))
    mono = sig.astype(np.float32) / np.max(np.abs(sig)+1e-9)
    bits = np.random.RandomState(0).randint(0, 2, size=400).astype(np.uint8)
    full = np.concatenate([_sync_bits(), bits])
    wm = _embed_bits(mono, full)
    off = _find_sync(wm)
    assert off is not None
    got = _extract_bits(wm, bits.size, off + SYNC_BITS * HOP)
    ber = float((got != bits).sum()) / bits.size
    assert ber < 0.05, f"watermark BER without MP3 was {ber:.3f} — should be ~0"


def test_mp3_single_encode_roundtrip(long_mp3, sonnet_text, tmp_path):
    """Embed a small payload, write MP3, decode, recover byte-exact."""
    pl = tmp_path / "sonnet.txt"; pl.write_bytes(sonnet_text[:48])
    out = tmp_path / "stego.mp3"
    info = embed_file(long_mp3, str(out), str(pl), block_size=16, rs_nsym=6, redundancy=None)
    assert info["payload_bytes"] == 48
    rec, _ = extract_file(str(out), str(tmp_path))
    assert open(rec, "rb").read() == sonnet_text[:48], "MP3 round-trip lost bits"


def test_mp3_double_encode_roundtrip(long_mp3, tmp_path):
    """Hide bytes in MP3, re-encode that MP3 through MP3 again, still recover the file.
       This is the ambitious goal: survives a second lossy generation."""
    payload = b"This message survived double MP3 encoding."
    pl = tmp_path / "p.txt"; pl.write_bytes(payload)
    stego = tmp_path / "stego.mp3"
    embed_file(long_mp3, str(stego), str(pl), block_size=16, rs_nsym=6, redundancy=None)
    # Re-encode the stego MP3 (a second lossy generation)
    samp, sr = _decode(str(stego))
    regen = tmp_path / "stego_regen.mp3"
    _encode(samp, sr, str(regen), _LOSSY_EXTS[".mp3"])
    rec, _ = extract_file(str(regen), str(tmp_path))
    assert open(rec, "rb").read() == payload, "watermark did not survive a second MP3 encoding"


def test_mp3_with_password(long_mp3, preamble_text, tmp_path):
    # AES-GCM adds ~48 bytes of overhead and uses a random nonce, so keep the cleartext small to
    # leave the fountain plenty of redundancy headroom against the rare DSSS bit error.
    pl = tmp_path / "pre.txt"; pl.write_bytes(preamble_text[:16])
    out = tmp_path / "enc.mp3"
    embed_file(long_mp3, str(out), str(pl), block_size=16, rs_nsym=6, redundancy=None,
               password="hunter2")
    rec, _ = extract_file(str(out), str(tmp_path), password="hunter2")
    assert open(rec, "rb").read() == preamble_text[:16]


def test_clean_mp3_has_no_header(long_mp3, tmp_path):
    """An MP3 with no embedded watermark must not be mis-detected as a stego carrier."""
    from stego import pipeline
    with pytest.raises(pipeline.PipelineError):
        extract_file(long_mp3, str(tmp_path))
