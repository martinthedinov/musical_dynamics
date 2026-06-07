"""MIDI carrier — hide bits in the low bit(s) of note-on velocities.

A typical MIDI file has hundreds-to-thousands of note-on events; flipping the lowest bit of
each velocity is essentially inaudible (velocity is logarithmic-perceptual, a ±1 step at v=64
is a fraction of a dB and well below most synthesizer rendering precision). Capacity is one
bit per note (× n_lsb if you opt into higher bit-planes), so a busy MIDI song easily hides
a few kilobytes.

Avoided pitfalls:
  * note-on with velocity 0 means note-off in many MIDI implementations, so we never modify
    velocity=0 events — they're skipped entirely.
  * note-off events are left untouched (they aren't reliable carriers and editors may strip
    their velocity).
  * Event order is preserved exactly; bits are read/written in file/track/event order.
"""
import os
import numpy as np
from .base import Carrier


def _velocity_carriers(mid):
    """Return (track_index, msg_index) pairs in stable order for usable note_on messages.
       'Usable' = type=='note_on' and velocity > 0 (avoiding the note-off-via-vel-0 idiom)."""
    out = []
    for ti, track in enumerate(mid.tracks):
        for mi, msg in enumerate(track):
            if getattr(msg, "type", None) == "note_on" and msg.velocity > 0:
                out.append((ti, mi))
    return out


class MIDICarrier(Carrier):
    """A MIDI file. n_lsb chooses how many low bits of each velocity carry data.
       n_lsb=1 is essentially inaudible; 2 is still very subtle; >=3 starts being noticeable."""
    EXTS = frozenset({".mid", ".midi"})

    def __init__(self, path):
        try:
            import mido
        except ImportError as e:                       # pragma: no cover
            raise ImportError("MIDICarrier needs mido (pip install mido): %s" % e)
        self.mid = mido.MidiFile(path)
        self.path = path
        self._carriers = _velocity_carriers(self.mid)
        # avoid clamping by keeping velocity in [n_lsb_max+1 .. 127] — but we only modify low bits,
        # and a velocity of 1 is the smallest legal "audible" value, so any v>=1 has room for n_lsb=4

    def num_slots(self, n_lsb):
        # one bit per carrier note × n_lsb bit-planes; but if v<2^n_lsb-1, skip that note for safety
        cnt = 0
        for ti, mi in self._carriers:
            v = self.mid.tracks[ti][mi].velocity
            if v >= max(1, (1 << n_lsb) - 1):           # leave room so low-bits writes can't clobber
                cnt += n_lsb
        return cnt

    def _iter_safe(self, n_lsb):
        thresh = max(1, (1 << n_lsb) - 1)
        for ti, mi in self._carriers:
            v = self.mid.tracks[ti][mi].velocity
            if v >= thresh:
                yield ti, mi

    def get_bits(self, n_lsb=1):
        bits = []
        for ti, mi in self._iter_safe(n_lsb):
            v = self.mid.tracks[ti][mi].velocity
            for p in range(n_lsb):
                bits.append((v >> p) & 1)
        return np.asarray(bits, dtype=np.uint8)

    def set_bits(self, bits, n_lsb=1):
        bits = np.asarray(bits, dtype=np.uint8)
        if bits.size != self.num_slots(n_lsb):
            raise ValueError("expected %d bits for this MIDI at n_lsb=%d, got %d"
                             % (self.num_slots(n_lsb), n_lsb, bits.size))
        k = 0
        mask_keep = (~((1 << n_lsb) - 1)) & 0x7F
        for ti, mi in self._iter_safe(n_lsb):
            v = self.mid.tracks[ti][mi].velocity & 0x7F
            nv = v & mask_keep
            for p in range(n_lsb):
                if bits[k]: nv |= (1 << p)
                k += 1
            if nv == 0: nv = 1                          # never write velocity 0 (that's note-off)
            self.mid.tracks[ti][mi].velocity = nv

    def write(self, path):
        self.mid.save(path)
