"""
mc_codec — back-and-forth translation:  Python  <->  opcodes  <->  music (MIDI).

DETERMINISM (the design principle)
  * decode (music -> opcodes -> output/Python) is a pure FUNCTION. One music, one program.
  * encode (Python -> music) is one-to-MANY, but the choice among the many is a deliberate
    compositional input (the `variation` selector + mode/key/etc.), never hidden randomness.
  * the decoder is INVARIANT to every compositional choice, because:
      - opcode  = chord QUALITY, read as intervals from the bass; the bass is ALWAYS the
        chord root (no inversions), so octave-spread / register / key / climb don't matter.
      - each opcode owns a FAMILY of distinct qualities (the redundancy). quality -> opcode
        is a clean reverse lookup.
      - operands ride on a dedicated channel at a FIXED register (OPERAND_BASE + value),
        which the climb/key/octave never transpose -> losslessly recoverable.
"""
import ast, io, contextlib
from dataclasses import dataclass

# ---------- opcode -> FAMILY of chord qualities (intervals from root). Primary first. ----------
QFAMILY = {
    "PUSH":  [(0,4,7),(0,4,7,9)],      "LOAD":  [(0,3,7),(0,3,7,10)],  "STORE": [(0,5,7),(0,5,7,10)],
    "ADD":   [(0,2,7)],                "SUB":   [(0,4,7,11)],          "MUL":   [(0,4,8)],
    "DIV":   [(0,3,8)],                "MOD":   [(0,4,6)],
    "EQ":    [(0,4,7,10)],             "NE":    [(0,6)],               "LT":    [(0,3,7,9)],
    "GT":    [(0,3,7,11)],             "LE":    [(0,4,8,10)],          "GE":    [(0,3,6,10)],
    "IF":    [(0,3,6),(0,2,3,7)],      "ELSE":  [(0,1,2)],             "WHILE": [(0,3,6,9)],
    "END":   [(0,7),(0,1,7)],          "OUT":   [(0,2,4,7)],           "DUP":   [(0,5)],
    "MKSTR": [(0,2,5),(0,2,5,9)],      # assemble a string from N popped char codes
}
HAS_ARG = {"PUSH","LOAD","STORE","MKSTR"}
OPERAND_BASE  = 24                     # fixed "data register" (kept low to leave MIDI headroom); never transposed
OPERAND_RADIX = 12                     # operands written base-12, one octave band per digit
# A digit lives in band b at pitch OPERAND_BASE + 12*b + digit. The top pitch of the highest
# usable band must stay within MIDI 0..127, which bounds how many bands (hence the max value) we get.
OPERAND_BANDS = (127 - OPERAND_BASE - (OPERAND_RADIX - 1)) // 12 + 1   # = 8 with base 24
OPERAND_MAX   = OPERAND_RADIX ** OPERAND_BANDS - 1                     # = 429,981,695

def enc_operand(v):
    """non-negative int -> list of pitches (>=1 note); each note's octave band = its base-12 digit position.
       Lossless for 0..OPERAND_MAX, which covers every Unicode code point (<=0x10FFFF) and large literals."""
    v0 = v = int(v)
    if v < 0: raise ValueError("operands must be non-negative")
    if v > OPERAND_MAX:
        raise ValueError("operand %d too large (max %d per literal; build bigger values arithmetically)" % (v0, OPERAND_MAX))
    digits = [0] if v == 0 else []
    while v > 0: digits.append(v % OPERAND_RADIX); v //= OPERAND_RADIX
    return [OPERAND_BASE + i*12 + d for i, d in enumerate(digits)]

def dec_operand(pitches):
    """inverse of enc_operand; order-independent (band carries digit position)."""
    v = 0
    for p in pitches:
        k = p - OPERAND_BASE; v += (k % 12) * (OPERAND_RADIX ** (k // 12))
    return v

# reverse map quality-signature -> opcode, with disjointness guarantee
QREV = {}
for _op, _fam in QFAMILY.items():
    for _q in _fam:
        sig = tuple(sorted(set(x % 12 for x in _q)))
        assert sig not in QREV, f"AMBIGUOUS quality {sig}: {QREV.get(sig)} vs {_op}"
        QREV[sig] = _op

MODES = {"major":[0,2,4,5,7,9,11],"minor":[0,2,3,5,7,8,10],"dorian":[0,2,3,5,7,9,10],
 "phrygian":[0,1,3,5,7,8,10],"lydian":[0,2,4,6,7,9,11],"mixolydian":[0,2,4,5,7,9,10],
 "pent_major":[0,2,4,7,9],"pent_minor":[0,3,5,7,10],"whole_tone":[0,2,4,6,8,10]}
def scale_shift(deg, sc):
    n=len(sc); deg%=(2*n); return sc[deg%n]+12*(deg//n)

# ================= Python-subset compiler (real ast) =================
BINOP={ast.Add:"ADD",ast.Sub:"SUB",ast.Mult:"MUL",ast.Mod:"MOD",ast.FloorDiv:"DIV"}
CMPOP={ast.Lt:"LT",ast.Gt:"GT",ast.LtE:"LE",ast.GtE:"GE",ast.Eq:"EQ",ast.NotEq:"NE"}
def compile_python(src):
    tree=ast.parse(src); regs={}; code=[]; tmp=[0]
    def reg(n):
        if n not in regs: regs[n]=len(regs)
        return regs[n]
    def newtmp(): tmp[0]+=1; return reg("__t%d"%tmp[0])
    def E(e):
        if isinstance(e,ast.Constant):
            if isinstance(e.value,bool): raise ValueError("bools not supported")
            if isinstance(e.value,int): code.append(("PUSH",e.value))
            elif isinstance(e.value,str):
                for ch in e.value: code.append(("PUSH",ord(ch)))
                code.append(("MKSTR",len(e.value)))
            else: raise ValueError("only int and str literals")
        elif isinstance(e,ast.Name): code.append(("LOAD",reg(e.id)))
        elif isinstance(e,ast.BinOp): E(e.left);E(e.right);code.append((BINOP[type(e.op)],None))
        elif isinstance(e,ast.UnaryOp) and isinstance(e.op,ast.USub): code.append(("PUSH",0));E(e.operand);code.append(("SUB",None))
        elif isinstance(e,ast.Compare) and len(e.ops)==1: E(e.left);E(e.comparators[0]);code.append((CMPOP[type(e.ops[0])],None))
        else: raise ValueError("expr: "+ast.dump(e))
    def B(ss):
        for s in ss: S(s)
    def S(s):
        if isinstance(s,ast.Assign) and len(s.targets)==1 and isinstance(s.targets[0],ast.Name):
            E(s.value);code.append(("STORE",reg(s.targets[0].id)))
        elif isinstance(s,ast.AugAssign) and isinstance(s.target,ast.Name):
            r=reg(s.target.id);code.append(("LOAD",r));E(s.value);code.append((BINOP[type(s.op)],None));code.append(("STORE",r))
        elif (isinstance(s,ast.Expr) and isinstance(s.value,ast.Call) and isinstance(s.value.func,ast.Name)
              and s.value.func.id=="print" and len(s.value.args)==1):
            E(s.value.args[0]);code.append(("OUT",None))
        elif isinstance(s,ast.While):
            E(s.test);code.append(("WHILE",None));B(s.body);E(s.test);code.append(("END",None))
        elif isinstance(s,ast.If):
            E(s.test);code.append(("IF",None));B(s.body)
            if s.orelse: code.append(("ELSE",None));B(s.orelse)
            code.append(("END",None))
        elif isinstance(s,ast.For) and isinstance(s.target,ast.Name) and isinstance(s.iter,ast.Call) and getattr(s.iter.func,"id",None)=="range":
            v=reg(s.target.id); a=s.iter.args
            start,stop=(ast.Constant(0),a[0]) if len(a)==1 else (a[0],a[1])
            E(start);code.append(("STORE",v)); et=newtmp(); E(stop);code.append(("STORE",et))
            code.append(("LOAD",v));code.append(("LOAD",et));code.append(("LT",None));code.append(("WHILE",None))
            B(s.body)
            code.append(("LOAD",v));code.append(("PUSH",1));code.append(("ADD",None));code.append(("STORE",v))
            code.append(("LOAD",v));code.append(("LOAD",et));code.append(("LT",None));code.append(("END",None))
        else: raise ValueError("stmt: "+ast.dump(s))
    B(tree.body); return code, regs

# ================= VM =================
def run(toks, max_steps=2_000_000):
    pair,opener_of,st={},{},[]
    for i,(op,_) in enumerate(toks):
        if op in ("IF","WHILE"): st.append(i)
        elif op=="ELSE": pair[st[-1]]=i
        elif op=="END": s=st.pop(); pair.setdefault(s,i); opener_of[i]=s
    def ste(ip):
        d=1
        while d: ip+=1; o=toks[ip][0]; d+=(o in ("IF","WHILE"))-(o=="END")
        return ip
    stack,regs,out,trace,loops,ip,steps,mx=[],{},[],[],[],0,0,0
    isum=lambda: sum(c["iter"] for c in loops)
    def emit(op,arg,val=None): trace.append({"op":op,"arg":arg,"iter":isum(),"val":val})
    while ip<len(toks):
        if (steps:=steps+1)>max_steps: raise RuntimeError("step limit")
        op,arg=toks[ip]
        if op=="PUSH": stack.append(arg)
        elif op=="LOAD": stack.append(regs.get(arg,0))
        elif op=="STORE": regs[arg]=stack.pop()
        elif op=="MKSTR":
            chars=[stack.pop() for _ in range(arg)][::-1]
            stack.append("".join(chr(int(c)) if isinstance(c,int) else str(c) for c in chars))
        elif op=="ADD": b,a=stack.pop(),stack.pop(); stack.append(a+b)
        elif op=="SUB": b,a=stack.pop(),stack.pop(); stack.append(a-b)
        elif op=="MUL": b,a=stack.pop(),stack.pop(); stack.append(a*b)
        elif op=="DIV": b,a=stack.pop(),stack.pop(); stack.append(a//b if b else 0)
        elif op=="MOD": b,a=stack.pop(),stack.pop(); stack.append(((a%b)+b)%b if b else 0)
        elif op=="EQ": b,a=stack.pop(),stack.pop(); stack.append(int(a==b))
        elif op=="NE": b,a=stack.pop(),stack.pop(); stack.append(int(a!=b))
        elif op=="LT": b,a=stack.pop(),stack.pop(); stack.append(int(a<b))
        elif op=="GT": b,a=stack.pop(),stack.pop(); stack.append(int(a>b))
        elif op=="LE": b,a=stack.pop(),stack.pop(); stack.append(int(a<=b))
        elif op=="GE": b,a=stack.pop(),stack.pop(); stack.append(int(a>=b))
        elif op=="DUP": stack.append(stack[-1])
        elif op=="OUT": v=stack.pop(); out.append(v); emit(op,arg,v); ip+=1; continue
        elif op=="IF":
            if stack.pop()==0:
                emit(op,arg); ip=pair[ip]
                if toks[ip][0]=="ELSE": ip+=1
                continue
        elif op=="ELSE": emit(op,arg); ip=ste(ip); continue
        elif op=="WHILE":
            top=loops[-1] if loops else None; re=top is not None and top["opener"]==ip
            if stack.pop()==0:
                if re: loops.pop()
                emit(op,arg); ip=ste(ip)+1; continue
            if re: top["iter"]+=1; mx=max(mx,top["iter"])
            else: loops.append({"opener":ip,"iter":0})
        elif op=="END":
            if toks[opener_of[ip]][0]=="WHILE": emit(op,arg); ip=opener_of[ip]; continue
        emit(op,arg); ip+=1
    return out, trace, mx+1

def run_trace(toks):
    """Replay an UNROLLED trace as straight-line code: branches/loops already happened,
    so IF/WHILE just consume their condition and ELSE/END are markers. Reproduces output."""
    stack,regs,out=[],{},[]
    for op,arg in toks:
        if op=="PUSH": stack.append(arg)
        elif op=="LOAD": stack.append(regs.get(arg,0))
        elif op=="STORE": regs[arg]=stack.pop()
        elif op=="MKSTR":
            chars=[stack.pop() for _ in range(arg)][::-1]
            stack.append("".join(chr(int(c)) if isinstance(c,int) else str(c) for c in chars))
        elif op=="ADD": b,a=stack.pop(),stack.pop(); stack.append(a+b)
        elif op=="SUB": b,a=stack.pop(),stack.pop(); stack.append(a-b)
        elif op=="MUL": b,a=stack.pop(),stack.pop(); stack.append(a*b)
        elif op=="DIV": b,a=stack.pop(),stack.pop(); stack.append(a//b if b else 0)
        elif op=="MOD": b,a=stack.pop(),stack.pop(); stack.append(((a%b)+b)%b if b else 0)
        elif op=="EQ": b,a=stack.pop(),stack.pop(); stack.append(int(a==b))
        elif op=="NE": b,a=stack.pop(),stack.pop(); stack.append(int(a!=b))
        elif op=="LT": b,a=stack.pop(),stack.pop(); stack.append(int(a<b))
        elif op=="GT": b,a=stack.pop(),stack.pop(); stack.append(int(a>b))
        elif op=="LE": b,a=stack.pop(),stack.pop(); stack.append(int(a<=b))
        elif op=="GE": b,a=stack.pop(),stack.pop(); stack.append(int(a>=b))
        elif op=="DUP": stack.append(stack[-1])
        elif op=="OUT": out.append(stack.pop())
        elif op in ("IF","WHILE"): stack.pop()      # consume condition; no jump (already linearized)
        elif op in ("ELSE","END"): pass             # structural markers
    return out

# ================= DECODABLE realizer (deterministic; root always = bass) =================
@dataclass
class Note: pitch:int; start:float; dur:float; vel:int; ch:int; role:str; tp:int

CAT={"LOAD":(.30,52,0),"STORE":(.30,54,0),"DUP":(.30,52,0),"PUSH":(.40,64,0),"ADD":(.40,70,0),"SUB":(.40,70,0),
 "MUL":(.40,70,0),"DIV":(.40,70,0),"MOD":(.40,70,0),"EQ":(.40,68,0),"NE":(.40,68,0),"LT":(.40,68,0),"GT":(.40,68,0),
 "LE":(.40,68,0),"GE":(.40,68,0),"IF":(.55,86,1),"ELSE":(.55,84,1),"WHILE":(.60,90,1),"END":(.55,80,1),"OUT":(.50,58,1),
 "MKSTR":(.45,72,0)}

def realize(trace, mode="major", key=0, climb_step=1, octave=0, tempo=1.0, variation=0):
    """variation = deterministic compositional choice (family member + voicing spread)."""
    sc=MODES[mode]; root0=60+key+12*octave; n=len(sc)
    notes, t = [], 0.0
    for k,s in enumerate(trace):
        op=s["op"]; dur,vel,ctrl=CAT.get(op,(.4,64,0)); dur*=tempo
        fam=QFAMILY[op]; q=fam[(variation) % len(fam)]            # deterministic family choice
        tp=scale_shift(s["iter"]*climb_step, sc); root=root0+tp
        # voicing: root stays the bass; spread some upper tones up an octave (deterministic)
        voiced=[root+q[0]]
        for j,iv in enumerate(q[1:],1):
            up = 12 if ((variation>>j) & 1) else 0
            voiced.append(root+iv+up)
        for p in voiced: notes.append(Note(p,t,dur*0.95,vel,0,"pad",tp))
        if ctrl: notes.append(Note(root-24,t,dur,max(1,vel-12),2,"bass",tp))   # ch2 doubling (decoder ignores)
        if op in HAS_ARG:                                          # LOSSLESS operand on ch1, fixed register
            for p in enc_operand(s["arg"]): notes.append(Note(p, t, dur*0.9, 96, 1, "operand", 0))
        elif op=="OUT" and s["val"] is not None:                  # decorative melody (decoder ignores ch1 here)
            val=s["val"]
            v=abs(int(val)) if isinstance(val,int) else (ord(val[0]) if val else 0)
            notes.append(Note(root0+12+sc[v%n]+12*((v//n)%3), t, dur*1.1, 110, 1, "lead", tp))
        t+=dur
    return notes, t

# ================= DECODER:  notes -> opcodes =================
def decode_notes(notes, eps=1e-6):
    # cluster ch0/ch1 by onset (ch2 ignored)
    onsets={}
    for nt in notes:
        if nt.ch==2: continue
        key=round(nt.start/0.0001)
        onsets.setdefault(key, {"t":nt.start, "ch0":[], "ch1":[]})
        ("ch0" if nt.ch==0 else "ch1")
        onsets[key]["ch0" if nt.ch==0 else "ch1"].append(nt.pitch)
    code=[]
    for key in sorted(onsets, key=lambda k:onsets[k]["t"]):
        ev=onsets[key]; ch0=ev["ch0"]
        root=min(ch0)
        sig=tuple(sorted(set((p-root)%12 for p in ch0)))
        op=QREV.get(sig)
        if op is None: raise ValueError("undecodable chord signature %s"%(sig,))
        arg=None
        if op in HAS_ARG:
            if not ev["ch1"]: raise ValueError("missing operand note for %s"%op)
            arg=dec_operand(ev["ch1"])
        code.append((op,arg))
    return code

# ================= MIDI write / read (round trip through a real file) =================
def write_midi(notes, path, bpm=112):
    import mido
    mid=mido.MidiFile(ticks_per_beat=480); tr=mido.MidiTrack(); mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo",tempo=mido.bpm2tempo(bpm)))
    for ch,prog in ((0,89),(1,81),(2,38)): tr.append(mido.Message("program_change",channel=ch,program=prog,time=0))
    ev=[]
    for nt in notes: ev+=[(nt.start,1,nt),(nt.start+nt.dur,0,nt)]
    ev.sort(key=lambda e:(e[0],e[1]))
    last=0.0
    for ts,on,nt in ev:
        d=int(round((ts-last)*480)); last=ts
        tr.append(mido.Message("note_on" if on else "note_off",channel=nt.ch,
                  note=max(0,min(127,nt.pitch)),velocity=nt.vel if on else 0,time=max(0,d)))
    mid.save(path)

def read_midi(path):
    import mido
    mid=mido.MidiFile(path); tick=0; tpb=mid.ticks_per_beat; raw=[]
    for msg in mido.merge_tracks(mid.tracks):
        tick+=msg.time
        if msg.type=="note_on" and msg.velocity>0:
            raw.append((tick, msg.channel, msg.note))
    # group simultaneous ticks into note objects with start in beats
    notes=[]
    for tk,ch,note in raw:
        notes.append(Note(note, tk/tpb, 0.25, 80, ch, "pad" if ch==0 else ("operand" if ch==1 else "bass"), 0))
    return notes

# ================= DECOMPILER:  opcodes -> Python source =================
def _strip(e):
    if e.startswith("(") and e.endswith(")"):
        d=0
        for i,c in enumerate(e):
            d+=(c=="(")-(c==")")
            if d==0 and i<len(e)-1: return e
        return e[1:-1]
    return e
def decompile(toks):
    pair,opener_of,st={},{},[]
    for i,(op,_) in enumerate(toks):
        if op in ("IF","WHILE"): st.append(i)
        elif op=="ELSE": pair[st[-1]]=i
        elif op=="END": s=st.pop(); pair.setdefault(s,i); opener_of[i]=s
    lines=[]; indent=0; S=[]; whilecond=[]
    BIN={"ADD":"+","SUB":"-","MUL":"*","MOD":"%","DIV":"//"}; CMP={"LT":"<","GT":">","LE":"<=","GE":">=","EQ":"==","NE":"!="}
    def put(txt): lines.append("    "*indent+txt)
    ip=0
    while ip<len(toks):
        op,arg=toks[ip]
        if op=="PUSH": S.append(str(arg))
        elif op=="LOAD": S.append("v%d"%arg)
        elif op=="MKSTR":
            parts=[S.pop() for _ in range(arg)][::-1]
            try: S.append(repr("".join(chr(int(x)) for x in parts)))
            except Exception: S.append("str(%s)"%(parts,))
        elif op=="STORE": e=S.pop(); put("v%d = %s"%(arg,_strip(e)))
        elif op in BIN: b,a=S.pop(),S.pop(); S.append("(%s %s %s)"%(a,BIN[op],b))
        elif op in CMP: b,a=S.pop(),S.pop(); S.append("(%s %s %s)"%(a,CMP[op],b))
        elif op=="DUP": S.append(S[-1])
        elif op=="OUT": put("print(%s)"%_strip(S.pop()))
        elif op=="IF": c=_strip(S.pop()); put("if %s:"%c); indent+=1
        elif op=="ELSE": indent-=1; put("else:"); indent+=1
        elif op=="WHILE": c=_strip(S.pop()); put("while %s:"%c); whilecond.append(c); indent+=1
        elif op=="END":
            indent-=1
            if toks[opener_of[ip]][0]=="WHILE":
                if S: S.pop()           # discard the duplicate end-of-body condition
                whilecond.pop()
        ip+=1
    return "\n".join(lines)

# ================= MD language: a tiny C/Python-flavored surface over the SAME opcodes =================
# The opcode list is the canonical IR, so Python <-> MD <-> music all convert through it.
#   stmt := ['let'] NAME '=' expr ';'
#         | NAME ('+='|'-='|'*='|'//='|'%=') expr ';'
#         | 'print' '(' expr ')' ';'
#         | 'if' '(' expr ')' '{' stmt* '}' ('elif' '(' expr ')' '{' stmt* '}')* ['else' '{' stmt* '}']
#         | 'while' '(' expr ')' '{' stmt* '}'
#         | 'for' '(' NAME 'in' 'range' '(' expr [',' expr] ')' ')' '{' stmt* '}'
#   expr := ints, "strings", names, ( ) , unary -, and  + - * // %  <  >  <=  >=  ==  !=
#   comments := '#' to end of line, or '/* ... */'.  ('//' is floor-division, never a comment.)
_MD_KW  = {"let", "if", "elif", "else", "while", "for", "in", "range", "print"}
_MD_OPS = ["//=", "//", "==", "!=", "<=", ">=", "+=", "-=", "*=", "%=",
           "=", "<", ">", "+", "-", "*", "%", "(", ")", "{", "}", ",", ";"]
_MD_ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}

def _md_lex(s):
    i, n, out = 0, len(s), []
    while i < n:
        c = s[i]
        if c in " \t\r\n": i += 1; continue
        if c == "#":
            while i < n and s[i] != "\n": i += 1
            continue
        if c == "/" and i + 1 < n and s[i+1] == "*":
            i += 2
            while i + 1 < n and not (s[i] == "*" and s[i+1] == "/"): i += 1
            i += 2; continue
        if c == '"' or c == "'":
            q, j, buf = c, i + 1, []
            while j < n and s[j] != q:
                if s[j] == "\\" and j + 1 < n: buf.append(_MD_ESC.get(s[j+1], s[j+1])); j += 2
                else: buf.append(s[j]); j += 1
            if j >= n: raise ValueError("MD: unterminated string")
            out.append(("str", "".join(buf))); i = j + 1; continue
        if c.isdigit():
            j = i
            while j < n and s[j].isdigit(): j += 1
            out.append(("num", int(s[i:j]))); i = j; continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (s[j].isalnum() or s[j] == "_"): j += 1
            w = s[i:j]; out.append(("kw" if w in _MD_KW else "name", w)); i = j; continue
        for op in _MD_OPS:
            if s.startswith(op, i): out.append(("op", op)); i += len(op); break
        else: raise ValueError("MD: bad token near %r" % s[i:i+12])
    return out

_MD_PREC = {"<":1,">":1,"<=":1,">=":1,"==":1,"!=":1,"+":2,"-":2,"*":3,"%":3,"//":3}

def _md_parse(toks):
    """recursive-descent -> list of statement AST dicts (same shape the codegen below expects)."""
    pos = [0]
    def peek(o=0):
        k = pos[0] + o
        return toks[k] if k < len(toks) else ("eof", "")
    def nxt(): t = peek(); pos[0] += 1; return t
    def eat(val):
        t = nxt()
        if t[1] != val: raise ValueError("MD: expected %r, got %r" % (val, t[1]))
    def name():
        t = nxt()
        if t[0] != "name": raise ValueError("MD: expected a name, got %r" % (t[1],))
        return t[1]
    def atom():
        t = nxt()
        if t[0] == "num": return {"k": "num", "v": t[1]}
        if t[0] == "str": return {"k": "str", "v": t[1]}
        if t[0] == "name": return {"k": "name", "v": t[1]}
        if t == ("op", "("):
            e = expr(0); eat(")"); return e
        if t == ("op", "-"): return {"k": "neg", "e": atom()}
        raise ValueError("MD: unexpected token %r" % (t[1],))
    def expr(minp):
        left = atom()
        while True:
            t = peek()
            if t[0] == "op" and t[1] in _MD_PREC and _MD_PREC[t[1]] >= minp:
                op = nxt()[1]; right = expr(_MD_PREC[op] + 1)
                left = {"k": "bin", "op": op, "l": left, "r": right}
            else: return left
    def paren_expr(): eat("("); e = expr(0); eat(")"); return e
    def block():
        eat("{"); body = []
        while not (peek() == ("op", "}")):
            if peek()[0] == "eof": raise ValueError("MD: unclosed '{'")
            body.append(statement())
        eat("}"); return body
    def if_stmt():
        nxt()  # 'if' or 'elif'
        test = paren_expr(); body = block(); orelse = []
        if peek() == ("kw", "elif"): orelse = [if_stmt()]
        elif peek() == ("kw", "else"): nxt(); orelse = block()
        return {"t": "if", "test": test, "body": body, "orelse": orelse}
    def for_stmt():
        nxt(); eat("("); var = name()
        if nxt() != ("kw", "in"):    raise ValueError("MD: for expects 'in'")
        if nxt() != ("kw", "range"): raise ValueError("MD: for expects 'range(...)'")
        eat("("); a = expr(0)
        if peek() == ("op", ","): nxt(); start, stop = a, expr(0)
        else: start, stop = {"k": "num", "v": 0}, a
        eat(")"); eat(")")
        return {"t": "for", "var": var, "start": start, "stop": stop, "body": block()}
    def statement():
        t = peek()
        if t == ("kw", "if"):    return if_stmt()
        if t == ("kw", "for"):   return for_stmt()
        if t == ("kw", "while"):
            nxt(); test = paren_expr(); return {"t": "while", "test": test, "body": block()}
        if t == ("kw", "print"):
            nxt(); eat("("); e = expr(0); eat(")"); eat(";"); return {"t": "print", "e": e}
        if t == ("kw", "let"):
            nxt(); nm = name(); eat("="); e = expr(0); eat(";"); return {"t": "assign", "name": nm, "e": e}
        if t[0] == "name":
            nm = nxt()[1]; op = nxt()
            if op == ("op", "="): e = expr(0); eat(";"); return {"t": "assign", "name": nm, "e": e}
            if op[0] == "op" and op[1] in ("+=", "-=", "*=", "//=", "%="):
                e = expr(0); eat(";"); return {"t": "aug", "name": nm, "op": op[1][:-1], "e": e}
            raise ValueError("MD: bad statement after %r (op %r)" % (nm, op[1]))
        raise ValueError("MD: unexpected %r" % (t[1],))
    prog = []
    while peek()[0] != "eof": prog.append(statement())
    return prog

def compile_md(src):
    """MD source -> (opcodes, regs). Emits the identical opcode patterns as compile_python
       (for-loops desugar to while), so the music/decoder/decompiler all behave the same."""
    prog = _md_parse(_md_lex(src))
    regs, code, tmp = {}, [], [0]
    def reg(nm):
        if nm not in regs: regs[nm] = len(regs)
        return regs[nm]
    def newtmp(): tmp[0] += 1; return reg("__t%d" % tmp[0])
    def E(e):
        if   e["k"] == "num":  code.append(("PUSH", e["v"]))
        elif e["k"] == "str":
            for ch in e["v"]: code.append(("PUSH", ord(ch)))
            code.append(("MKSTR", len(e["v"])))
        elif e["k"] == "name": code.append(("LOAD", reg(e["v"])))
        elif e["k"] == "neg":  code.append(("PUSH", 0)); E(e["e"]); code.append(("SUB", None))
        elif e["k"] == "bin":  E(e["l"]); E(e["r"]); code.append((BINOP_SYM.get(e["op"]) or CMPOP_SYM[e["op"]], None))
        else: raise ValueError("MD expr?")
    def B(ss):
        for s in ss: S(s)
    def S(s):
        t = s["t"]
        if   t == "assign": E(s["e"]); code.append(("STORE", reg(s["name"])))
        elif t == "aug":
            r = reg(s["name"]); code.append(("LOAD", r)); E(s["e"]); code.append((BINOP_SYM[s["op"]], None)); code.append(("STORE", r))
        elif t == "print":  E(s["e"]); code.append(("OUT", None))
        elif t == "while":  E(s["test"]); code.append(("WHILE", None)); B(s["body"]); E(s["test"]); code.append(("END", None))
        elif t == "if":
            E(s["test"]); code.append(("IF", None)); B(s["body"])
            if s["orelse"]: code.append(("ELSE", None)); B(s["orelse"])
            code.append(("END", None))
        elif t == "for":
            v = reg(s["var"]); E(s["start"]); code.append(("STORE", v)); et = newtmp(); E(s["stop"]); code.append(("STORE", et))
            code.append(("LOAD", v)); code.append(("LOAD", et)); code.append(("LT", None)); code.append(("WHILE", None))
            B(s["body"])
            code.append(("LOAD", v)); code.append(("PUSH", 1)); code.append(("ADD", None)); code.append(("STORE", v))
            code.append(("LOAD", v)); code.append(("LOAD", et)); code.append(("LT", None)); code.append(("END", None))
        else: raise ValueError("MD stmt?")
    B(prog); return code, regs

# operator symbol -> opcode (shared by MD compiler and both decompilers)
BINOP_SYM = {"+":"ADD","-":"SUB","*":"MUL","%":"MOD","//":"DIV"}
CMPOP_SYM = {"<":"LT",">":"GT","<=":"LE",">=":"GE","==":"EQ","!=":"NE"}

def _md_str(s):
    out = ['"']
    for ch in s:
        out.append({'"': '\\"', "\\": "\\\\", "\n": "\\n", "\t": "\\t", "\r": "\\r"}.get(ch, ch))
    out.append('"'); return "".join(out)

def decompile_md(toks):
    """opcodes -> MD source (the brace/semicolon surface). Mirror of decompile() for Python."""
    pair, opener_of, st = {}, {}, []
    for i, (op, _) in enumerate(toks):
        if op in ("IF", "WHILE"): st.append(i)
        elif op == "ELSE": pair[st[-1]] = i
        elif op == "END": s = st.pop(); pair.setdefault(s, i); opener_of[i] = s
    BIN = {"ADD":"+","SUB":"-","MUL":"*","MOD":"%","DIV":"//"}; CMP = {"LT":"<","GT":">","LE":"<=","GE":">=","EQ":"==","NE":"!="}
    lines, indent, S = [], 0, []
    def put(txt): lines.append("    " * indent + txt)
    ip = 0
    while ip < len(toks):
        op, arg = toks[ip]
        if   op == "PUSH": S.append(str(arg))
        elif op == "LOAD": S.append("v%d" % arg)
        elif op == "MKSTR":
            parts = [S.pop() for _ in range(arg)][::-1]
            try: S.append(_md_str("".join(chr(int(x)) for x in parts)))
            except Exception: S.append("str(%s)" % (parts,))
        elif op == "STORE": put("v%d = %s;" % (arg, _strip(S.pop())))
        elif op in BIN: b, a = S.pop(), S.pop(); S.append("(%s %s %s)" % (a, BIN[op], b))
        elif op in CMP: b, a = S.pop(), S.pop(); S.append("(%s %s %s)" % (a, CMP[op], b))
        elif op == "DUP": S.append(S[-1])
        elif op == "OUT": put("print(%s);" % _strip(S.pop()))
        elif op == "IF": put("if (%s) {" % _strip(S.pop())); indent += 1
        elif op == "ELSE": indent -= 1; put("} else {"); indent += 1
        elif op == "WHILE": put("while (%s) {" % _strip(S.pop())); indent += 1
        elif op == "END":
            indent -= 1
            if toks[opener_of[ip]][0] == "WHILE" and S: S.pop()   # discard the duplicated end-of-loop condition
            put("}")
        ip += 1
    return "\n".join(lines)

# ---- conversions through the opcode IR (both directions, all three surfaces) ----
def python_to_md(src): return decompile_md(compile_python(src)[0])
def md_to_python(src): return decompile(compile_md(src)[0])

# MD versions of the demos (same programs, MD syntax)
MD_DEMOS = {
"counter":  "for (i in range(1, 11)) {\n    print(i);\n}",
"fizzbuzz": ('for (i in range(1, 16)) {\n'
             '    if (i % 15 == 0) { print("FizzBuzz"); }\n'
             '    elif (i % 3 == 0) { print("Fizz"); }\n'
             '    elif (i % 5 == 0) { print("Buzz"); }\n'
             '    else { print(i); }\n}'),
"hello":    'print("Hello, World!");\nprint("Musical " + "Dynamics");',
"fib":      ("let a = 0;\nlet b = 1;\n"
             "for (i in range(10)) {\n    print(a);\n    let c = a + b;\n    a = b;\n    b = c;\n}"),
"primes":   ("for (n in range(2, 30)) {\n    let d = 2;\n    let p = 1;\n"
             "    while (d * d <= n) {\n        if (n % d == 0) { p = 0; }\n        d = d + 1;\n    }\n"
             "    if (p == 1) { print(n); }\n}"),
}

# ================= demos =================
DEMOS={
"fibonacci":"a = 0\nb = 1\nfor i in range(10):\n    print(a)\n    c = a + b\n    a = b\n    b = c",
"counter":"for i in range(1, 11):\n    print(i)",
"fizzbuzz":"for i in range(1, 16):\n    if i % 3 == 0:\n        print(0)\n    else:\n        print(i)",
"nested":"n = 3\nfor i in range(n):\n    for j in range(n):\n        print(i + j)",
"primes":"for n in range(2, 30):\n    d = 2\n    p = 1\n    while d * d <= n:\n        if n % d == 0:\n            p = 0\n        d = d + 1\n    if p == 1:\n        print(n)",
"hello":'print("Hello, World!")',
"fizzwords":'for i in range(1, 16):\n    if i % 15 == 0:\n        print("FizzBuzz")\n    elif i % 3 == 0:\n        print("Fizz")\n    elif i % 5 == 0:\n        print("Buzz")\n    else:\n        print(i)',
"concat":'print("Fizz" + "Buzz")\nprint("MD" + " rocks")',
}
def pyrun(src):
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf): exec(compile(src,"<d>","exec"),{})
    return buf.getvalue().splitlines()                 # compare printed lines (handles int & str)
def as_lines(out): return [str(x) for x in out]

if __name__=="__main__":
    print("quality families: %d opcodes, %d distinct chords, all disjoint ✓\n"%(len(QFAMILY),len(QREV)))
    allok=True
    for name,src in DEMOS.items():
        code,_=compile_python(src); ref=pyrun(src)
        traceops=[(s["op"],s["arg"]) for s in run(code)[1]]
        # ---- SCORE mode: music encodes the static program; recover it EXACTLY, every rendering ----
        pst=[{"op":op,"arg":arg,"iter":0,"val":None} for op,arg in code]
        score_ok=True
        for var in range(4):
          for mode in ("major","pent_minor","whole_tone"):
            notes,_=realize(pst, mode=mode, key=(var*2)%12, climb_step=var%3, octave=var%2, variation=var)
            if decode_notes(notes)!=code: score_ok=False
        score_out = as_lines(run(decode_notes(realize(pst,variation=2)[0]))[0])
        # ---- PERFORMANCE mode: music encodes the execution trace; recover trace, replay for output ----
        _,trace,_=run(code)
        perf_ok=True
        for var in range(4):
          for mode in ("major","pent_minor","whole_tone"):
            notes,_=realize(trace, mode=mode, key=(var*2)%12, climb_step=var%3, octave=var%2, variation=var)
            if decode_notes(notes)!=traceops: perf_ok=False
        perf_out = as_lines(run_trace(decode_notes(realize(trace,variation=1)[0])))
        # ---- decompile the static program -> Python -> run ----
        dsrc=decompile(code); dout=pyrun(dsrc)
        ok = (ref==score_out==perf_out==dout and score_ok and perf_ok); allok&=ok
        print(f"{name:10} ok={ok}  out={ref}")
        print(f"            score: exact-program-recovery(12 renderings)={score_ok}  recovered-output={score_out==ref}")
        print(f"            perf : exact-trace-recovery(12 renderings)={perf_ok}  replayed-output={perf_out==ref}  decompiled-runs={dout==ref}")
    # ---- MD language: compile, decompile, round-trip, and bridge to/from Python ----
    print("\n--- MD language (C/Python-flavored surface over the same opcodes) ---")
    md_ok=True
    for name,src in MD_DEMOS.items():
        code,_=compile_md(src)
        out=as_lines(run(code)[0])
        ref=pyrun(decompile(code))                              # opcodes -> Python -> run
        idem=(compile_md(decompile_md(code))[0]==code)          # MD -> opcodes -> MD -> opcodes is stable
        music=(decode_notes(realize([{"op":op,"arg":arg,"iter":0,"val":None} for op,arg in code],variation=3)[0])==code)
        ok=(out==ref and idem and music); md_ok&=ok
        print(f"  {name:9} ok={ok}  out={out}  (decompile-idempotent={idem}, music-roundtrip={music})")
    # cross-bridge: every Python demo -> MD -> opcodes reproduces the original behavior, and back
    bridge_ok=True
    for name,src in DEMOS.items():
        md=python_to_md(src)
        if run(compile_md(md)[0])[0]!=run(compile_python(src)[0])[0]: bridge_ok=False
        if pyrun(md_to_python(MD_DEMOS["hello"]))!=pyrun("print('Hello, World!')\nprint('Musical '+'Dynamics')"): bridge_ok=False
    print(f"  python<->MD bridge preserves behavior on all {len(DEMOS)} demos: {bridge_ok}")
    # operand encoding now spans far beyond 1727 (covers all Unicode + large literals)
    op_ok=all(dec_operand(enc_operand(v))==v for v in [0,1,127,1727,2000,20013,127925,0x10FFFF,OPERAND_MAX])
    uni="print(\"♪ 中 🎵\");"; uni_code,_=compile_md(uni)
    uni_music=(decode_notes(realize([{"op":op,"arg":arg,"iter":0,"val":None} for op,arg in uni_code],variation=1)[0])==uni_code)
    print(f"  operand enc/dec exact up to {OPERAND_MAX} (incl. emoji/CJK): {op_ok}; unicode prog music-roundtrips: {uni_music}")
    allok &= (md_ok and bridge_ok and op_ok and uni_music)
    # ---- full round trip THROUGH A REAL .mid FILE (score mode -> recover looped Python) ----
    import os, tempfile
    midpath=os.path.join(tempfile.gettempdir(),"md_roundtrip.mid")
    print("\n--- round trip through an actual MIDI file (Hello World, score mode) ---")
    code,_=compile_python(DEMOS["hello"])
    pst=[{"op":op,"arg":arg,"iter":0,"val":None} for op,arg in code]
    notes,_=realize(pst, mode="pent_minor", key=3, octave=0, variation=2)
    write_midi(notes, midpath)
    dec=decode_notes(read_midi(midpath))
    print("opcodes recovered from .mid exactly:", dec==code)
    print("output from decoded MIDI:", run(dec)[0])
    print("recovered Python from the MIDI file:", decompile(dec))
    print("recovered MD from the MIDI file:", repr(decompile_md(dec)))
    print("\nALL PASS:", allok)
