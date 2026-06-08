// Python-subset compiler: parses a small Python subset (ints/strings, + - * // %,
// comparisons, if/elif/else, while, for-range, print, =, +=, ...) and emits opcodes.
// Algorithm is byte-identical to mc_codec.py's compile_python.
const KW  = new Set(["while", "if", "elif", "else", "for", "in", "range", "print"]);
const OPS = ["//=", "//", "==", "!=", "<=", ">=", "+=", "-=", "*=", "%=",
             "=", "<", ">", "+", "-", "*", "%", "(", ")", ",", ":"];

function lex(s) {
  const o = []; let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c === " " || c === "\t") { i++; continue; }
    if (c === '"' || c === "'") {
      const q = c; let j = i + 1, str = "";
      while (j < s.length && s[j] !== q) {
        if (s[j] === "\\") {
          const n = s[j+1];
          str += (n === "n" ? "\n" : n === "t" ? "\t" : n === "\\" ? "\\" : n === "r" ? "\r" : n);
          j += 2;
        } else { str += s[j]; j++; }
      }
      if (j >= s.length) throw new Error("unterminated string");
      o.push({ t: "str", v: str }); i = j + 1; continue;
    }
    if (/\d/.test(c)) {
      let j = i;
      while (j < s.length && /\d/.test(s[j])) j++;
      o.push({ t: "num", v: parseInt(s.slice(i, j), 10) }); i = j; continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      let j = i;
      while (j < s.length && /[A-Za-z0-9_]/.test(s[j])) j++;
      const w = s.slice(i, j);
      o.push({ t: KW.has(w) ? "kw" : "name", v: w }); i = j; continue;
    }
    let m = null;
    for (const op of OPS) if (s.startsWith(op, i)) { m = op; break; }
    if (!m) throw new Error("lex error near: " + s.slice(i));
    o.push({ t: "op", v: m }); i += m.length;
  }
  return o;
}

function preprocess(src) {
  const L = [];
  for (let raw of src.replace(/\r/g, "").split("\n")) {
    raw = raw.split("#")[0];
    if (!raw.trim()) continue;
    let ind = 0;
    for (const ch of raw) { if (ch === " ") ind++; else if (ch === "\t") ind += 4; else break; }
    L.push({ indent: ind, text: raw.trim() });
  }
  return L;
}

function parseExpr(toks) {
  let p = 0;
  const peek = () => toks[p], next = () => toks[p++];
  function atom() {
    const t = next();
    if (!t) throw new Error("unexpected end of expression");
    if (t.t === "num") return { k: "num", v: t.v };
    if (t.t === "str") return { k: "str", v: t.v };
    if (t.t === "name") return { k: "name", v: t.v };
    if (t.t === "op" && t.v === "(") {
      const e = expr(0); const c = next();
      if (!c || c.v !== ")") throw new Error("expected )");
      return e;
    }
    if (t.t === "op" && t.v === "-") return { k: "neg", e: atom() };
    throw new Error("unexpected token");
  }
  const PREC = { "<":1, ">":1, "<=":1, ">=":1, "==":1, "!=":1, "+":2, "-":2, "*":3, "%":3, "//":3 };
  function expr(min) {
    let left = atom();
    while (peek() && peek().t === "op" && PREC[peek().v] !== undefined && PREC[peek().v] >= min) {
      const op = next().v;
      left = { k: "bin", op, left, right: expr(PREC[op] + 1) };
    }
    return left;
  }
  const e = expr(0);
  if (p !== toks.length) throw new Error("trailing tokens in expression");
  return e;
}

export function compilePython(src) {
  const lines = preprocess(src); let pos = 0;
  function suite(ind) { const o = []; while (pos < lines.length && lines[pos].indent === ind) o.push(statement(ind)); return o; }
  function statement(ind) {
    const t = lex(lines[pos].text), h = t[0];
    if (h.t === "kw" && ["while","if","elif","else","for"].includes(h.v)) return compound(ind, t);
    pos++; return simple(t);
  }
  function condTokens(t) {
    if (t[t.length - 1].v !== ":") throw new Error("expected ':'");
    return t.slice(1, t.length - 1);
  }
  function ci() {
    if (pos >= lines.length) throw new Error("expected an indented block");
    return lines[pos].indent;
  }
  function compound(ind, t) {
    const kw = t[0].v;
    if (kw === "while") { const test = parseExpr(condTokens(t)); pos++; return { type: "while", test, body: suite(ci()) }; }
    if (kw === "for") {
      if (t[1].t !== "name" || t[2].v !== "in" || t[3].v !== "range" || t[4].v !== "(") throw new Error("bad for-loop");
      let close = t.length - 2;
      if (t[close].v !== ")" || t[t.length-1].v !== ":") throw new Error("bad for-loop tail");
      const inner = t.slice(5, close), args = [];
      let depth = 0, start = 0;
      for (let i = 0; i < inner.length; i++) {
        const v = inner[i].v;
        if      (v === "(") depth++;
        else if (v === ")") depth--;
        else if (v === "," && depth === 0) { args.push(inner.slice(start, i)); start = i + 1; }
      }
      if (inner.length) args.push(inner.slice(start));
      const ex = args.map(parseExpr);
      pos++; const body = suite(ci());
      return { type: "for", var: t[1].v,
               start: ex.length === 1 ? { k: "num", v: 0 } : ex[0],
               stop:  ex.length === 1 ? ex[0] : ex[1],
               body };
    }
    if (kw === "if" || kw === "elif") {
      const test = parseExpr(condTokens(t)); pos++;
      const body = suite(ci()); let orelse = [];
      if (pos < lines.length && lines[pos].indent === ind) {
        const t2 = lex(lines[pos].text);
        if (t2[0].v === "elif") orelse = [compound(ind, t2)];
        else if (t2[0].v === "else") { pos++; orelse = suite(ci()); }
      }
      return { type: "if", test, body, orelse };
    }
    throw new Error("unexpected " + kw);
  }
  function simple(t) {
    if (t[0].v === "print") {
      if (t[1].v !== "(") throw new Error("print needs (");
      return { type: "print", expr: parseExpr(t.slice(2, t.length - 1)) };
    }
    if (t[0].t !== "name") throw new Error("can't parse statement");
    const name = t[0].v, op = t[1].v;
    if (op === "=") return { type: "assign", name, expr: parseExpr(t.slice(2)) };
    if (["+=", "-=", "*=", "%=", "//="].includes(op))
      return { type: "aug", name, op: op.slice(0, -1), expr: parseExpr(t.slice(2)) };
    throw new Error("can't parse: " + t.map(x => x.v).join(" "));
  }

  const prog = suite(lines.length ? lines[0].indent : 0);
  const regs = {}, code = [];
  const reg = n => { if (!(n in regs)) regs[n] = Object.keys(regs).length; return regs[n]; };
  let tmp = 0; const newtmp = () => reg("__t" + (++tmp));
  const BIN = { "+":"ADD", "-":"SUB", "*":"MUL", "%":"MOD", "//":"DIV" };
  const CMP = { "<":"LT", ">":"GT", "<=":"LE", ">=":"GE", "==":"EQ", "!=":"NE" };

  function E(e) {
    if (e.k === "num") code.push(["PUSH", e.v]);
    else if (e.k === "name") code.push(["LOAD", reg(e.v)]);
    else if (e.k === "str") { for (const ch of e.v) code.push(["PUSH", ch.codePointAt(0)]); code.push(["MKSTR", [...e.v].length]); }
    else if (e.k === "neg") { code.push(["PUSH", 0]); E(e.e); code.push(["SUB", null]); }
    else if (e.k === "bin") { E(e.left); E(e.right); code.push([BIN[e.op] || CMP[e.op], null]); }
    else throw new Error("expr?");
  }
  function B(s) { for (const x of s) ST(x); }
  function ST(s) {
    if (s.type === "assign") { E(s.expr); code.push(["STORE", reg(s.name)]); }
    else if (s.type === "aug") { const r = reg(s.name); code.push(["LOAD", r]); E(s.expr); code.push([BIN[s.op], null]); code.push(["STORE", r]); }
    else if (s.type === "print") { E(s.expr); code.push(["OUT", null]); }
    else if (s.type === "while") { E(s.test); code.push(["WHILE", null]); B(s.body); E(s.test); code.push(["END", null]); }
    else if (s.type === "if") {
      E(s.test); code.push(["IF", null]); B(s.body);
      if (s.orelse.length) { code.push(["ELSE", null]); B(s.orelse); }
      code.push(["END", null]);
    }
    else if (s.type === "for") {
      const v = reg(s.var); E(s.start); code.push(["STORE", v]);
      const et = newtmp(); E(s.stop); code.push(["STORE", et]);
      code.push(["LOAD", v], ["LOAD", et], ["LT", null], ["WHILE", null]);
      B(s.body);
      code.push(["LOAD", v], ["PUSH", 1], ["ADD", null], ["STORE", v]);
      code.push(["LOAD", v], ["LOAD", et], ["LT", null], ["END", null]);
    }
    else throw new Error("stmt?");
  }
  B(prog);
  return { code, regs };
}
