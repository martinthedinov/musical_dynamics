"""Lossless PCM carrier: WAV / FLAC / AIFF via libsndfile (soundfile).

Works on any such file, MD-generated or not. Audio is handled as interleaved 16-bit samples;
data rides the low bit-plane(s). Plane 0 uses LSB *matching* (±1) rather than replacement, so
the change is the same inaudible ±1 LSB but with less statistical signature. Higher planes
(n_lsb>1) trade imperceptibility for capacity via plain replacement.
"""
import os
import numpy as np
from .base import Carrier

_FMT = {".wav": "WAV", ".flac": "FLAC", ".aiff": "AIFF", ".aif": "AIFF", ".aifc": "AIFF"}

class PCMCarrier(Carrier):
    EXTS = frozenset(_FMT)

    def __init__(self, path):
        import soundfile as sf
        data, sr = sf.read(path, dtype="int16", always_2d=True)   # (frames, channels)
        self.sr = sr
        self.shape = data.shape
        self.flat = np.ascontiguousarray(data.reshape(-1), dtype=np.int16)
        self.in_format = sf.info(path).format

    def num_units(self):
        return self.flat.size

    def get_bits(self, n_lsb):
        u = self.flat.view(np.uint16)
        bits = np.empty(self.flat.size * n_lsb, dtype=np.uint8)
        for p in range(n_lsb):
            bits[p::n_lsb] = ((u >> p) & 1).astype(np.uint8)
        return bits

    def set_bits(self, bits, n_lsb):
        if n_lsb == 1:
            cur = (self.flat.view(np.uint16) & 1).astype(np.uint8)
            tgt = bits.astype(np.uint8)
            s = self.flat.astype(np.int32)
            step = np.where(s >= 32767, -1, np.where(s <= -32768, 1, 1)).astype(np.int32)
            s = np.where(cur != tgt, s + step, s)             # ±1 flips the LSB without clipping
            self.flat = s.astype(np.int16)
        else:
            u = self.flat.view(np.uint16).astype(np.uint32)
            for p in range(n_lsb):
                tgt = bits[p::n_lsb].astype(np.uint32)
                u = (u & ~np.uint32(1 << p)) | (tgt << p)
            self.flat = u.astype(np.uint16).view(np.int16).copy()

    def write(self, path):
        import soundfile as sf
        fmt = _FMT.get(os.path.splitext(path)[1].lower(), self.in_format)
        sf.write(path, self.flat.reshape(self.shape), self.sr, subtype="PCM_16", format=fmt)
