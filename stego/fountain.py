"""LT fountain code — the redundancy engine.

Split data into K fixed-size blocks; emit as many coded symbols as the carrier holds.
Each symbol is the XOR of a pseudo-random set of blocks (degree drawn from the Robust
Soliton distribution), with the block set reproducible from the symbol's ordinal + a seed.

The decoder recovers all K blocks from *any* K' >~ K surviving symbols (it doesn't matter
which are lost), via belief-propagation peeling. Per-symbol CRC upstream turns corruption
into erasure, and interleaving turns bursts into scattered erasures — exactly what this eats.
This is what makes the hidden file survive truncation, overwrite, and partial damage.
"""
import math
import numpy as np
from .bitio import mulberry32, _u32

def _robust_soliton_cdf(K, c=0.05, delta=0.5):
    """Cumulative degree distribution for K blocks (Luby's Robust Soliton)."""
    if K <= 1:
        return [0.0, 1.0]
    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))
    S = c * math.log(K / delta) * math.sqrt(K)
    tau = [0.0] * (K + 1)
    pivot = max(1, int(round(K / S)))
    for d in range(1, K + 1):
        if d < pivot:    tau[d] = S / (K * d)
        elif d == pivot: tau[d] = S * math.log(S / delta) / K
    Z = sum(rho[d] + tau[d] for d in range(1, K + 1))
    cdf, acc = [0.0] * (K + 1), 0.0
    for d in range(1, K + 1):
        acc += (rho[d] + tau[d]) / Z
        cdf[d] = acc
    cdf[K] = 1.0
    return cdf

class Fountain:
    """Deterministic LT code over K blocks of `block_size` bytes, parameterized by `seed`."""
    def __init__(self, K, block_size, seed):
        self.K, self.B, self.seed = int(K), int(block_size), _u32(seed)
        self._cdf = _robust_soliton_cdf(self.K)

    def _rng(self, i):
        # unique, reproducible stream per symbol ordinal i. Coerce to Python int so numpy
        # callers don't silently overflow np.int64 before reaching _u32.
        i = int(i)
        return mulberry32(_u32(_u32(self.seed * 2654435761) ^ _u32((i + 1) * 2246822519)))

    def indices(self, i):
        """Block indices XORed into symbol i (reproducible on both sides)."""
        if self.K == 1:
            return [0]
        r = self._rng(i)
        u = r()
        d = self.K
        for dd in range(1, self.K + 1):
            if u <= self._cdf[dd]:
                d = dd; break
        idxs = set()
        while len(idxs) < d:
            idxs.add(int(r() * self.K))
        return sorted(idxs)

    def encode_symbol(self, blocks, i):
        """blocks: (K, B) uint8 array -> the B-byte coded symbol for ordinal i."""
        idxs = self.indices(i)
        return np.bitwise_xor.reduce(blocks[idxs], axis=0) if len(idxs) > 1 else blocks[idxs[0]].copy()

def blocks_of(data, block_size):
    """Pad `data` to a whole number of blocks; return (blocks (K,B) uint8, K)."""
    B = block_size
    K = max(1, (len(data) + B - 1) // B)
    buf = np.zeros(K * B, dtype=np.uint8)
    buf[:len(data)] = np.frombuffer(data, dtype=np.uint8)
    return buf.reshape(K, B), K

def decode(symbols, fnt):
    """symbols: dict {ordinal -> B-byte payload (bytes/np)} that passed CRC.
       Returns K*B bytes, or None if not yet decodable."""
    K, B = fnt.K, fnt.B
    eqs = []                                  # [set(unknown block idxs), value (B,) uint8]
    refs = [[] for _ in range(K)]             # block -> equations referencing it
    for i, data in symbols.items():
        val = np.frombuffer(data, dtype=np.uint8).copy() if isinstance(data, (bytes, bytearray)) else np.asarray(data, np.uint8).copy()
        idxs = set(fnt.indices(i))
        e = len(eqs); eqs.append([idxs, val])
        for k in idxs: refs[k].append(e)
    known = [None] * K
    ripple = [e for e, (idxs, _) in enumerate(eqs) if len(idxs) == 1]
    solved = 0
    while ripple and solved < K:
        e = ripple.pop()
        idxs, val = eqs[e]
        if len(idxs) != 1: continue
        k = next(iter(idxs)); idxs.clear()
        if known[k] is not None: continue
        known[k] = val.copy(); solved += 1
        for o in refs[k]:
            oidx, oval = eqs[o]
            if k in oidx:
                oval ^= known[k]; oidx.discard(k)
                if len(oidx) == 1: ripple.append(o)
    if solved < K:
        return None
    return b"".join(known[k].tobytes() for k in range(K))
