"""Carrier registry, format dispatch, and the file-level public API."""
import os
from .. import pipeline
from .pcm import PCMCarrier

_CARRIERS = [PCMCarrier]
try:
    from .mp3 import MP3Carrier
    _CARRIERS.append(MP3Carrier)
except Exception:
    MP3Carrier = None                 # PyAV not installed -> MP3/AAC/Ogg disabled
try:
    from .midi import MIDICarrier
    _CARRIERS.append(MIDICarrier)
except Exception:
    MIDICarrier = None                # mido not installed -> MIDI disabled
_PLANNED = {}

def open_carrier(path):
    ext = os.path.splitext(path)[1].lower()
    for C in _CARRIERS:
        if ext in C.EXTS:
            return C(path)
    if ext in _PLANNED:
        raise NotImplementedError("%s carrier (%s) is planned but not implemented yet; "
                                  "use a lossless format (WAV/FLAC/AIFF) for now" % (ext, _PLANNED[ext]))
    raise ValueError("unsupported carrier format: %r" % ext)

# ---------- public file API ----------
def embed_file(in_music, out_music, payload_path, password=None, redundancy=None, n_lsb=1,
               block_size=pipeline.DEFAULT_BLOCK, rs_nsym=pipeline.DEFAULT_RS):
    """Hide the file at payload_path inside in_music, writing the stego carrier to out_music."""
    carrier = open_carrier(in_music)
    with open(payload_path, "rb") as f:
        payload = f.read()
    info = pipeline.embed(carrier, payload, os.path.basename(payload_path), password=password,
                          block_size=block_size, n_lsb=n_lsb, redundancy=redundancy, rs_nsym=rs_nsym)
    carrier.write(out_music)
    info["payload_bytes"] = len(payload)
    return info

def extract_file(in_music, out_dir=".", password=None):
    """Recover a hidden file from in_music into out_dir. Returns (output_path, header_info)."""
    carrier = open_carrier(in_music)
    name, data, hdr = pipeline.extract(carrier, password=password)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, os.path.basename(name) or "payload.bin")
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path, hdr

def capacity(in_music, n_lsb=1, block_size=pipeline.DEFAULT_BLOCK, rs_nsym=pipeline.DEFAULT_RS):
    """Report how much can be hidden in in_music at the given depth."""
    carrier = open_carrier(in_music)
    cap = len(carrier.get_bits(n_lsb))
    lay = pipeline._layout(cap)
    body = 0 if lay is None else len(lay[1])
    symbol_slots = pipeline._step_bytes(block_size, rs_nsym) * 8
    n_fit = max(0, body // symbol_slots)
    return dict(slots=cap, max_symbols=n_fit, approx_payload_bytes_at_1x=n_fit * block_size, n_lsb=n_lsb)
