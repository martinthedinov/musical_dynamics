// Realizer (opcodes/trace -> notes) + decoder (notes -> opcodes). Identical to mc_codec.py.
import { MODES, scaleShift, QFAMILY, HAS_ARG, QREV, CAT, encOperand, decOperand } from "./opcodes.js";

export const COL = {
  PUSH:"--maj", LOAD:"--min", STORE:"--min", DUP:"--min",
  ADD:"--op", SUB:"--op", MUL:"--op", DIV:"--op", MOD:"--op",
  EQ:"--op", NE:"--op", LT:"--op", GT:"--op", LE:"--op", GE:"--op",
  IF:"--ctrl", ELSE:"--ctrl", WHILE:"--ctrl", END:"--ctrl", OUT:"--ctrl",
  MKSTR:"--maj",
};

export function realize(trace, P) {
  const sc = MODES[P.mode], root0 = 60 + P.key + 12 * P.octave, n = sc.length;
  const notes = []; let t = 0;
  for (let k = 0; k < trace.length; k++) {
    const s = trace[k], op = s.op;
    let [dur, vel, ctrl] = CAT[op] || [.4, 64, 0];
    dur *= P.tempo;
    let step = dur, gate = dur * 0.95;
    if      (P.feel === "staccato") gate = dur * 0.5;
    else if (P.feel === "legato")   gate = dur * 1.25;
    else if (P.feel === "swing")    { step = dur * (k % 2 === 0 ? 1.34 : 0.66); gate = step * 0.9; }
    const fam = QFAMILY[op], q = fam[P.variation % fam.length];
    const tp = scaleShift(s.iter * P.climb, sc), root = root0 + tp;
    const voiced = [root + q[0]];
    for (let j = 1; j < q.length; j++) {
      const up = ((P.variation >> j) & 1) ? 12 : 0;
      voiced.push(root + q[j] + up);
    }
    for (const p of voiced) notes.push({ p, t, d: gate, vel, role: "pad", col: COL[op], tp });
    if (ctrl) notes.push({ p: root - 24, t, d: step, vel: Math.max(1, vel - 12), role: "bass", col: "--ctrl", tp });
    if (HAS_ARG.has(op)) {
      for (const p of encOperand(s.arg | 0)) notes.push({ p, t, d: gate * 0.9, vel: 96, role: "operand", col: "--acc", tp: 0 });
    } else if (op === "OUT" && s.val != null) {
      const sv = s.val;
      const v = (typeof sv === "number") ? Math.abs(sv | 0) : (sv.length ? sv.codePointAt(0) : 0);
      let mp;
      if      (P.melody === "pulse")     mp = root0 + 19;
      else if (P.melody === "chromatic") mp = root0 + 12 + (v % 24);
      else if (P.melody === "compact")   mp = root0 + 12 + sc[v % n];
      else                                mp = root0 + 12 + sc[v % n] + 12 * (Math.floor(v / n) % 3);
      notes.push({ p: mp, t, d: gate * 1.1, vel: 110, role: "lead", col: "--lead", tp });
    }
    t += step;
  }
  return { notes, total: t };
}

export function decodeNotes(notes) {
  const onsets = new Map();
  for (const nt of notes) {
    if (nt.role === "bass") continue;
    const key = Math.round(nt.t / 0.0001);
    if (!onsets.has(key)) onsets.set(key, { t: nt.t, ch0: [], ch1: [] });
    (nt.role === "pad" ? onsets.get(key).ch0 : onsets.get(key).ch1).push(nt.p);
  }
  const keys = [...onsets.keys()].sort((a, b) => onsets.get(a).t - onsets.get(b).t);
  const code = [];
  for (const key of keys) {
    const ev = onsets.get(key);
    const root = Math.min(...ev.ch0);
    const sig = [...new Set(ev.ch0.map(p => ((p - root) % 12 + 12) % 12))].sort((a, b) => a - b).join(",");
    const op = QREV[sig];
    if (op === undefined) throw new Error("undecodable chord [" + sig + "]");
    let arg = null;
    if (HAS_ARG.has(op)) {
      if (!ev.ch1.length) throw new Error("missing operand for " + op);
      arg = decOperand(ev.ch1);
    }
    code.push([op, arg]);
  }
  return code;
}
