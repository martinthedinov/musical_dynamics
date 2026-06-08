// Opcode/chord tables, scale modes, operand register encoding.
// Identical to mc_codec.py and the verified index.html JS (tested in ~10M decodes).

export const MODES = {
  major: [0,2,4,5,7,9,11], minor: [0,2,3,5,7,8,10],
  dorian: [0,2,3,5,7,9,10], phrygian: [0,1,3,5,7,8,10],
  lydian: [0,2,4,6,7,9,11], mixolydian: [0,2,4,5,7,9,10],
  pent_major: [0,2,4,7,9], pent_minor: [0,3,5,7,10],
  whole_tone: [0,2,4,6,8,10],
};

export const scaleShift = (deg, sc) => {
  const n = sc.length;
  deg = ((deg % (2 * n)) + 2 * n) % (2 * n);
  return sc[deg % n] + 12 * Math.floor(deg / n);
};

// Opcode -> family of chord-quality signatures (intervals above the root). 21 opcodes, 27
// disjoint chords. Primary form first; the second variant (when present) gives the variation
// channel an extra bit of choice.
export const QFAMILY = {
  PUSH:[[0,4,7],[0,4,7,9]], LOAD:[[0,3,7],[0,3,7,10]], STORE:[[0,5,7],[0,5,7,10]],
  ADD:[[0,2,7]], SUB:[[0,4,7,11]], MUL:[[0,4,8]], DIV:[[0,3,8]], MOD:[[0,4,6]],
  EQ:[[0,4,7,10]], NE:[[0,6]], LT:[[0,3,7,9]], GT:[[0,3,7,11]], LE:[[0,4,8,10]], GE:[[0,3,6,10]],
  IF:[[0,3,6],[0,2,3,7]], ELSE:[[0,1,2]], WHILE:[[0,3,6,9]], END:[[0,7],[0,1,7]],
  OUT:[[0,2,4,7]], DUP:[[0,5]], MKSTR:[[0,2,5],[0,2,5,9]],
};

export const HAS_ARG = new Set(["PUSH", "LOAD", "STORE", "MKSTR"]);

// Operand "data register": low MIDI band, never transposed by key/octave/climb.
// Lossless for 0..OPERAND_MAX = 12**8-1 = 429,981,695 (covers all Unicode code points).
export const OPERAND_BASE  = 24;
export const OPERAND_RADIX = 12;
export const OPERAND_BANDS = Math.floor((127 - OPERAND_BASE - (OPERAND_RADIX - 1)) / 12) + 1;
export const OPERAND_MAX   = Math.pow(OPERAND_RADIX, OPERAND_BANDS) - 1;

export function encOperand(v) {
  v = v | 0;
  if (v < 0) throw new Error("operand must be ≥0");
  if (v > OPERAND_MAX) throw new Error("operand too large (max " + OPERAND_MAX + ")");
  const d = [];
  if (v === 0) d.push(0);
  else while (v > 0) { d.push(v % OPERAND_RADIX); v = Math.floor(v / OPERAND_RADIX); }
  return d.map((dig, i) => OPERAND_BASE + i * 12 + dig);
}
export function decOperand(ps) {
  let v = 0;
  for (const p of ps) {
    const k = p - OPERAND_BASE;
    v += (k % 12) * Math.pow(OPERAND_RADIX, Math.floor(k / 12));
  }
  return v;
}

// Build the reverse map (chord signature -> opcode) once; asserts disjointness.
export const QREV = {};
for (const [op, fam] of Object.entries(QFAMILY)) {
  for (const q of fam) {
    const sig = [...new Set(q.map(x => ((x % 12) + 12) % 12))].sort((a, b) => a - b).join(",");
    if (QREV[sig] !== undefined) console.error("AMBIGUOUS chord:", sig, QREV[sig], "vs", op);
    QREV[sig] = op;
  }
}

export const CHORDNAME = {
  "0,4,7":"maj","0,4,7,9":"6","0,3,7":"min","0,3,7,10":"m7","0,5,7":"sus4","0,5,7,10":"7s4",
  "0,2,7":"sus2","0,4,7,11":"maj7","0,4,8":"aug","0,3,8":"m#5","0,4,6":"♭5","0,4,7,10":"7",
  "0,6":"tritone","0,3,7,9":"m6","0,3,7,11":"mM7","0,4,8,10":"aug7","0,3,6,10":"m7♭5",
  "0,3,6":"dim","0,2,3,7":"madd9","0,1,2":"clus3","0,3,6,9":"dim7","0,7":"5th","0,1,7":"7♭9",
  "0,2,4,7":"add9","0,5":"4th","0,2,5":"q4","0,2,5,9":"q4add",
};

// Per-opcode duration/velocity/control hints used by the realizer.
export const CAT = {
  LOAD:[.30,52,0], STORE:[.30,54,0], DUP:[.30,52,0], PUSH:[.40,64,0],
  ADD:[.40,70,0], SUB:[.40,70,0], MUL:[.40,70,0], DIV:[.40,70,0], MOD:[.40,70,0],
  EQ:[.40,68,0], NE:[.40,68,0], LT:[.40,68,0], GT:[.40,68,0], LE:[.40,68,0], GE:[.40,68,0],
  IF:[.55,86,1], ELSE:[.55,84,1], WHILE:[.60,90,1], END:[.55,80,1], OUT:[.50,58,1],
  MKSTR:[.45,72,0],
};
