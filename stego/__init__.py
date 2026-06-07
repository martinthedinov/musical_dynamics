"""
stego — hide arbitrary files inside music, with fountain-coded redundancy.

A format-independent payload pipeline (frame -> zlib -> AES-GCM -> fountain FEC ->
interleave) feeds pluggable *carriers* (lossless PCM today; MP3 watermark, MIDI and
the MD-native compositional channel to follow). The decoder bootstraps blind from a
fixed, repetition-coded header and *fails safe* (verify-and-refuse, never silent-wrong).

Public API:
    embed_file(in_music, out_music, payload_path, password=None, redundancy=None, n_lsb=1)
    extract_file(in_music, out_dir=".", password=None)
    capacity(in_music, n_lsb=1)
"""
from .pipeline import embed, extract, pack, unpack, PipelineError
from .carriers import open_carrier, embed_file, extract_file, capacity

__all__ = ["embed", "extract", "pack", "unpack", "PipelineError",
           "open_carrier", "embed_file", "extract_file", "capacity"]
