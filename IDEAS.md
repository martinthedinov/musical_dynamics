# Musical Dynamics — ways to manipulate and use the MD language

A running idea-book for the project. The bedrock guarantee never changes: **one program → many
performances, but any given set of notes → exactly one program.** Everything below either adds a
new *surface* for authoring/reading MD, or exploits the *degrees of freedom the decoder ignores*.

Legend: ✅ shipped · 🔮 next/planned · 💡 idea · 🎯 maps to a numbered request.

---

## 1. Authoring surfaces (write MD more ways)

- ✅ **Python subset** front-end (`compile_python`) and ✅ **MD** front-end (`compile_md`) — both
  emit the same opcode IR, so all conversions go through one place. 🎯#2/#5
- 🔮 **Two-way text sync**: edit Python *or* MD and see the other regenerate live (both are just
  `decompile`/`decompile_md` of the shared opcodes).
- ✅ **Visual block editor** ("program by ear") — keep it, and 💡 bind it to the MD text so blocks
  ⇄ text stay in sync; greyed bricks already enforce validity.
- 💡 **MIDI-controller authoring**: play chords on a MIDI keyboard → live-decode to opcodes →
  build a program by performance. The validity engine highlights only legal next chords.
- 💡 **Shareable URLs**: pack `{md, mode, key, octave, climb, tempo, variation}` into the URL hash
  so a "song-program" opens exactly as composed — deterministic, so the link *is* the piece.

## 2. Output surfaces (read MD more ways) 🎯#3

- 🔮 **Exporters**: MIDI (.mid), rendered **WAV**, and **MusicXML/score** — same notes, different
  containers. Decoder is invariant, so every export round-trips back to the one program.
- 💡 **ABC / LilyPond** for engraved sheet music; **JSON note-list** for diffing/debugging.
- 💡 **Step-debugger / teaching mode**: highlight the chord as each opcode executes; scrub the
  piano-roll and watch the stack/regs update. Great for "see the program *as* music."

## 3. Steganography 🎯#6

- 🔮 **Fix the LSB channel** (the existing side feature): unify the interleave PRNG and channel
  convention so Python- and JS-embedded WAVs are mutually decodable.
- 💡 **Native "compositional" steganography** — the elegant one. The decoder is provably blind to
  *variation, voicing, key, octave* (and, in performance mode, *mode/climb*). A single program has
  hundreds–thousands of equivalent performances, so the **choice of performance carries a hidden
  message** while the notes still decode to the identical program. No sample tampering at all.
  - Per-instruction budget ≈ `log2(family_size × voicing_combos)` bits; a long program hides a
    short message purely in *how it's voiced*.
  - Decode: re-derive each instruction's chosen family-member/voicing index from the notes (the
    same data the decoder already reads, just not *discarded*), concatenate to bytes, CRC-check.
  - Bonus: completely lossless and inaudible-by-construction (it's "just a different arrangement"),
    and survives transposition because the *relative* choice is what's read.

## 4. Song → closest viable program 🎯#6

Turn an existing piece into the nearest MD program it "almost is":

1. **Ingest** a MIDI (or pitch-tracked audio) → note events.
2. **Cluster** by onset into chords; read **intervals above the bass** → nearest opcode by
   minimum interval-set distance (Hamming/Jaccard over pitch-classes); read the fixed operand
   register if present.
3. **Repair to validity**: a raw nearest-opcode stream rarely type-checks, so run a small
   **beam search** that keeps the stack non-negative and blocks balanced (reuse the existing
   `simulate`/`legalNext` validity engine as the constraint), minimizing total chord-distance.
4. **Emit** the resulting MD + a "fidelity" score (how far the song had to bend to become a
   program). Play the *repaired* version back so you can hear the difference.

This makes the language a lens: any song has a closest computer program, and you can hear how
close it was.

## 5. Search / generative uses

- 💡 **Target-melody synthesis**: given a melody, search realization params (and, in perf mode,
  loop-climb) for the rendering whose pitch contour best matches it — same program, on-purpose tune.
- 💡 **Evolve programs**: genetic search over MD whose performance minimizes audio distance to a
  target — "find a program that sounds like this."
- 💡 **Quines & self-describing songs**: a program whose printed output *is* its own MD source —
  a song that sings its own code.
- 💡 **Diff two songs as programs**: decode both, diff the opcodes/MD — semantic comparison of music.

## 6. Language growth (stay minimal, stay Turing-complete) 🎯#5

- Current MD is intentionally tiny: ints/strings, `+ - * // %`, comparisons, `if/elif/else`,
  `while`, `for…range`, `print`, `let`/assignment/augmented-assignment. That's already
  Turing-complete (unbounded `while` + integer state).
- 💡 Optional sugar that still compiles to today's opcodes: `do { } while(...)`, `break`/`continue`
  (as structured jumps), C-style `for(init; cond; step)`. Each must remain losslessly
  decompilable from the music, or it isn't real MD.
- 💡 Functions (`def`/inline) are the big leap — only worth it if calls/returns get opcodes that
  preserve the one-music-one-program guarantee.

---

*Add freely. The test for any feature: does the music still decode to exactly one program?*
