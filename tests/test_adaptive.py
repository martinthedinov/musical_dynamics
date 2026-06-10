"""Adaptive psychoacoustic PCM carrier: more capacity, masked imperceptibility, speech-safe."""
import os
import numpy as np
import pytest
import soundfile as sf

from stego.carriers import embed_file, extract_file, capacity
from stego.carriers.adaptive import AdaptivePCMCarrier, allocate, MUSIC, SPEECH, KMAX, _MASK
from stego import pipeline


# ---------- synthetic carriers ----------
def _loud_music(path, seconds=12, sr=44100):
    t = np.linspace(0, seconds, seconds * sr, endpoint=False)
    s = (0.5 * np.sin(2 * np.pi * 110 * t) + 0.3 * np.sin(2 * np.pi * 220 * t)
         + 0.2 * np.sin(2 * np.pi * 660 * t))
    s /= np.max(np.abs(s)) + 1e-9
    sf.write(path, (np.stack([s, s], 1) * 30000).astype(np.int16), sr, subtype="PCM_16", format="WAV")

def _speech_like(path, seconds=10, sr=16000):
    """Voiced 'words' (formant resonances over a pitch pulse train) separated by silence,
       so the voice-activity gate has real silence to skip."""
    rng = np.random.RandomState(0)
    f0s = [110, 130, 98, 120]
    formants = [[700, 1220, 2600], [400, 1700, 2400], [600, 900, 2500]]
    out, i = [], 0
    while sum(len(c) for c in out) < seconds * sr:
        n = int(sr * 0.45); tt = np.arange(n) / sr
        f0 = f0s[i % len(f0s)]; F = formants[i % len(formants)]
        pulse = (np.mod(tt, 1.0 / f0) < (1.0 / sr) * 3).astype(float)   # glottal pulse train
        sig = np.zeros(n)
        for f in F:
            sig += np.sin(2 * np.pi * f * tt) * np.exp(-6 * np.mod(tt, 1.0 / f0) * f0)
        sig = sig * (0.6 + 0.4 * pulse) * np.hanning(n)
        out.append(sig)
        out.append(np.zeros(int(sr * (0.22 + 0.1 * rng.rand()))))       # silence between words
        i += 1
    mono = np.concatenate(out)[:seconds * sr]
    mono /= np.max(np.abs(mono)) + 1e-9
    sf.write(path, (mono * 22000).astype(np.int16), sr, subtype="PCM_16", format="WAV")


# ---------- round-trips ----------
def test_adaptive_music_roundtrip(alice_text, tmp_path):
    wav = str(tmp_path / "music.wav"); _loud_music(wav)
    pf = tmp_path / "alice.txt"; pf.write_bytes(alice_text)
    out = str(tmp_path / "stego.wav")
    info = embed_file(wav, out, str(pf), method="adaptive", profile="music")
    assert info["method"] == "adaptive" and info["profile"] == "music"
    rec, hdr = extract_file(out, str(tmp_path))
    assert open(rec, "rb").read() == alice_text
    assert hdr["method"] == "adaptive" and hdr["profile"] == "music"

def test_adaptive_speech_roundtrip(sonnet_text, tmp_path):
    wav = str(tmp_path / "speech.wav"); _speech_like(wav)
    pf = tmp_path / "msg.txt"; pf.write_bytes(sonnet_text[:200])
    out = str(tmp_path / "stego.wav")
    info = embed_file(wav, out, str(pf), method="adaptive", profile="speech")
    rec, hdr = extract_file(out, str(tmp_path))
    assert open(rec, "rb").read() == sonnet_text[:200]
    assert hdr["profile"] == "speech"

def test_auto_detect_distinguishes_uniform_and_adaptive(preamble_text, tmp_path):
    """A uniform-embedded and an adaptive-embedded file both extract via the same extract_file."""
    wav = str(tmp_path / "m.wav"); _loud_music(wav)
    pf = tmp_path / "p.txt"; pf.write_bytes(preamble_text)
    u = str(tmp_path / "u.wav"); embed_file(wav, u, str(pf), method="uniform")
    a = str(tmp_path / "a.wav"); embed_file(wav, a, str(pf), method="adaptive", profile="music")
    ru, hu = extract_file(u, str(tmp_path / "ou"))
    ra, ha = extract_file(a, str(tmp_path / "oa"))
    assert open(ru, "rb").read() == preamble_text and hu["method"] == "uniform"
    assert open(ra, "rb").read() == preamble_text and ha["method"] == "adaptive"


# ---------- the headline claims ----------
def test_capacity_exceeds_uniform_on_loud_audio(tmp_path):
    """On loud audio, adaptive packs strictly more than fixed 1-LSB (and more than 2-LSB)."""
    wav = str(tmp_path / "m.wav"); _loud_music(wav)
    uni1 = capacity(wav, n_lsb=1)["slots"]
    uni2 = capacity(wav, n_lsb=2)["slots"]
    adp = capacity(wav, method="adaptive", profile="music")["slots"]
    assert adp > uni1, f"adaptive {adp} should beat 1-LSB {uni1}"
    assert adp > uni2, f"adaptive {adp} should beat 2-LSB {uni2} on loud audio"

def test_speech_silence_is_untouched(tmp_path):
    """The voice-activity gate must leave silent samples byte-identical."""
    wav = str(tmp_path / "s.wav"); _speech_like(wav)
    before, _ = sf.read(wav, dtype="int16")
    pf = tmp_path / "p.bin"; pf.write_bytes(os.urandom(64))
    out = str(tmp_path / "stego.wav")
    embed_file(wav, out, str(pf), method="adaptive", profile="speech")
    after, _ = sf.read(out, dtype="int16")
    k, _ = allocate(np.ascontiguousarray(before, dtype=np.int16), SPEECH)
    silent = (k == 0)
    assert silent.sum() > before.size * 0.1, "test signal should have substantial silence"
    assert np.array_equal(before[silent], after[silent]), "silent samples were modified"

def test_imperceptibility_masking_bound(tmp_path):
    """By construction the embedding noise stays below local_signal / MASK_RATIO everywhere."""
    wav = str(tmp_path / "m.wav"); _loud_music(wav)
    before, _ = sf.read(wav, dtype="int16")
    flat = np.ascontiguousarray(before.reshape(-1), dtype=np.int16)
    pf = tmp_path / "p.bin"; pf.write_bytes(os.urandom(4000))
    out = str(tmp_path / "stego.wav")
    embed_file(wav, out, str(pf), method="adaptive", profile="music", redundancy=None)
    after, _ = sf.read(out, dtype="int16")
    delta = np.abs(after.reshape(-1).astype(np.int64) - flat.astype(np.int64))
    k, sig = allocate(flat, MUSIC)
    # wherever bits were written, |delta| < 2^k <= sig / MASK_RATIO  -> noise is masked
    touched = k > 0
    assert np.all(delta[touched] < (2 ** k[touched])), "delta exceeded the allocated bit-depth"
    assert np.all(delta[touched] < sig[touched] / _MASK[MUSIC] + 1.0), "noise exceeded the masking bound"
    assert np.all(delta[~touched] == 0), "samples allocated 0 bits were modified"

def test_robust_to_lsb_plane0_stripping(tmp_path):
    """Zeroing the entire LSB plane (a common 'sanitization') still leaves the file recoverable,
       because the data is spread across planes 0..k-1 and the fountain rebuilds the rest."""
    wav = str(tmp_path / "m.wav"); _loud_music(wav)
    payload = os.urandom(800)
    pf = tmp_path / "p.bin"; pf.write_bytes(payload)
    out = str(tmp_path / "stego.wav")
    embed_file(wav, out, str(pf), method="adaptive", profile="music", redundancy=None)
    data, sr = sf.read(out, dtype="int16")
    stripped = (data.reshape(-1).view(np.uint16) & np.uint16(0xFFFE)).view(np.int16).reshape(data.shape)
    strip_path = str(tmp_path / "stripped.wav")
    sf.write(strip_path, stripped, sr, subtype="PCM_16", format="WAV")
    rec, _ = extract_file(strip_path, str(tmp_path / "o"))
    assert open(rec, "rb").read() == payload, "did not survive LSB-plane-0 stripping"


# ---------- fail-safe ----------
def test_clean_file_has_no_header(tmp_path):
    wav = str(tmp_path / "clean.wav"); _loud_music(wav)
    with pytest.raises(pipeline.PipelineError):
        extract_file(wav, str(tmp_path / "o"))

def test_adaptive_with_password(preamble_text, tmp_path):
    from stego.crypto import CryptoError
    wav = str(tmp_path / "m.wav"); _loud_music(wav)
    pf = tmp_path / "p.txt"; pf.write_bytes(preamble_text[:100])
    out = str(tmp_path / "enc.wav")
    embed_file(wav, out, str(pf), method="adaptive", profile="music", password="hunter2")
    rec, _ = extract_file(out, str(tmp_path / "o"), password="hunter2")
    assert open(rec, "rb").read() == preamble_text[:100]
    with pytest.raises(CryptoError):
        extract_file(out, str(tmp_path / "ox"), password="wrong")
