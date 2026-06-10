"""Shared fixtures: synthesized carrier audio (WAV, FLAC, MP3, MIDI) and PD payload texts.

Audio carriers are synthesized deterministically so the tests are reproducible offline. Real-
world MP3/WAV files can be dropped into tests/data/ and `data_files()` will pick them up.
Wikipedia content can be fetched via tests/fetch_test_data.sh; tests fall back to the bundled
public-domain texts when those files are absent.
"""
import os, sys, pathlib
import numpy as np
import pytest

# Make the repo root importable so `import stego, mc_codec` works regardless of cwd.
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

DATA = pathlib.Path(__file__).resolve().parent / "data"

# ---------- payloads ----------
@pytest.fixture(scope="session")
def pd_texts():
    """All public-domain text fixtures available in tests/data/."""
    return {p.stem: p.read_bytes() for p in sorted(DATA.glob("*.txt"))}

@pytest.fixture(scope="session")
def alice_text():
    return (DATA / "gutenberg_alice_chapter1.txt").read_bytes()

@pytest.fixture(scope="session")
def sonnet_text():
    return (DATA / "shakespeare_sonnet18.txt").read_bytes()

@pytest.fixture(scope="session")
def preamble_text():
    return (DATA / "us_constitution_preamble.txt").read_bytes()

@pytest.fixture(scope="session")
def random_payload():
    """Incompressible random bytes — defeats any zlib-only stego scheme."""
    return os.urandom(2048)

# ---------- synthesized audio carriers ----------
SR = 44100

def _music_signal(seconds, seed=0, sr=SR):
    """Reproducible 'music-like' stereo signal: bass + mid pad + moving lead."""
    rng = np.random.RandomState(seed)
    t = np.linspace(0, seconds, int(seconds * sr), endpoint=False)
    sig = (0.40 * np.sin(2 * np.pi * 110 * t)
         + 0.30 * np.sin(2 * np.pi * 220 * t)
         + 0.30 * np.sin(2 * np.pi * (1200 + 200 * np.sin(2 * np.pi * 0.3 * t)) * t)
         + 0.005 * rng.standard_normal(t.size))     # gentle dither; too much noise breaks DSSS
    sig /= np.max(np.abs(sig)) + 1e-9
    left = (sig * 30000).astype(np.int16)
    right = (np.roll(sig, sr // 100) * 30000).astype(np.int16)
    return np.stack([left, right])      # (2, T) int16

@pytest.fixture(scope="session")
def short_wav(tmp_path_factory):
    """8s WAV — small carrier, suitable for light-payload tests."""
    import soundfile as sf
    p = tmp_path_factory.mktemp("audio") / "short.wav"
    stereo = _music_signal(8.0)
    sf.write(str(p), stereo.T, SR, subtype="PCM_16", format="WAV")
    return str(p)

@pytest.fixture(scope="session")
def long_wav(tmp_path_factory):
    """30s WAV — larger carrier."""
    import soundfile as sf
    p = tmp_path_factory.mktemp("audio") / "long.wav"
    stereo = _music_signal(30.0, seed=1)
    sf.write(str(p), stereo.T, SR, subtype="PCM_16", format="WAV")
    return str(p)

@pytest.fixture(scope="session")
def long_flac(tmp_path_factory):
    import soundfile as sf
    p = tmp_path_factory.mktemp("audio") / "long.flac"
    stereo = _music_signal(30.0, seed=2)
    sf.write(str(p), stereo.T, SR, subtype="PCM_16", format="FLAC")
    return str(p)

@pytest.fixture(scope="session")
def long_mp3(tmp_path_factory):
    """3-minute MP3 — generous capacity so the DSSS watermark has solid fountain redundancy
       (a tiny AES payload then survives the occasional post-MP3 bit error deterministically)."""
    pyav = pytest.importorskip("av")
    from stego.carriers.mp3 import _encode, _LOSSY_EXTS
    p = tmp_path_factory.mktemp("audio") / "long.mp3"
    stereo = _music_signal(180.0, seed=3)
    _encode(stereo, SR, str(p), _LOSSY_EXTS[".mp3"])
    return str(p)

@pytest.fixture(scope="session")
def long_mid(tmp_path_factory):
    """A multi-thousand-note MIDI track — realistic carrier for velocity-LSB stego."""
    mido = pytest.importorskip("mido")
    p = tmp_path_factory.mktemp("audio") / "long.mid"
    mid = mido.MidiFile(); tr = mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    import random; random.seed(7)
    for i in range(3000):
        pitch = 36 + (i * 7) % 48
        vel = 70 + random.randint(0, 40)        # >= 7, so n_lsb up to 3 is safe
        tr.append(mido.Message("note_on",  channel=0, note=pitch, velocity=vel, time=60))
        tr.append(mido.Message("note_off", channel=0, note=pitch, velocity=0,   time=120))
    mid.save(str(p))
    return str(p)
