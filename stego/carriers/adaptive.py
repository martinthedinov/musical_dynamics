"""Adaptive psychoacoustic PCM carrier — pack more data, less audibly, speech-safe.

Instead of a fixed number of LSBs per sample, allocate a per-sample bit-depth k[i] from the
LOCAL signal energy: loud passages hide more bits (the signal masks the embedding noise),
quiet/silent passages hide fewer or none. The allocation is computed from the *high* bits of
the samples (everything at or above bit KMAX), which embedding never touches — so the decoder
reproduces the exact same allocation blind, from the stego file alone.

Why this is better than fixed n-LSB:
  * More capacity: up to KMAX bits per sample where the signal is loud (vs a fixed 1).
  * More imperceptible: the embedding noise tracks the signal envelope and is provably kept a
    fixed ratio below the local signal (masking); silence is left untouched.
  * More robust to LSB-plane stripping: data is spread across planes 0..k-1, so zeroing the
    lowest plane only corrupts a fraction of the slots — the fountain code rebuilds the rest.

Two profiles (chosen at embed, auto-detected at extract):
  * music  — energy-masked allocation across the whole file (max capacity).
  * speech — adds a voice-activity gate (no embedding in silence) and a gentler mask, so the
             speech stays natural and intelligible.

Invariance proof: k[i] is derived from `flat >> KMAX` (arithmetic shift drops the low KMAX
bits). Embedding only ever writes bits 0..k-1 with k <= KMAX, so `flat >> KMAX` — and therefore
every k[i] — is identical before and after embedding. No side channel is needed.
"""
import os
import numpy as np
from .base import Carrier

_FMT = {".wav": "WAV", ".flac": "FLAC", ".aiff": "AIFF", ".aif": "AIFF", ".aifc": "AIFF"}

# Profile codes ride in the pipeline header's "n_lsb" byte (kept distinct from uniform 1..4).
MUSIC, SPEECH = 16, 17
PROFILES = (MUSIC, SPEECH)
PROFILE_NAME = {MUSIC: "music", SPEECH: "speech", "music": MUSIC, "speech": SPEECH}

KMAX = 4                                   # invariance boundary: never write at/above this bit
WINDOW = 256                               # samples for the local-energy envelope
_KMAX_P = {MUSIC: 4, SPEECH: 3}            # per-profile cap on bits/sample
_MASK = {MUSIC: 32.0, SPEECH: 96.0}        # embedding noise kept this many x below local signal
_VAD_FRACTION = 0.06                       # speech: skip samples below this fraction of the loud level


def _moving_rms(x, w):
    """Symmetric moving RMS via a cumulative sum of squares (fast, fully deterministic)."""
    x2 = x.astype(np.float64) ** 2
    c = np.concatenate([[0.0], np.cumsum(x2)])
    half = w // 2
    n = x.size
    lo = np.clip(np.arange(n) - half, 0, n)
    hi = np.clip(np.arange(n) + half + 1, 0, n)
    return np.sqrt((c[hi] - c[lo]) / np.maximum(1, hi - lo))


def allocate(flat, profile):
    """Return (k, sig): per-sample bit-depth and the local signal magnitude it was based on.
       Both are computed only from the embedding-invariant high bits."""
    hi = flat.astype(np.int32) >> KMAX                  # arithmetic shift -> independent of low KMAX bits
    env = _moving_rms(hi, WINDOW)
    sig = env * (1 << KMAX)                             # ~ local signal magnitude
    allow = np.log2(np.maximum(sig, 1e-9) / _MASK[profile])
    k = np.clip(np.floor(allow), 0, _KMAX_P[profile]).astype(np.int64)
    if profile == SPEECH:
        loud = np.percentile(sig, 95) + 1e-9
        k[sig < _VAD_FRACTION * loud] = 0              # voice-activity gate: silence carries nothing
    return k, sig


class AdaptivePCMCarrier(Carrier):
    EXTS = frozenset(_FMT)

    def __init__(self, path):
        import soundfile as sf
        data, sr = sf.read(path, dtype="int16", always_2d=True)
        self.sr = sr
        self.shape = data.shape
        self.flat = np.ascontiguousarray(data.reshape(-1), dtype=np.int16)
        self.in_format = sf.info(path).format

    def candidates(self):
        return PROFILES

    def _k(self, profile):
        return allocate(self.flat, profile)[0]

    def capacity_bits(self, profile):
        return int(self._k(profile).sum())

    @staticmethod
    def _plane_offsets(k):
        # PLANE-MAJOR layout: all plane-0 bits, then all plane-1 bits, ... Each plane is a
        # contiguous block, so zeroing one plane corrupts one contiguous slot region (which the
        # stride-spread header and cell-spread fountain tolerate) instead of aliasing with them.
        counts = [int((k > b).sum()) for b in range(KMAX)]
        offsets = np.cumsum([0] + counts)[:-1]
        return counts, offsets

    def get_bits(self, profile):
        k = self._k(profile)
        counts, offsets = self._plane_offsets(k)
        bits = np.zeros(int(sum(counts)), dtype=np.uint8)
        u = self.flat.view(np.uint16)
        for b in range(KMAX):
            sel = np.nonzero(k > b)[0]
            if sel.size:
                bits[offsets[b]:offsets[b] + sel.size] = ((u[sel] >> b) & 1).astype(np.uint8)
        return bits

    def set_bits(self, bits, profile):
        k = self._k(profile)
        counts, offsets = self._plane_offsets(k)
        u = self.flat.view(np.uint16).astype(np.uint32)
        for b in range(KMAX):
            sel = np.nonzero(k > b)[0]
            if sel.size:
                tgt = bits[offsets[b]:offsets[b] + sel.size].astype(np.uint32)
                u[sel] = (u[sel] & ~np.uint32(1 << b)) | (tgt << b)
        self.flat = u.astype(np.uint16).view(np.int16).copy()

    def write(self, path):
        import soundfile as sf
        fmt = _FMT.get(os.path.splitext(path)[1].lower(), self.in_format)
        sf.write(path, self.flat.reshape(self.shape), self.sr, subtype="PCM_16", format=fmt)
