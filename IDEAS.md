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

- ✅ **Exporters**: MIDI (.mid), rendered **WAV** (offline Web Audio render), and
  **MusicXML/score** — same notes, different containers. (`web/src/audio/midi.js`,
  `web/src/audio/musicxml.js`, `web/src/audio/synth.js`)
- 💡 **ABC / LilyPond** for engraved sheet music; **JSON note-list** for diffing/debugging.
- 💡 **Step-debugger / teaching mode**: highlight the chord as each opcode executes; scrub the
  piano-roll and watch the stack/regs update. Great for "see the program *as* music."

## 3. Steganography 🎯#6

- ✅ **Lossless audio (WAV/FLAC/AIFF)** carrier with fountain-coded redundancy, optional
  AES-GCM, and a fail-safe verify-and-refuse decoder. (`stego/carriers/pcm.py`)
- ✅ **MP3/AAC/Ogg watermark** via spread-spectrum DSSS in the mid-band of overlap-add STFT
  frames. Survives *double* MP3 encoding generations. (`stego/carriers/mp3.py`)
- ✅ **MIDI carrier**: hide bits in low bits of note-on velocities, n_lsb=2 is inaudible (max
  velocity delta = 3) and gives ~750 B per 3000-note track. (`stego/carriers/midi.py`)
- ✅ **MD-native compositional channel** — the elegant one. The decoder is provably blind to
  *variation, voicing, key, octave* (and, in performance mode, *mode/climb*). The **choice of
  performance** carries a hidden message while the notes still decode to the identical program.
  No sample tampering at all. Per-program capacity ~10–20 bytes. (`stego/md_native.py`)
- ✅ **Browser mirror**: in-app file embed/extract for the lossless WAV path. Same MDX1 wire
  format as Python (mulberry32 PRNG, fountain code, CRC-16/CRC-32 all byte-identical). Verified
  cross-decode in both directions under Node. (`web/src/stego/`)

## 4. Song → closest viable program 🎯#6

✅ Shipped as `mc_song_to_md.py`. Turns an arbitrary MIDI into the nearest valid MD program:

1. Clusters MIDI events by onset into chords (filters MD's operand/bass channels when present).
2. Maps each chord to its nearest opcode by Jaccard distance over pitch-class sets.
3. Runs a small **beam search** that keeps the partial program valid (stack non-negative, blocks
   balanced) — reusing the same validity engine the visual composer uses.
4. Closes any open blocks with `END`s and emits MD source + fidelity score in [0,1].

Run on the MD-generated `roundtrip.mid` (Hello World), it recovers fidelity = 1.0 — meaning
every chord matched a `QFAMILY` member exactly. Run on a random C-major progression, it
matches at 1.0 too (chords look like opcode signatures) but produces no `print()` (the song
didn't suggest any output): an honest "balanced but silent" program.

The next step is making the song → program → music round-trip *listenable* — letting users
hear how close their song was to being a program.

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
