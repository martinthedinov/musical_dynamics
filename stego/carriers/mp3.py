"""Lossy-audio carrier (MP3 / AAC / Ogg) via PyAV + spread-spectrum watermarking.

LSB tampering on decoded PCM is destroyed by lossy re-encoding — that's the point of
psychoacoustic compression. To hide data inside an MP3 that *stays* an MP3, we need a real
audio watermark in the frequency domain.

Scheme (DSSS in the mid-band of overlap-add STFT frames):
  * Decode to int16 PCM with PyAV (bundles ffmpeg). Mix channels for analysis.
  * Frame at N samples, hop N/2 (Hann OLA reconstructs perfectly when nothing is changed).
  * For each frame, FFT and look at a band of K bins in the mid-frequency range — high enough
    that MP3 keeps the energy (it's where ears are most sensitive), low enough that anti-alias
    filtering doesn't wreck it.
  * DSSS: a fixed PN sequence p[k] ∈ {-1,+1} of length K. To embed bit b∈{0,1}, *add*
    α·avgMag·(2b-1)·p[k] to the magnitudes (phase preserved). To extract, FFT, correlate
    magnitudes with p — the sign gives the bit.
  * Re-synthesize frames with OLA, re-encode to the target lossy format.
  * Sync: a known PN preamble of SYNC_BITS symbols at the file start lets the decoder find
    sample-accurate alignment (handles MP3 lookahead/padding offsets).

Capacity ≈ sr / HOP bits/sec ≈ 43 b/s at sr=44.1k, N=2048 — a 3-min track holds ~7700 bits.
After RS + fountain headroom that lands around 150–300 bytes of payload — the cost of MP3.
"""
import os
import numpy as np
from .base import Carrier

# decoder MUST agree with encoder
N            = 2048
HOP          = N // 2
BAND_LO_BIN  = 60
BAND_HI_BIN  = 220
ALPHA        = 0.35           # watermark strength (fraction of in-band avg magnitude)
PN_SEED      = 0xA17C0DE
SYNC_BITS    = 32
SYNC_SEED    = 0x5719BEEF

_LOSSY_EXTS = {
    ".mp3": ("mp3",  "libmp3lame", 192_000),
    ".aac": ("adts", "aac",        192_000),
    ".m4a": ("ipod", "aac",        192_000),
    ".ogg": ("ogg",  "libvorbis",  192_000),
}


def _pn(seed, length):
    rs = np.random.RandomState(seed)
    return (rs.randint(0, 2, size=length).astype(np.int8) * 2 - 1).astype(np.float32)

_BAND_PN_CACHE = None
def _band_pn():
    global _BAND_PN_CACHE
    if _BAND_PN_CACHE is None: _BAND_PN_CACHE = _pn(PN_SEED, BAND_HI_BIN - BAND_LO_BIN)
    return _BAND_PN_CACHE

_SYNC_CACHE = None
def _sync_bits():
    global _SYNC_CACHE
    if _SYNC_CACHE is None: _SYNC_CACHE = ((_pn(SYNC_SEED, SYNC_BITS) + 1) // 2).astype(np.uint8)
    return _SYNC_CACHE


def _frame_count(n_samples): return max(0, 1 + (n_samples - N) // HOP)
def _hann():                 return np.hanning(N).astype(np.float32)

# ---------- watermark embed / extract on a mono float32 signal ----------
def _embed_bits(mono, bits):
    """Add DSSS watermark to frames 0..len(bits)-1. OLA reconstruction via Hann window."""
    out = mono.astype(np.float32).copy()
    p   = _band_pn()
    w   = _hann()
    bipolar = (2.0 * bits.astype(np.float32) - 1.0)
    for i, b in enumerate(bipolar):
        s = i * HOP
        if s + N > out.size: break
        frame = out[s:s + N] * w
        F = np.fft.rfft(frame)
        mag = np.abs(F); ang = np.angle(F)
        # Scale by frame peak so silent frames don't get clobbered and tonal frames get a
        # watermark proportional to their energy (psychoacoustically reasonable).
        scale = float(np.max(mag)) + 1e-6
        band = mag[BAND_LO_BIN:BAND_HI_BIN]
        band = np.maximum(band + ALPHA * scale * b * p, 1e-4)
        mag[BAND_LO_BIN:BAND_HI_BIN] = band
        F2 = mag * np.exp(1j * ang)
        # write the *difference* back (additive OLA) so overlapping frames sum correctly
        out[s:s + N] += (np.fft.irfft(F2).astype(np.float32) - frame)
    return out

def _extract_bits(mono, n_bits, sample_offset=0):
    """Demodulate `n_bits` from `mono` starting at `sample_offset` (one bit per frame)."""
    p = _band_pn(); w = _hann()
    bits = np.zeros(n_bits, dtype=np.uint8)
    for i in range(n_bits):
        s = sample_offset + i * HOP
        if s + N > mono.size: break
        frame = mono[s:s + N] * w
        F = np.fft.rfft(frame); mag = np.abs(F)
        band = mag[BAND_LO_BIN:BAND_HI_BIN]
        # correlate with the PN, removing the mean so a flat (silent) band contributes ~0
        bits[i] = 1 if float(np.dot(band - band.mean(), p)) > 0 else 0
    return bits

def _find_sync(mono):
    """Search the start of `mono` for the sync preamble; return best sample offset, or None."""
    sync = _sync_bits()
    max_search = min(mono.size - SYNC_BITS * HOP - N, N * 32)
    if max_search <= 0: return None
    # Coarse scan, then fine search around the best hit.
    step = max(1, HOP // 8)
    best_score, best_off = -1.0, 0
    for off in range(0, max_search, step):
        got = _extract_bits(mono, SYNC_BITS, off)
        score = float((got == sync).sum())
        if score > best_score: best_score, best_off = score, off
    lo, hi = max(0, best_off - step), min(max_search, best_off + step)
    for off in range(lo, hi + 1):
        got = _extract_bits(mono, SYNC_BITS, off)
        score = float((got == sync).sum())
        if score > best_score: best_score, best_off = score, off
    return best_off if best_score >= 0.75 * SYNC_BITS else None


# ---------- PyAV decode / encode ----------
def _decode(path):
    """Decode any audio file to int16 PCM (2, T) at the file's native sample rate.
       Always returns interleaved (packed) samples de-muxed into 2 planar channels."""
    import av
    container = av.open(path); stream = container.streams.audio[0]
    sr = stream.sample_rate or 44100
    resampler = av.audio.resampler.AudioResampler(format="s16", layout="stereo", rate=sr)
    chunks = []
    for frame in container.decode(audio=0):
        for out in resampler.resample(frame):
            arr = out.to_ndarray()                # shape (1, 2*nsamples) for s16 packed stereo
            if arr.ndim == 1: arr = arr.reshape(1, -1)
            # demux packed L,R,L,R -> planar (2, n)
            packed = arr.reshape(-1)
            n = packed.size // 2
            chunks.append(packed[:n * 2].reshape(n, 2).T)
    container.close()
    if not chunks: return np.zeros((2, 0), dtype=np.int16), int(sr)
    return np.concatenate(chunks, axis=1).astype(np.int16), int(sr)

def _encode(samples_int16, sr, path, fmt_key):
    import av
    fmt, codec_name, bit_rate = fmt_key
    container = av.open(path, mode="w", format=fmt)
    stream = container.add_stream(codec_name, rate=sr)
    stream.bit_rate = bit_rate
    layout = "stereo"
    frame_size = getattr(stream.codec_context, "frame_size", None) or 1152
    interleaved = samples_int16.T.reshape(-1).astype(np.int16)   # L,R,L,R,...
    total = interleaved.size // 2
    pts = 0
    for off in range(0, total, frame_size):
        n = min(frame_size, total - off)
        # PyAV s16 (packed) wants shape (1, 2*n) interleaved L,R
        chunk = interleaved[off * 2:(off + n) * 2].reshape(1, -1).copy()
        af = av.AudioFrame.from_ndarray(np.ascontiguousarray(chunk), format="s16", layout=layout)
        af.sample_rate = sr; af.pts = pts; pts += n
        for pkt in stream.encode(af): container.mux(pkt)
    for pkt in stream.encode(): container.mux(pkt)
    container.close()


class MP3Carrier(Carrier):
    """Lossy audio (MP3 / AAC / Ogg). One DSSS bit per analysis frame.

    On embed: decode → embed bits + sync preamble at start → re-encode.
    On extract: decode → search for sync → demodulate the rest. The pipeline calls get_bits()
    once and treats it as the carrier's slot array.
    """
    EXTS = frozenset(_LOSSY_EXTS)

    def __init__(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext not in _LOSSY_EXTS:
            raise ValueError("MP3Carrier: unsupported extension %r" % ext)
        self.fmt_key = _LOSSY_EXTS[ext]
        self.in_path = path
        self.samples, self.sr = _decode(path)             # (2, T) int16
        self._mono = self.samples.astype(np.float32).mean(axis=0) / 32768.0
        self._capacity = max(0, _frame_count(self._mono.size) - SYNC_BITS)
        # Demodulate any existing watermark (so extract works on a re-decoded file). If sync is
        # not present (clean carrier on the embed path), report zeros sized to capacity.
        self._current = self._try_demodulate()

    def _try_demodulate(self):
        off = _find_sync(self._mono)
        if off is None:
            return np.zeros(self._capacity, dtype=np.uint8)
        body = off + SYNC_BITS * HOP
        n = min(self._capacity, _frame_count(self._mono.size) - SYNC_BITS - (body - off) // HOP)
        if n <= 0: return np.zeros(self._capacity, dtype=np.uint8)
        bits = _extract_bits(self._mono, n, body)
        if bits.size < self._capacity:
            bits = np.concatenate([bits, np.zeros(self._capacity - bits.size, dtype=np.uint8)])
        return bits

    def get_bits(self, n_lsb=1):
        if n_lsb != 1: raise NotImplementedError("MP3Carrier uses 1 bit per frame")
        return self._current.copy()

    def set_bits(self, bits, n_lsb=1):
        if n_lsb != 1: raise NotImplementedError("MP3Carrier uses 1 bit per frame")
        bits = np.asarray(bits, dtype=np.uint8)
        if bits.size > self._capacity:
            raise ValueError("need %d watermark bits but carrier holds %d" % (bits.size, self._capacity))
        # rebuild mono from original samples (so repeated set_bits doesn't accumulate)
        base = self.samples.astype(np.float32).mean(axis=0) / 32768.0
        full = np.concatenate([_sync_bits(), bits])
        new_mono = _embed_bits(base, full)
        delta = (new_mono - base) * 32768.0
        out = self.samples.astype(np.float32)
        out[0] = np.clip(out[0] + delta, -32768, 32767)
        out[1] = np.clip(out[1] + delta, -32768, 32767)
        self.samples = out.astype(np.int16)
        self._mono = new_mono
        self._current = bits.copy()

    def write(self, path):
        ext = os.path.splitext(path)[1].lower()
        fmt_key = _LOSSY_EXTS.get(ext, self.fmt_key)
        _encode(self.samples, self.sr, path, fmt_key)
