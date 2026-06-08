// Musical Dynamics web · v7 entry point.
//   Loads the codec, audio synth, MIDI/MusicXML exporters, and the new file-in-WAV stego UI.
import { compilePython } from "./codec/python.js";
import { run } from "./codec/vm.js";
import { realize, decodeNotes } from "./codec/realizer.js";
import { CHORDNAME, QFAMILY } from "./codec/opcodes.js";
import { notesToMidi, downloadMidi } from "./audio/midi.js";
import { downloadMusicXML } from "./audio/musicxml.js";
import { synthToWav, playNotes, stopAudio } from "./audio/synth.js";
import { WavCarrier } from "./stego/wav.js";
import { embed, extract, PipelineError } from "./stego/pipeline.js";

// ---------- the player ----------
const DEMOS = {
  fibonacci: "a = 0\nb = 1\nfor i in range(10):\n    print(a)\n    c = a + b\n    a = b\n    b = c",
  hello:     'print("Hello, World!")\nprint("Musical " + "Dynamics")',
  fizzwords: 'for i in range(1, 16):\n    if i % 15 == 0:\n        print("FizzBuzz")\n    elif i % 3 == 0:\n        print("Fizz")\n    elif i % 5 == 0:\n        print("Buzz")\n    else:\n        print(i)',
  primes:    "for n in range(2, 30):\n    d = 2\n    p = 1\n    while d * d <= n:\n        if n % d == 0:\n            p = 0\n        d = d + 1\n    if p == 1:\n        print(n)",
};
const $ = (id) => document.getElementById(id);
let lastNotes = [];

function params() {
  return {
    mode:     $("mode").value,
    key:      +$("key").value,
    octave:   +$("octave").value,
    climb:    1,
    tempo:    120 / +$("tempo").value,
    feel:     "straight",
    melody:   "ladder",
    variation: Math.max(0, +$("variation").value | 0),
  };
}

function decompileLight(code) {
  // a minimal decompiler (we keep the v6 page for full decode/round-trip)
  const lines = []; const S = []; let indent = 0;
  const put = (t) => lines.push("    ".repeat(indent) + t);
  const BIN = { ADD:"+", SUB:"-", MUL:"*", MOD:"%", DIV:"//" };
  const CMP = { LT:"<", GT:">", LE:"<=", GE:">=", EQ:"==", NE:"!=" };
  const strip = (e) => (e.startsWith("(") && e.endsWith(")")) ? e.slice(1, -1) : e;
  for (const [op, arg] of code) {
    if (op === "PUSH") S.push(String(arg));
    else if (op === "LOAD") S.push("v" + arg);
    else if (op === "MKSTR") {
      const parts = []; for (let k = 0; k < arg; k++) parts.unshift(S.pop());
      try { S.push(JSON.stringify(parts.map(x => String.fromCodePoint(parseInt(x, 10))).join(""))); }
      catch { S.push("str(" + parts.join("+") + ")"); }
    }
    else if (op === "STORE") put("v" + arg + " = " + strip(S.pop()));
    else if (BIN[op]) { const b = S.pop(), a = S.pop(); S.push("(" + a + " " + BIN[op] + " " + b + ")"); }
    else if (CMP[op]) { const b = S.pop(), a = S.pop(); S.push("(" + a + " " + CMP[op] + " " + b + ")"); }
    else if (op === "OUT") put("print(" + strip(S.pop()) + ")");
    else if (op === "IF") { put("if " + strip(S.pop()) + ":"); indent++; }
    else if (op === "ELSE") { indent--; put("else:"); indent++; }
    else if (op === "WHILE") { put("while " + strip(S.pop()) + ":"); indent++; }
    else if (op === "END") { indent--; if (S.length) S.pop(); }
  }
  return lines.join("\n");
}

function compileAndShow() {
  $("out").className = "out";
  try {
    const { code } = compilePython($("src").value);
    const r = run(code);
    const pst = code.map(([op, arg]) => ({ op, arg, iter: 0, val: null }));
    const real = realize(pst, params());
    lastNotes = real.notes;
    $("out").textContent = r.out.join("  ") || "(no output)";
    // Try to round-trip through the decoder to show the recovered Python
    try {
      const dec = decodeNotes(real.notes);
      $("recpy").textContent = decompileLight(dec) || "(decoded ok)";
    } catch (e) { $("recpy").textContent = "decode error: " + e.message; }
  } catch (e) {
    $("out").className = "out err";
    $("out").textContent = "⚠ " + (e.message || e);
    lastNotes = [];
  }
}

$("play").onclick = async () => { compileAndShow(); if (lastNotes.length) await playNotes(lastNotes); };
$("stop").onclick = stopAudio;
["mode","key","octave","tempo","variation"].forEach(id => $(id).addEventListener("input", compileAndShow));
$("src").addEventListener("input", () => { clearTimeout(window._t); window._t = setTimeout(compileAndShow, 300); });

$("demo-btn").onclick = () => {
  const names = Object.keys(DEMOS);
  const cur = names.find(n => DEMOS[n] === $("src").value) || "fibonacci";
  const next = names[(names.indexOf(cur) + 1) % names.length];
  $("src").value = DEMOS[next]; compileAndShow();
};

$("export-mid").onclick = () => { if (lastNotes.length) downloadMidi(lastNotes, "musical_dynamics.mid"); };
$("export-xml").onclick = () => { if (lastNotes.length) downloadMusicXML(lastNotes, "musical_dynamics.musicxml"); };
$("export-wav").onclick = async () => {
  if (!lastNotes.length) return;
  const wav = await synthToWav(lastNotes);
  const blob = new Blob([wav], { type: "audio/wav" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "musical_dynamics.wav"; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 100);
};

// ---------- file-in-WAV stego UI ----------
async function readAsArrayBuffer(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r.readAsArrayBuffer(file);
  });
}

$("emb-go").onclick = async () => {
  const log = $("stego-log");
  log.textContent = "embedding...";
  const carrierFile = $("emb-carrier").files[0];
  const payloadFile = $("emb-payload").files[0];
  if (!carrierFile || !payloadFile) { log.textContent = "pick a carrier WAV and a payload first."; return; }
  try {
    const carrier = new WavCarrier(await readAsArrayBuffer(carrierFile));
    const payload = new Uint8Array(await readAsArrayBuffer(payloadFile));
    const r = $("emb-redundancy").value;
    const info = embed(carrier, payload, payloadFile.name, { redundancy: r ? +r : null });
    const blob = new Blob([carrier.toArrayBuffer()], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "stego.wav"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 100);
    log.textContent = `hid ${payload.length} bytes of "${payloadFile.name}" in ${carrierFile.name}\n` +
                      `K=${info.K}, ${info.nSymbols} symbols (${info.redundancy}× redundancy), ` +
                      `tolerates losing ${info.tolerates_symbol_loss} of the carrier\n` +
                      `downloaded as stego.wav — the Python CLI can also read it`;
  } catch (e) {
    log.textContent = "⚠ " + (e.message || e);
  }
};

$("ext-go").onclick = async () => {
  const log = $("stego-log");
  const f = $("ext-file").files[0];
  if (!f) { log.textContent = "pick a stego .wav first."; return; }
  log.textContent = "extracting...";
  try {
    const carrier = new WavCarrier(await readAsArrayBuffer(f));
    const { name, data, hdr } = extract(carrier);
    const blob = new Blob([data], { type: "application/octet-stream" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name || "payload.bin"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 100);
    log.textContent = `extracted "${name}" (${data.length} bytes) at ${hdr.nSymbols / hdr.K | 0}× redundancy.\n` +
                      `downloaded.`;
  } catch (e) {
    log.textContent = e instanceof PipelineError ? "⚠ " + e.message : "⚠ " + (e.message || e);
  }
};

// boot
$("src").value = DEMOS.fibonacci;
compileAndShow();
