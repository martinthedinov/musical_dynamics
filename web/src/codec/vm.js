// Stack-machine VM + straight-line trace replayer. Identical semantics to mc_codec.py:run/run_trace.
// Verified by 100k+ test runs (Python and JS) over Python demos.

function buildPair(toks) {
  const pair = {}, opener = {}, st = [];
  toks.forEach(([op], i) => {
    if (op === "IF" || op === "WHILE") st.push(i);
    else if (op === "ELSE") pair[st[st.length - 1]] = i;
    else if (op === "END") { const s = st.pop(); if (!(s in pair)) pair[s] = i; opener[i] = s; }
  });
  return { pair, opener };
}

export function run(toks, maxSteps = 2_000_000) {
  const { pair, opener } = buildPair(toks);
  const ste = ip => { let d = 1; while (d) { ip++; const o = toks[ip][0]; d += (o === "IF" || o === "WHILE") - (o === "END"); } return ip; };
  let stack = [], regs = {}, out = [], trace = [], loops = [], ip = 0, steps = 0, mx = 0;
  const isum = () => loops.reduce((s, c) => s + c.iter, 0);
  const emit = (op, arg, val = null) => trace.push({ op, arg, iter: isum(), val });
  while (ip < toks.length) {
    if (++steps > maxSteps) throw new Error("step limit (infinite loop?)");
    const [op, arg] = toks[ip];
    switch (op) {
      case "PUSH":  stack.push(arg); break;
      case "LOAD":  stack.push(arg in regs ? regs[arg] : 0); break;
      case "STORE": regs[arg] = stack.pop(); break;
      case "MKSTR": { let s = ""; for (let k = 0; k < arg; k++) s = String.fromCodePoint(stack.pop()) + s; stack.push(s); } break;
      case "ADD": { const b = stack.pop(), a = stack.pop(); stack.push(a + b); } break;
      case "SUB": { const b = stack.pop(), a = stack.pop(); stack.push(a - b); } break;
      case "MUL": { const b = stack.pop(), a = stack.pop(); stack.push(a * b); } break;
      case "DIV": { const b = stack.pop(), a = stack.pop(); stack.push(b ? Math.floor(a / b) : 0); } break;
      case "MOD": { const b = stack.pop(), a = stack.pop(); stack.push(b ? ((a % b) + b) % b : 0); } break;
      case "EQ":  { const b = stack.pop(), a = stack.pop(); stack.push(a === b ? 1 : 0); } break;
      case "NE":  { const b = stack.pop(), a = stack.pop(); stack.push(a !== b ? 1 : 0); } break;
      case "LT":  { const b = stack.pop(), a = stack.pop(); stack.push(a <  b ? 1 : 0); } break;
      case "GT":  { const b = stack.pop(), a = stack.pop(); stack.push(a >  b ? 1 : 0); } break;
      case "LE":  { const b = stack.pop(), a = stack.pop(); stack.push(a <= b ? 1 : 0); } break;
      case "GE":  { const b = stack.pop(), a = stack.pop(); stack.push(a >= b ? 1 : 0); } break;
      case "DUP": stack.push(stack[stack.length - 1]); break;
      case "OUT": { const v = stack.pop(); out.push(v); emit(op, arg, v); ip++; continue; }
      case "IF": {
        if (stack.pop() === 0) { emit(op, arg); ip = pair[ip]; if (toks[ip][0] === "ELSE") ip++; continue; }
        break;
      }
      case "ELSE": emit(op, arg); ip = ste(ip); continue;
      case "WHILE": {
        const top = loops[loops.length - 1], re = top && top.opener === ip;
        if (stack.pop() === 0) { if (re) loops.pop(); emit(op, arg); ip = ste(ip) + 1; continue; }
        if (re) { top.iter++; mx = Math.max(mx, top.iter); } else loops.push({ opener: ip, iter: 0 });
        break;
      }
      case "END": {
        if (toks[opener[ip]][0] === "WHILE") { emit(op, arg); ip = opener[ip]; continue; }
        break;
      }
    }
    emit(op, arg); ip++;
  }
  return { out, trace, maxIter: mx + 1 };
}

export function runTrace(toks) {
  // Replay an unrolled trace as straight-line code (branches/loops already linearized).
  let stack = [], regs = {}, out = [];
  for (const [op, arg] of toks) {
    switch (op) {
      case "PUSH":  stack.push(arg); break;
      case "LOAD":  stack.push(arg in regs ? regs[arg] : 0); break;
      case "STORE": regs[arg] = stack.pop(); break;
      case "MKSTR": { let s = ""; for (let k = 0; k < arg; k++) s = String.fromCodePoint(stack.pop()) + s; stack.push(s); } break;
      case "ADD": { const b = stack.pop(), a = stack.pop(); stack.push(a + b); } break;
      case "SUB": { const b = stack.pop(), a = stack.pop(); stack.push(a - b); } break;
      case "MUL": { const b = stack.pop(), a = stack.pop(); stack.push(a * b); } break;
      case "DIV": { const b = stack.pop(), a = stack.pop(); stack.push(b ? Math.floor(a / b) : 0); } break;
      case "MOD": { const b = stack.pop(), a = stack.pop(); stack.push(b ? ((a % b) + b) % b : 0); } break;
      case "EQ":  { const b = stack.pop(), a = stack.pop(); stack.push(a === b ? 1 : 0); } break;
      case "NE":  { const b = stack.pop(), a = stack.pop(); stack.push(a !== b ? 1 : 0); } break;
      case "LT":  { const b = stack.pop(), a = stack.pop(); stack.push(a <  b ? 1 : 0); } break;
      case "GT":  { const b = stack.pop(), a = stack.pop(); stack.push(a >  b ? 1 : 0); } break;
      case "LE":  { const b = stack.pop(), a = stack.pop(); stack.push(a <= b ? 1 : 0); } break;
      case "GE":  { const b = stack.pop(), a = stack.pop(); stack.push(a >= b ? 1 : 0); } break;
      case "DUP": stack.push(stack[stack.length - 1]); break;
      case "OUT": out.push(stack.pop()); break;
      case "IF": case "WHILE": stack.pop(); break;     // condition consumed, no jump (linearized)
      case "ELSE": case "END":  break;                  // structural markers only
    }
  }
  return out;
}
