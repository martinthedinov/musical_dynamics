// Format-independent payload pipeline, JS port of stego/pipeline.py.
// Uses rs_nsym=0 mode (no inner Reed-Solomon) so we don't need to port the RS library;
// inner integrity is CRC-16/CCITT and fountain handles outer redundancy. Lossless audio is
// bit-exact anyway, so RS isn't needed for the lossless cross-compat path.

import { bytesToBits, bitsToBytes, crc16, crc32 } from "./bitio.js";
import { Fountain, ltDecode, blocksOf } from "./fountain.js";
import { deflate, inflate } from "./zlib.js";

export class PipelineError extends Error { constructor(m) { super(m); this.name = "PipelineError"; } }

const MAGIC      = new TextEncoder().encode("MDX1");
const VERSION    = 1;
const R_HEADER   = 11;
export const HEADER_BYTES   = 30;    // matches Python _HDR_FMT
export const DEFAULT_BLOCK  = 64;
export const FLAG_ZLIB = 1;

// ---------- byte-level helpers ----------
function dvWrite(buf, off, fmt, ...vals) {
  const v = new DataView(buf.buffer, buf.byteOffset + off);
  let p = 0;
  for (let i = 0; i < fmt.length; i++) {
    const c = fmt[i];
    if      (c === "B") { v.setUint8(p, vals[i]);             p += 1; }
    else if (c === "H") { v.setUint16(p, vals[i], false);     p += 2; }
    else if (c === "I") { v.setUint32(p, vals[i] >>> 0, false); p += 4; }
    else if (c === "s") { buf.set(vals[i], off + p);          p += vals[i].length; }
    else throw new Error("bad fmt " + c);
  }
}
function dvRead(buf, off, fmt) {
  const v = new DataView(buf.buffer, buf.byteOffset + off);
  const out = []; let p = 0;
  for (const c of fmt) {
    if      (c === "B") { out.push(v.getUint8(p)); p += 1; }
    else if (c === "H") { out.push(v.getUint16(p, false)); p += 2; }
    else if (c === "I") { out.push(v.getUint32(p, false) >>> 0); p += 4; }
    else throw new Error("bad fmt " + c);
  }
  return out;
}
function concatU8(...arrs) {
  let n = 0; for (const a of arrs) n += a.length;
  const out = new Uint8Array(n); let p = 0;
  for (const a of arrs) { out.set(a, p); p += a.length; }
  return out;
}

// ---------- frame (filename + integrity) ----------
function frame(payload, filename) {
  const name = new TextEncoder().encode(filename || "payload.bin").slice(0, 65535);
  const head = new Uint8Array(2 + 4 + 4);
  const v = new DataView(head.buffer);
  v.setUint16(0, name.length, false);
  v.setUint32(2, payload.length, false);
  v.setUint32(6, crc32(payload), false);
  return concatU8(head, name, payload);
}
function unframe(buf) {
  if (buf.length < 10) throw new PipelineError("frame too short");
  const v = new DataView(buf.buffer, buf.byteOffset);
  const nameLen = v.getUint16(0, false);
  const dataLen = v.getUint32(2, false);
  const crc     = v.getUint32(6, false) >>> 0;
  const name = new TextDecoder().decode(buf.slice(10, 10 + nameLen));
  const data = buf.slice(10 + nameLen, 10 + nameLen + dataLen);
  if (data.length !== dataLen) throw new PipelineError("payload truncated");
  if (crc32(data) !== crc) throw new PipelineError("payload CRC-32 mismatch (corrupted beyond recovery)");
  return { name, data };
}

// ---------- pack / unpack (compression layer; no AES in browser yet) ----------
export function pack(payload, filename = "payload.bin") {
  const fr = frame(payload, filename);
  let flags = 0;
  let coded = fr;
  const comp = deflate(fr);
  if (comp.length < fr.length) { coded = comp; flags |= FLAG_ZLIB; }
  return { coded, flags };
}
export function unpack(coded, flags) {
  let buf = coded;
  if (flags & FLAG_ZLIB) {
    try { buf = inflate(coded); }
    catch (e) { throw new PipelineError("decompression failed (payload corrupted): " + e.message); }
  }
  return unframe(buf);
}

// ---------- header (30 bytes; same layout as Python _HDR_FMT) ----------
//   magic(4) ver(1) flags(1) block_size(2) K(4) seed(4) coded_len(4) n_sym(4) n_lsb(1) rs_nsym(1) crc(4)
function makeHeader(flags, blockSize, K, seed, codedLen, nSym, nLsb, rsNsym) {
  const h = new Uint8Array(HEADER_BYTES);
  dvWrite(h, 0, "sBBHIIIIBB", MAGIC, VERSION, flags, blockSize, K, seed, codedLen, nSym, nLsb, rsNsym);
  const c = crc32(h.slice(0, HEADER_BYTES - 4));
  new DataView(h.buffer).setUint32(HEADER_BYTES - 4, c, false);
  return h;
}
function readHeaderBytes(h) {
  for (let i = 0; i < 4; i++) if (h[i] !== MAGIC[i]) return null;
  const [, ver, flags, blockSize, K, seed, codedLen, nSym, nLsb, rsNsym, crc] =
        dvRead(h, 0, "IBBHIIIIBBI");
  void [ver];                                              // version read but unused
  if (crc32(h.slice(0, HEADER_BYTES - 4)) !== crc) return null;
  return { version: ver, flags, blockSize, K, seed, codedLen, nSym, nLsb, rsNsym };
}

function stepBytes(blockSize, rsNsym) {
  return rsNsym > 0 ? (blockSize + 2 + rsNsym) : (2 + blockSize);
}

// Same layout function as stego/pipeline.py:_layout
function layout(cap) {
  const nbits = HEADER_BYTES * 8;
  const headerTotal = R_HEADER * nbits;
  if (cap < headerTotal + 1) return null;
  const stride = Math.floor(cap / headerTotal);
  const hpos = new Int32Array(headerTotal);
  for (let i = 0; i < headerTotal; i++) hpos[i] = i * stride;
  const mask = new Uint8Array(cap).fill(1);
  for (let i = 0; i < headerTotal; i++) mask[hpos[i]] = 0;
  const body = []; for (let i = 0; i < cap; i++) if (mask[i]) body.push(i);
  return { hpos, body: new Int32Array(body) };
}

const cell = (i, nFit, nSym) => Math.floor((i * nFit) / nSym);

// ---------- the four functions a carrier needs ----------
export function embedSlots(slotBits, payload, filename, { blockSize = DEFAULT_BLOCK, nLsb = 1, redundancy = null } = {}) {
  const { coded, flags } = pack(payload, filename);
  const seed = crc32(coded);
  const { blocks, K } = blocksOf(coded, blockSize);
  const fnt = new Fountain(K, blockSize, seed);
  const rsNsym = 0;                                        // browser uses no inner RS
  const cap = slotBits.length;
  const lay = layout(cap);
  if (lay === null) throw new PipelineError("carrier far too small");
  const { hpos, body } = lay;
  const step = stepBytes(blockSize, rsNsym), symSlots = step * 8;
  const nFit = Math.floor(body.length / symSlots);
  if (nFit < K) throw new PipelineError(`carrier too small: fits ${nFit} symbols but payload needs >= ${K}`);
  const nSym = redundancy == null ? nFit : Math.min(nFit, Math.max(K, Math.ceil(K * redundancy)));
  const out = new Uint8Array(slotBits);
  const header = makeHeader(flags, blockSize, K, seed, coded.length, nSym, nLsb, rsNsym);
  const hbits = bytesToBits(header);
  for (let c = 0; c < R_HEADER; c++)
    for (let b = 0; b < hbits.length; b++) out[hpos[c * hbits.length + b]] = hbits[b];
  for (let i = 0; i < nSym; i++) {
    const sym = fnt.encodeSymbol(blocks, i);
    const wire = new Uint8Array(2 + sym.length);
    new DataView(wire.buffer).setUint16(0, crc16(sym), false);
    wire.set(sym, 2);
    const wbits = bytesToBits(wire);
    const c = cell(i, nFit, nSym);
    for (let b = 0; b < wbits.length; b++) out[body[c * symSlots + b]] = wbits[b];
  }
  return {
    bits: out,
    info: {
      K, blockSize, rsNsym, nSymbols: nSym, redundancy: Math.round(100 * nSym / K) / 100,
      codedLen: coded.length, flags, capacitySlots: cap, nLsb,
      tolerates_symbol_loss: `${Math.round(100 * (1 - K / nSym))}%`
    }
  };
}

export function readHeader(slotBits) {
  const lay = layout(slotBits.length);
  if (lay === null) return null;
  const { hpos } = lay;
  const nbits = HEADER_BYTES * 8;
  const votes = new Int32Array(nbits);
  for (let c = 0; c < R_HEADER; c++)
    for (let b = 0; b < nbits; b++) votes[b] += slotBits[hpos[c * nbits + b]];
  const maj = new Uint8Array(nbits);
  for (let b = 0; b < nbits; b++) maj[b] = (votes[b] * 2 > R_HEADER) ? 1 : 0;
  const tryParse = (bits) => readHeaderBytes(bitsToBytes(bits));
  let hdr = tryParse(maj);
  if (hdr) return hdr;
  for (let c = 0; c < R_HEADER; c++) {                     // fallback: any single intact copy
    const copy = new Uint8Array(nbits);
    for (let b = 0; b < nbits; b++) copy[b] = slotBits[hpos[c * nbits + b]];
    hdr = tryParse(copy);
    if (hdr) return hdr;
  }
  return null;
}

export function extractSlots(slotBits, hdr) {
  const lay = layout(slotBits.length);
  const { body } = lay;
  const { blockSize: B, K, seed, codedLen, nSym, rsNsym } = hdr;
  if (rsNsym > 0) throw new PipelineError("rs_nsym>0 (Python-only path) — install reedsolo-js to extract");
  const step = stepBytes(B, rsNsym), symSlots = step * 8;
  const nFit = Math.floor(body.length / symSlots);
  const fnt = new Fountain(K, B, seed);
  const symbols = new Map();
  for (let i = 0; i < nSym; i++) {
    const c = cell(i, nFit, nSym);
    const sBits = new Uint8Array(symSlots);
    for (let b = 0; b < symSlots; b++) sBits[b] = slotBits[body[c * symSlots + b]];
    const wire = bitsToBytes(sBits);
    if (wire.length < step) continue;
    const crc = new DataView(wire.buffer, wire.byteOffset).getUint16(0, false);
    const data = wire.slice(2);
    if (crc16(data) === crc) symbols.set(i, data);
  }
  const codedPadded = ltDecode(symbols, fnt);
  if (codedPadded === null)
    throw new PipelineError(`too many symbols lost — payload unrecoverable (${symbols.size}/${nSym} usable)`);
  return codedPadded.slice(0, codedLen);
}

// ---------- public file API (carrier-agnostic) ----------
export function embed(carrier, payload, filename = "payload.bin", opts = {}) {
  const bits = carrier.getBits(opts.nLsb || 1);
  const { bits: newBits, info } = embedSlots(bits, payload, filename, opts);
  carrier.setBits(newBits, opts.nLsb || 1);
  return info;
}
export function extract(carrier, nLsbCandidates = [1, 2, 3, 4]) {
  for (const nLsb of nLsbCandidates) {
    let bits;
    try { bits = carrier.getBits(nLsb); } catch (e) { continue; }
    const hdr = readHeader(bits);
    if (hdr === null || hdr.nLsb !== nLsb) continue;
    const coded = extractSlots(bits, hdr);
    const { name, data } = unpack(coded, hdr.flags);
    return { name, data, hdr };
  }
  throw new PipelineError("no MDX1 header found (not a stego carrier, or too corrupted to read)");
}
