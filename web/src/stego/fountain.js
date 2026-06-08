// LT fountain code — byte-compatible with Python stego/fountain.py.
// Robust Soliton degree distribution, mulberry32-seeded block selection per ordinal,
// belief-propagation peeling decoder. Decoder recovers all K blocks from any K'~K
// surviving symbols.

import { mulberry32, u32 } from "./bitio.js";

function robustSolitonCDF(K, c = 0.05, delta = 0.5) {
  if (K <= 1) return [0.0, 1.0];
  const rho = new Array(K + 1).fill(0.0);
  rho[1] = 1.0 / K;
  for (let d = 2; d <= K; d++) rho[d] = 1.0 / (d * (d - 1));
  const S = c * Math.log(K / delta) * Math.sqrt(K);
  const tau = new Array(K + 1).fill(0.0);
  const pivot = Math.max(1, Math.round(K / S));
  for (let d = 1; d <= K; d++) {
    if (d < pivot)       tau[d] = S / (K * d);
    else if (d === pivot) tau[d] = (S * Math.log(S / delta)) / K;
  }
  let Z = 0; for (let d = 1; d <= K; d++) Z += rho[d] + tau[d];
  const cdf = new Array(K + 1).fill(0.0);
  let acc = 0.0;
  for (let d = 1; d <= K; d++) { acc += (rho[d] + tau[d]) / Z; cdf[d] = acc; }
  cdf[K] = 1.0;
  return cdf;
}

export class Fountain {
  constructor(K, B, seed) {
    this.K = K | 0;
    this.B = B | 0;
    this.seed = u32(seed);
    this._cdf = robustSolitonCDF(this.K);
  }
  _rng(i) {
    // Same mixing as stego/fountain.py:Fountain._rng
    const s = u32(Math.imul(this.seed, 2654435761) ^ Math.imul(i + 1, 2246822519));
    return mulberry32(s);
  }
  indices(i) {
    if (this.K === 1) return [0];
    const r = this._rng(i);
    const u = r();
    let d = this.K;
    for (let dd = 1; dd <= this.K; dd++) if (u <= this._cdf[dd]) { d = dd; break; }
    const idxs = new Set();
    while (idxs.size < d) idxs.add(Math.floor(r() * this.K));
    return Array.from(idxs).sort((a, b) => a - b);
  }
  encodeSymbol(blocks, i) {
    // blocks: Uint8Array of length K*B (row-major). Returns a B-byte Uint8Array.
    const idxs = this.indices(i);
    const out = new Uint8Array(this.B);
    for (const k of idxs) {
      const off = k * this.B;
      for (let j = 0; j < this.B; j++) out[j] ^= blocks[off + j];
    }
    return out;
  }
}

// Belief-propagation peeling decoder for LT. `symbols` is a Map from ordinal -> Uint8Array(B).
// Returns Uint8Array(K*B) on success, or null if not enough symbols.
export function ltDecode(symbols, fnt) {
  const K = fnt.K, B = fnt.B;
  const eqs = [];                                  // [Set(unknown block idxs), Uint8Array(B)]
  const refs = Array.from({ length: K }, () => []);
  for (const [i, data] of symbols.entries()) {
    const idxs = new Set(fnt.indices(i));
    const e = eqs.length;
    eqs.push([idxs, new Uint8Array(data)]);
    for (const k of idxs) refs[k].push(e);
  }
  const known = new Array(K).fill(null);
  const ripple = [];
  for (let e = 0; e < eqs.length; e++) if (eqs[e][0].size === 1) ripple.push(e);
  let solved = 0;
  while (ripple.length && solved < K) {
    const e = ripple.pop();
    const [idxs, val] = eqs[e];
    if (idxs.size !== 1) continue;
    const k = idxs.values().next().value;
    idxs.clear();
    if (known[k] !== null) continue;
    known[k] = new Uint8Array(val);
    solved++;
    for (const o of refs[k]) {
      const [oidx, oval] = eqs[o];
      if (oidx.has(k)) {
        for (let j = 0; j < B; j++) oval[j] ^= known[k][j];
        oidx.delete(k);
        if (oidx.size === 1) ripple.push(o);
      }
    }
  }
  if (solved < K) return null;
  const out = new Uint8Array(K * B);
  for (let k = 0; k < K; k++) out.set(known[k], k * B);
  return out;
}

// Split data into K blocks of B bytes, zero-padded to K*B.
export function blocksOf(data, B) {
  const K = Math.max(1, Math.ceil(data.length / B));
  const buf = new Uint8Array(K * B);
  buf.set(data, 0);
  return { blocks: buf, K };
}
