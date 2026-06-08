// Bit packing, mulberry32 PRNG, CRC-16 and CRC-32 — byte-identical to the Python `stego` package
// so a stego WAV produced by Python is decodable in the browser, and vice versa.

// `& 0xFFFFFFFF` is a TRAP in JS — bitwise ops are 32-bit *signed*, so `x & 0xFFFFFFFF`
// is signed-equivalent to `x` (e.g. `0xFFFFFFFF & 0xFFFFFFFF == -1`). Use `>>> 0` instead.
export const u32 = (x) => x >>> 0;

// mulberry32 — same algorithm as stego/bitio.py:mulberry32
export function mulberry32(seed) {
  let a = u32(seed);
  return function () {
    a = u32(a + 0x6D2B79F5);
    let t = u32(Math.imul(a ^ (a >>> 15), 1 | a));
    t = u32(u32(t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t);
    return u32(t ^ (t >>> 14)) / 4294967296;
  };
}

// Seeded Fisher–Yates — same algorithm as stego/bitio.py:perm
export function perm(n, seed) {
  const r = mulberry32(seed);
  const a = new Int32Array(n);
  for (let i = 0; i < n; i++) a[i] = i;
  for (let i = n - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1));
    const t = a[i]; a[i] = a[j]; a[j] = t;
  }
  return a;
}

// bits <-> bytes (MSB first within each byte; matches numpy unpackbits/packbits)
export function bytesToBits(data) {
  const u8 = data instanceof Uint8Array ? data : new Uint8Array(data);
  const out = new Uint8Array(u8.length * 8);
  for (let i = 0; i < u8.length; i++) {
    const b = u8[i];
    for (let k = 0; k < 8; k++) out[i * 8 + k] = (b >> (7 - k)) & 1;
  }
  return out;
}
export function bitsToBytes(bits) {
  const out = new Uint8Array(bits.length >> 3);
  for (let i = 0; i < out.length; i++) {
    let v = 0;
    for (let k = 0; k < 8; k++) v = (v << 1) | bits[i * 8 + k];
    out[i] = v;
  }
  return out;
}

// CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) — matches stego/bitio.py:crc16
export function crc16(data) {
  let c = 0xFFFF;
  for (let i = 0; i < data.length; i++) {
    c ^= data[i] << 8;
    for (let k = 0; k < 8; k++) c = (c & 0x8000) ? (((c << 1) ^ 0x1021) & 0xFFFF) : ((c << 1) & 0xFFFF);
  }
  return c;
}

// CRC-32 (IEEE, poly 0xEDB88320 reflected) — matches Python zlib.crc32
const _CRC32_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();
export function crc32(data) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < data.length; i++) c = _CRC32_TABLE[(c ^ data[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}
