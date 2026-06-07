"""Lossless audio carriers: WAV, FLAC. Hide arbitrary files in real music files."""
import os
import numpy as np
import pytest
import soundfile as sf

from stego.carriers import embed_file, extract_file, capacity, open_carrier
from stego import pipeline


# ---------- basic round-trip on every PD fixture ----------
@pytest.mark.parametrize("name", ["us_constitution_preamble",
                                  "shakespeare_sonnet18",
                                  "poe_raven_stanza1",
                                  "gutenberg_alice_chapter1"])
def test_wav_byte_exact(long_wav, pd_texts, tmp_path, name):
    payload = pd_texts[name]
    pf = tmp_path / f"{name}.txt"; pf.write_bytes(payload)
    out = tmp_path / "stego.wav"
    info = embed_file(long_wav, str(out), str(pf))
    assert info["payload_bytes"] == len(payload)
    rec_path, hdr = extract_file(str(out), str(tmp_path))
    assert open(rec_path, "rb").read() == payload, "WAV: payload corrupted in round-trip"

def test_flac_byte_exact(long_flac, alice_text, tmp_path):
    pf = tmp_path / "alice.txt"; pf.write_bytes(alice_text)
    embed_file(long_flac, str(tmp_path / "out.flac"), str(pf))
    rec, _ = extract_file(str(tmp_path / "out.flac"), str(tmp_path))
    assert open(rec, "rb").read() == alice_text


# ---------- imperceptibility ----------
def test_imperceptibility_one_lsb(long_wav, alice_text, tmp_path):
    """Plane-0 embedding uses LSB matching (+/-1), so no sample changes by more than 1."""
    pf = tmp_path / "msg.txt"; pf.write_bytes(alice_text)
    out = tmp_path / "stego.wav"
    embed_file(long_wav, str(out), str(pf), n_lsb=1)
    a, _ = sf.read(long_wav, dtype="int16")
    b, _ = sf.read(str(out), dtype="int16")
    max_delta = int(np.max(np.abs(a.astype(np.int32) - b.astype(np.int32))))
    assert max_delta <= 1, f"plane-0 embed changed a sample by {max_delta}"


# ---------- encryption ----------
def test_aes_gcm_roundtrip_and_wrong_password(long_wav, alice_text, tmp_path):
    from stego.crypto import CryptoError
    pf = tmp_path / "msg.txt"; pf.write_bytes(alice_text)
    out = tmp_path / "enc.wav"
    embed_file(long_wav, str(out), str(pf), password="hunter2")
    rec, _ = extract_file(str(out), str(tmp_path), password="hunter2")
    assert open(rec, "rb").read() == alice_text
    with pytest.raises(CryptoError):
        extract_file(str(out), str(tmp_path / "x"), password="wrong")


# ---------- redundancy: survives scattered noise and large overwrites ----------
def _embed_and_get_samples(in_wav, payload, tmp_out, redundancy=None):
    pf = os.path.join(tmp_out, "p.bin"); open(pf, "wb").write(payload)
    out = os.path.join(tmp_out, "stego.wav")
    info = embed_file(in_wav, out, pf, redundancy=redundancy)
    a, sr = sf.read(out, dtype="int16")
    return out, a, sr, info

@pytest.mark.parametrize("noise_frac", [0.005, 0.01, 0.02])
def test_recovers_under_scattered_lsb_noise(long_wav, random_payload, tmp_path, noise_frac):
    """Reed-Solomon (inner) repairs scattered bit flips."""
    out_path, a, sr, _ = _embed_and_get_samples(long_wav, random_payload[:1024], str(tmp_path))
    flat = a.reshape(-1).copy()
    rng = np.random.RandomState(42)
    idx = rng.choice(flat.size, size=int(noise_frac * flat.size), replace=False)
    flat[idx] = (flat[idx].astype(np.int32) ^ 1).astype(np.int16)
    sf.write(out_path, flat.reshape(a.shape), sr, subtype="PCM_16", format="WAV")
    rec, _ = extract_file(out_path, str(tmp_path))
    assert open(rec, "rb").read() == random_payload[:1024]

@pytest.mark.parametrize("overwrite_frac", [0.30, 0.60, 0.80])
def test_recovers_under_contiguous_overwrite(long_wav, random_payload, tmp_path, overwrite_frac):
    """Fountain code (outer) rebuilds the file when a large contiguous region is wiped."""
    out_path, a, sr, info = _embed_and_get_samples(long_wav, random_payload[:1024], str(tmp_path))
    flat = a.reshape(-1).copy()
    n = int(overwrite_frac * flat.size); start = (flat.size - n) // 2
    flat[start:start + n] = 0
    sf.write(out_path, flat.reshape(a.shape), sr, subtype="PCM_16", format="WAV")
    rec, _ = extract_file(out_path, str(tmp_path))
    assert open(rec, "rb").read() == random_payload[:1024]


# ---------- fail-safe: refuse rather than return wrong data ----------
def test_overwriting_too_much_refuses(long_wav, random_payload, tmp_path):
    out_path, a, sr, _ = _embed_and_get_samples(long_wav, random_payload[:2048], str(tmp_path))
    flat = a.reshape(-1).copy()
    flat[:int(0.95 * flat.size)] = 0      # destroy almost everything
    sf.write(out_path, flat.reshape(a.shape), sr, subtype="PCM_16", format="WAV")
    with pytest.raises(pipeline.PipelineError):
        extract_file(out_path, str(tmp_path))

def test_clean_carrier_has_no_header(short_wav, tmp_path):
    with pytest.raises(pipeline.PipelineError):
        extract_file(short_wav, str(tmp_path))


# ---------- capacity reporting ----------
def test_capacity_reasonable(long_wav):
    info = capacity(long_wav)
    assert info["slots"] > 100_000
    assert info["max_symbols"] > 100
