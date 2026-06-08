"""
mc_song_to_md — turn any musical piece into the closest VALID Musical Dynamics program.

Given an arbitrary MIDI file (or any pitch-tracked notes), this finds the MD opcode sequence
whose realization is closest to the original music. It's the inverse direction of the codec:
the codec is exact (one music -> one program); this is approximate (one song -> the nearest
valid program by chord-interval distance).

Pipeline:
  1. Cluster MIDI events by onset into chords.
  2. Map each chord to an opcode by interval-set distance (intersect-over-union, with a tie-
     breaker on family-member specificity).
  3. The raw nearest-opcode stream is almost never a valid program: stack underflows, IF/END
     mismatches, etc. So a small *beam search* repairs it into a balanced, runnable sequence —
     reusing the same validity engine the visual composer uses (POPS/PUSHN tables).
  4. Emit the result as MD source (via decompile_md) plus a 'fidelity' score:
     fidelity = 1 - mean(chord_distance) over kept events.

Run it:
    python mc_song_to_md.py path/to/song.mid          # prints MD source + fidelity
    python mc_song_to_md.py path/to/song.mid -o out.md
"""
import argparse, sys, math
from mc_codec import (
    QFAMILY, HAS_ARG, decompile_md, decompile, compile_python, realize, write_midi, read_midi,
)

# ---------- validity engine (mirrors index.html `simulate`/`legalNext`) ----------
POPS  = {"PUSH":0,"LOAD":0,"STORE":1,"ADD":2,"SUB":2,"MUL":2,"DIV":2,"MOD":2,
         "EQ":2,"NE":2,"LT":2,"GT":2,"LE":2,"GE":2,"OUT":1,"DUP":1,"IF":1,"WHILE":1,
         "ELSE":0,"END":0,"MKSTR":1}        # MKSTR's real arg is variable; treat as 1 for now
PUSHN = {"PUSH":1,"LOAD":1,"STORE":0,"ADD":1,"SUB":1,"MUL":1,"DIV":1,"MOD":1,
         "EQ":1,"NE":1,"LT":1,"GT":1,"LE":1,"GE":1,"OUT":0,"DUP":2,"IF":0,"WHILE":0,
         "ELSE":0,"END":0,"MKSTR":1}

def _check(seq):
    """(depth, open_ctrl_stack, bad_reason) for a partial opcode sequence."""
    depth, ctrl = 0, []
    for op, arg in seq:
        if op == "ELSE":
            if not ctrl or ctrl[-1][0] != "if" or ctrl[-1][1]:
                return depth, ctrl, "ELSE without open IF"
            ctrl[-1] = ("if", True)
        elif op == "END":
            if not ctrl: return depth, ctrl, "END with no open block"
            ctrl.pop()
        pops   = POPS[op]
        pushes = PUSHN[op]
        if depth < pops: return depth, ctrl, "stack underflow at " + op
        depth += pushes - pops
        if op == "IF":    ctrl.append(("if", False))
        if op == "WHILE": ctrl.append(("while", False))
    return depth, ctrl, None


# ---------- nearest-opcode scoring ----------
def _signature(chord):
    """Tuple of pitch-classes above the bass. `chord` is an iterable of MIDI pitches."""
    if not chord: return ()
    root = min(chord)
    return tuple(sorted({(p - root) % 12 for p in chord}))

def _intervals(q):
    return tuple(sorted({x % 12 for x in q}))

def _distance(sig, q):
    """1 - Jaccard between observed pitch-class set and a family member's interval set."""
    a, b = set(sig), set(_intervals(q))
    if not a and not b: return 0.0
    return 1.0 - len(a & b) / max(1, len(a | b))

def _candidates(sig, k=5):
    """Top-k opcodes (with the family member used) for this chord signature, lowest distance first."""
    scored = []
    for op, fam in QFAMILY.items():
        d = min(_distance(sig, q) for q in fam)
        scored.append((d, op))
    scored.sort()
    return scored[:k]


# ---------- group MIDI events by onset (chord clustering) ----------
def chords_from_midi(path, tick_tolerance=10):
    """Returns a list of (onset_ticks, [pitches]) chord events.

    If the file follows MD's channel convention (ch0=chord, ch1=operand, ch2=bass), only ch0 is
    clustered. Otherwise (arbitrary input music) all channels are clustered together."""
    notes = read_midi(path)
    has_md_channels = any(n.ch in (1, 2) for n in notes)
    by_onset = {}
    for n in notes:
        if has_md_channels and n.ch != 0: continue
        key = round(n.start / 0.005)        # ~5ms bucket
        by_onset.setdefault(key, {"t": n.start, "ps": []})
        by_onset[key]["ps"].append(n.pitch)
    return [(int(x["t"] * 1000), x["ps"]) for x in sorted(by_onset.values(), key=lambda x: x["t"])]


# ---------- beam search to repair an opcode stream into a valid program ----------
def repair_to_valid(chord_events, beam_width=8, max_per_chord=4):
    """For each chord, pick from its top-k nearest opcodes the one that keeps the partial program
       valid (stack non-negative, blocks balanced). Beam-search keeps the best `beam_width`
       prefixes by cumulative chord-distance. Adds final END's to close any open blocks."""
    Beam = []        # list of (cum_distance, opcodes, depth, ctrl)
    Beam.append((0.0, [], 0, []))
    for ticks, ps in chord_events:
        sig = _signature(ps)
        cands = _candidates(sig, k=max_per_chord)
        next_beam = []
        for cum, seq, depth, ctrl in Beam:
            for d, op in cands:
                # quick eligibility check before deep-copying
                if op == "ELSE" and (not ctrl or ctrl[-1][0] != "if" or ctrl[-1][1]): continue
                if op == "END"  and not ctrl: continue
                if depth < POPS[op]: continue
                new_seq = seq + [(op, 0 if op in HAS_ARG else None)]
                _, _, bad = _check(new_seq)
                if bad: continue
                # update depth/ctrl incrementally (mirrors _check but cheaper)
                ndepth = depth + PUSHN[op] - POPS[op]
                nctrl = list(ctrl)
                if op == "ELSE": nctrl[-1] = ("if", True)
                if op == "END":  nctrl.pop()
                if op == "IF":   nctrl.append(("if", False))
                if op == "WHILE":nctrl.append(("while", False))
                next_beam.append((cum + d, new_seq, ndepth, nctrl))
        if not next_beam:
            continue                                     # this chord couldn't extend any beam
        next_beam.sort(key=lambda x: x[0])
        Beam = next_beam[:beam_width]
    # close any open blocks with END (and an ELSE if needed before END inside an IF without else)
    best = min(Beam, key=lambda x: x[0]) if Beam else (math.inf, [], 0, [])
    cum, seq, depth, ctrl = best
    while ctrl:
        seq.append(("END", None))
        ctrl.pop()
    return cum, seq


# ---------- public API ----------
def song_to_md(midi_path, beam_width=8):
    """midi_path -> (md_source, opcodes, fidelity_0_to_1, n_events_used)."""
    events = chords_from_midi(midi_path)
    if not events: raise ValueError("no chord events found in " + midi_path)
    total_dist, opcodes = repair_to_valid(events, beam_width=beam_width)
    n = max(1, len(opcodes))
    fidelity = 1.0 - (total_dist / n)
    md_src = decompile_md(opcodes)
    return md_src, opcodes, fidelity, len(events)


# ---------- CLI ----------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Find the closest valid MD program for a MIDI song.")
    ap.add_argument("midi", help="input MIDI file")
    ap.add_argument("-o", "--out", help="write MD source to this file (default: stdout)")
    ap.add_argument("--beam", type=int, default=8, help="beam width (default 8)")
    ap.add_argument("--show-opcodes", action="store_true", help="also print the opcode stream")
    a = ap.parse_args(argv)
    md, opcodes, fidelity, n = song_to_md(a.midi, beam_width=a.beam)
    print(f"// closest viable MD program for {a.midi}", file=sys.stderr)
    n_out = sum(1 for op, _ in opcodes if op == "OUT")
    print(f"// chord events: {n}    opcodes: {len(opcodes)}    fidelity: {fidelity:.3f}    "
          f"print() statements: {n_out}", file=sys.stderr)
    if n_out == 0:
        print("// note: the chords didn't suggest any print() output; the program is a balanced "
              "but silent computation.", file=sys.stderr)
    if a.show_opcodes:
        print("// opcodes:", file=sys.stderr)
        for i, (op, arg) in enumerate(opcodes):
            print(f"//   {i:3}  {op:<6}  {arg if arg is not None else ''}", file=sys.stderr)
    text = md or "// (no opcodes produced)"
    if a.out:
        with open(a.out, "w") as f: f.write(text + "\n")
        print(f"wrote {a.out}", file=sys.stderr)
    else:
        print(text)

if __name__ == "__main__":
    main()
