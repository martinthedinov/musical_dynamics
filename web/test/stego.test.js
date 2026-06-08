// Node-based tests for the JS stego port. Two purposes:
//   1) round-trip sanity (JS embed -> JS extract bit-exact)
//   2) CROSS-COMPAT: the file Python writes can be read by JS, and vice versa.
// Run with: npm test  (or: node --test test/)
import { test } from "node:test";
import assert from "node:assert/strict";
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { WavCarrier } from "../src/stego/wav.js";
import { embed, extract, PipelineError } from "../src/stego/pipeline.js";
import { mulberry32, perm, crc16, crc32 } from "../src/stego/bitio.js";

// ---------- helpers ----------
const REPO = new URL("../..", import.meta.url).pathname;
function synthWav(seconds = 8.0, sr = 44100) {
  const T = Math.floor(seconds * sr);
  const data = new Int16Array(T * 2);
  for (let i = 0; i < T; i++) {
    const t = i / sr;
    let s = 0.4 * Math.sin(2 * Math.PI * 220 * t) + 0.3 * Math.sin(2 * Math.PI * 440 * t);
    s = Math.max(-1, Math.min(1, s));
    const v = (s * 30000) | 0;
    data[i * 2] = v; data[i * 2 + 1] = v;
  }
  const fmt = { audioFormat: 1, channels: 2, sampleRate: sr, bitsPerSample: 16 };
  const buf = new ArrayBuffer(44 + data.length * 2);
  const dv = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); dv.setUint32(4, 36 + data.length * 2, true);
  w(8, "WAVE"); w(12, "fmt ");
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
  dv.setUint16(22, 2, true);  dv.setUint32(24, sr, true);
  dv.setUint32(28, sr * 4, true); dv.setUint16(32, 4, true);
  dv.setUint16(34, 16, true);
  w(36, "data"); dv.setUint32(40, data.length * 2, true);
  new Int16Array(buf, 44, data.length).set(data);
  return buf;
}

// ---------- 1. byte-level parity with Python ----------
test("mulberry32 matches the JS-reference vector (= the Python port's vector)", () => {
  const r = mulberry32(0x6d6432);
  const got = []; for (let i = 0; i < 6; i++) got.push(+r().toFixed(12));
  assert.deepEqual(got, [0.842230277602, 0.637956989231, 0.120746918255,
                          0.292125375941, 0.948608695064, 0.54758424079]);
});

test("perm is a permutation and deterministic", () => {
  const p = perm(64, 0xCAFE);
  const set = new Set(Array.from(p)); assert.equal(set.size, 64);
});

test("crc32 matches Python zlib on a few vectors", () => {
  const t = new TextEncoder();
  assert.equal(crc32(t.encode("hello")), 0x3610a686);
  assert.equal(crc32(t.encode("musiclang")), 0x93312f6e);
  assert.equal(crc32(new Uint8Array([0])), 0xd202ef8d);
});

test("crc16 matches Python's CCITT-FALSE on a few vectors", () => {
  const t = new TextEncoder();
  assert.equal(crc16(t.encode("hello")), 0xD26E);
  assert.equal(crc16(new Uint8Array([0, 0, 0, 0])), 0x84C0);
});

// ---------- 2. JS embed -> JS extract round-trip ----------
test("WAV: JS embed -> JS extract bit-exact for arbitrary payload", () => {
  const buf = synthWav(15);
  const carrier = new WavCarrier(buf);
  const payload = new TextEncoder().encode(
    "We the People, in Order to form a more perfect Union..."
  );
  embed(carrier, payload, "preamble.txt", { redundancy: 4 });
  const stegoBuf = carrier.toArrayBuffer();
  const carrier2 = new WavCarrier(stegoBuf);
  const { name, data } = extract(carrier2);
  assert.equal(name, "preamble.txt");
  assert.deepEqual(Array.from(data), Array.from(payload));
});

test("WAV: imperceptibility — max sample delta is 1 at n_lsb=1", () => {
  const buf = synthWav(8);
  const before = new WavCarrier(buf).samples.slice();
  const carrier = new WavCarrier(buf);
  const payload = new TextEncoder().encode("hello".repeat(50));
  embed(carrier, payload, "hi.txt");
  let maxDelta = 0;
  for (let i = 0; i < before.length; i++) {
    const d = Math.abs(before[i] - carrier.samples[i]);
    if (d > maxDelta) maxDelta = d;
  }
  assert.equal(maxDelta <= 1, true, `max sample delta was ${maxDelta}, want <= 1`);
});

test("PipelineError when carrier is too small", () => {
  const buf = synthWav(0.05);                       // very small carrier
  const carrier = new WavCarrier(buf);
  // use incompressible random bytes so zlib can't sneak it under the line
  const payload = new Uint8Array(500);
  for (let i = 0; i < payload.length; i++) payload[i] = (Math.random() * 256) | 0;
  assert.throws(() => embed(carrier, payload, "x.bin"),
                e => e instanceof PipelineError);
});

// ---------- 3. CROSS-COMPAT: Python -> JS, JS -> Python ----------
function runPython(script) {
  // write the script to a temp file so newlines/quotes don't get mangled by the shell
  const td = mkdtempSync(join(tmpdir(), "py-"));
  const f = join(td, "s.py");
  writeFileSync(f, script);
  try {
    return execSync(`python3 ${f}`, {
      stdio: ["ignore", "pipe", "pipe"], encoding: "utf8",
      env: { ...process.env, PYTHONPATH: REPO }
    }).trim();
  } catch (e) {
    if (process.env.STEGO_TEST_DEBUG) console.error("python error:", e.stderr || e.message);
    return null;
  }
}
function pythonAvailable() {
  try {
    execSync(`python3 -c "import stego"`,
             { stdio: "ignore", env: { ...process.env, PYTHONPATH: REPO } });
    return true;
  } catch { return false; }
}

test("CROSS-COMPAT (Python embed -> JS extract)", { skip: !pythonAvailable() }, () => {
  const td = mkdtempSync(join(tmpdir(), "xstego-"));
  const wav = join(td, "carrier.wav");
  const payload = join(td, "payload.txt");
  const stego = join(td, "stego.wav");
  const py = `import soundfile as sf, numpy as np, sys
sr=44100; t=np.linspace(0,15,15*sr,endpoint=False)
s=0.4*np.sin(2*np.pi*220*t)+0.3*np.sin(2*np.pi*440*t); s=np.clip(s,-1,1)
data=(np.stack([s,s],1)*30000).astype(np.int16)
sf.write(${JSON.stringify(wav)}, data, sr, subtype="PCM_16", format="WAV")
with open(${JSON.stringify(payload)}, "wb") as f: f.write(b"Hello from Python, decoded in JS!")
sys.path.insert(0, ${JSON.stringify(REPO)})
from stego.carriers import embed_file
info = embed_file(${JSON.stringify(wav)}, ${JSON.stringify(stego)}, ${JSON.stringify(payload)},
                  rs_nsym=0, redundancy=4.0)
print("ok", info["payload_bytes"])
`;
  const out = runPython(py);
  assert.ok(out && out.startsWith("ok"), "Python failed to embed: " + out);
  const carrier = new WavCarrier(readFileSync(stego).buffer);
  const { name, data } = extract(carrier);
  assert.equal(new TextDecoder().decode(data), "Hello from Python, decoded in JS!");
  assert.equal(name, "payload.txt");
});

test("CROSS-COMPAT (JS embed -> Python extract)", { skip: !pythonAvailable() }, () => {
  const td = mkdtempSync(join(tmpdir(), "xstego-"));
  const buf = synthWav(15);
  const carrier = new WavCarrier(buf);
  const payload = new TextEncoder().encode("Hello from JS, decoded in Python!");
  embed(carrier, payload, "msg.txt", { redundancy: 4 });
  const out = join(td, "stego.wav");
  writeFileSync(out, Buffer.from(carrier.toArrayBuffer()));
  const py = `import sys
sys.path.insert(0, ${JSON.stringify(REPO)})
from stego.carriers import extract_file
p, hdr = extract_file(${JSON.stringify(out)}, ${JSON.stringify(td)})
print(open(p).read(), end="")
`;
  const got = runPython(py);
  assert.equal(got, "Hello from JS, decoded in Python!");
});
