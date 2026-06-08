// 16-bit PCM WAV carrier (mono/stereo). Bit-exact lossless; LSB matching keeps audio sounding
// identical (max sample change is ±1, ≈ −96 dBFS).

export function parseWav(arrayBuffer) {
  const v = new DataView(arrayBuffer);
  if (v.getUint32(0, false) !== 0x52494646 /* 'RIFF' */) throw new Error("not a WAV (no RIFF header)");
  if (v.getUint32(8, false) !== 0x57415645 /* 'WAVE' */) throw new Error("not a WAV (no WAVE chunk)");
  let off = 12, fmt = null, dataOff = 0, dataLen = 0;
  while (off + 8 <= arrayBuffer.byteLength) {
    const id = v.getUint32(off, false), sz = v.getUint32(off + 4, true);
    if (id === 0x666d7420 /* 'fmt ' */) {
      fmt = {
        audioFormat:   v.getUint16(off + 8, true),
        channels:      v.getUint16(off + 10, true),
        sampleRate:    v.getUint32(off + 12, true),
        bitsPerSample: v.getUint16(off + 22, true),
      };
    } else if (id === 0x64617461 /* 'data' */) {
      dataOff = off + 8; dataLen = sz; break;
    }
    off += 8 + sz + (sz & 1);
  }
  if (!fmt) throw new Error("WAV missing fmt chunk");
  if (fmt.bitsPerSample !== 16) throw new Error("WAV must be 16-bit PCM (got " + fmt.bitsPerSample + ")");
  const total = (dataLen / 2) | 0;
  const samples = new Int16Array(arrayBuffer, dataOff, total);
  return { samples: new Int16Array(samples), fmt, dataOff, dataLen };
}

export function writeWav(samples, fmt) {
  const channels = fmt.channels, sr = fmt.sampleRate;
  const dataLen = samples.length * 2;
  const buf = new ArrayBuffer(44 + dataLen);
  const v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + dataLen, true);
  w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);             // PCM
  v.setUint16(22, channels, true);
  v.setUint32(24, sr, true);
  v.setUint32(28, sr * channels * 2, true);
  v.setUint16(32, channels * 2, true);
  v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, dataLen, true);
  const out = new Int16Array(buf, 44, samples.length);
  out.set(samples);
  return buf;
}

export class WavCarrier {
  constructor(arrayBuffer) {
    const { samples, fmt } = parseWav(arrayBuffer);
    this.samples = samples;                       // Int16Array, interleaved (matches Python sf.read flat)
    this.fmt = fmt;
  }
  getBits(nLsb = 1) {
    const N = this.samples.length;
    const bits = new Uint8Array(N * nLsb);
    for (let i = 0; i < N; i++) {
      const v = this.samples[i] & 0xFFFF;
      for (let p = 0; p < nLsb; p++) bits[i * nLsb + p] = (v >> p) & 1;
    }
    return bits;
  }
  setBits(bits, nLsb = 1) {
    const N = this.samples.length;
    if (nLsb === 1) {
      // LSB matching: flip a sample by ±1 (away from clipping) when its LSB doesn't match the target
      for (let i = 0; i < N; i++) {
        const s = this.samples[i];
        const cur = s & 1, tgt = bits[i] & 1;
        if (cur !== tgt) {
          const step = (s >= 32767) ? -1 : 1;
          this.samples[i] = (s + step);
        }
      }
    } else {
      const mask = ((1 << nLsb) - 1) ^ 0xFFFF;
      for (let i = 0; i < N; i++) {
        let v = this.samples[i] & 0xFFFF;
        v = (v & mask) >>> 0;
        for (let p = 0; p < nLsb; p++) if (bits[i * nLsb + p]) v |= (1 << p);
        // sign-extend back to int16
        this.samples[i] = v & 0x8000 ? v - 0x10000 : v;
      }
    }
  }
  toArrayBuffer() {
    return writeWav(this.samples, this.fmt);
  }
}
