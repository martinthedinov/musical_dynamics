"""Bit packing, a JS-compatible PRNG, deterministic interleaving, and CRC-16.

The PRNG is a byte-for-byte port of the browser's mulberry32 (`smb`) and Fisher-Yates
(`sperm`), so a payload embedded by Python in a WAV is decodable by the JS app and vice
versa. Everything operates on uint32 bit-patterns to match JS's 32-bit integer semantics.
"""
import numpy as np

_MASK = 0xFFFFFFFF

def _u32(x): return x & _MASK

def mulberry32(seed):
    """Port of JS  function smb(a){...}  — returns a float-in-[0,1) generator."""
    a = _u32(seed)
    def rnd():
        nonlocal a
        a = _u32(a + 0x6D2B79F5)
        t = _u32(_u32(a ^ (a >> 15)) * _u32(1 | a))
        t = _u32(_u32(t + _u32(_u32(t ^ (t >> 7)) * _u32(61 | t))) ^ t)
        return _u32(t ^ (t >> 14)) / 4294967296.0
    return rnd

def perm(n, seed):
    """Port of JS sperm(n,seed): seeded Fisher-Yates permutation of [0..n)."""
    r = mulberry32(seed)
    a = list(range(n))
    for i in range(n - 1, 0, -1):
        j = int(r() * (i + 1))
        a[i], a[j] = a[j], a[i]
    return np.asarray(a, dtype=np.int64)

# ---- bits <-> bytes (MSB first within each byte; matches JS sbits/sunbits) ----
def bytes_to_bits(data):
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))

def bits_to_bytes(bits):
    return np.packbits(np.asarray(bits, dtype=np.uint8)).tobytes()

# ---- CRC-16/CCITT-FALSE (per-symbol integrity; cheap, turns corruption into erasure) ----
def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc
