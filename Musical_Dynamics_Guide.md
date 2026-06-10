# Musical Dynamics — User Guide

*A Turing‑complete programming language whose instructions are musical chords. The same
artifact is at once a runnable program and a piece of music, and it translates **both ways**:
Python → music, and music → Python.*

---

## 1. What it is, in one minute

You write a small subset of **Python**. It compiles to a stack‑machine whose **opcodes are
chord qualities** — `PUSH` is one chord, `WHILE` is another, and so on. The program is played
as music, every `print` ringing its value out as a melody. A **decoder** can then listen to
those exact notes and reconstruct the program — its output *and* its source code.

Two principles hold throughout:

- **One program → many performances.** The same program can sound countless ways (key, scale,
  tempo, voicing…). These are *compositional choices you make*, never randomness.
- **One performance → one meaning.** Any given set of notes decodes to exactly one result.
  The decoder is **deterministic** and is invariant to every compositional choice above.

Two ways to run the player. The original zero-install demo is the single HTML file
**`index.html`** — no server, no install, just double-click it. The redesigned Vite app lives
in **`web/`** (`cd web && npm install && npm run dev` → http://localhost:5173) and adds a
file-in-WAV stego UI and MIDI/MusicXML/WAV exports.

---

## 2. Quick start (the player)

1. Open `index.html` in a browser.
2. Section **①** has a Python editor. Press **▶ run & play**. You'll hear the program and see
   its output.
3. Try the **demo** dropdown: Fibonacci, Counter, FizzBuzz, Nested loops, Primes,
   **Hello World (strings)**, **FizzBuzz (words)**.
4. Change anything in section **②** (scale, key, tempo, variation…) and play again — same
   output, different music.
5. Watch section **③**: the decoder reconstructs the program from the notes and shows a
   **round‑trip‑verified ✓** badge.

---

## 3. The language

### 3.1 Supported Python

| Feature | Examples |
|---|---|
| Integer & string literals | `42`, `"hello"` |
| Variables | `x = 5` |
| Assignment / augmented | `x = 1`, `x += 2`, `x *= 3`, `x //= 2`, `x %= 4` |
| Arithmetic | `+  -  *  //  %` (integer) |
| String concatenation | `"a" + "b"`, `"Count: " + s` |
| Comparison | `<  >  <=  >=  ==  !=` |
| Conditionals | `if … : / elif … : / else :` |
| Loops | `while … :` and `for v in range(a, b):` |
| Output | `print(<int or str expr>)` |

Strings compile to one `PUSH` per character plus a `MKSTR` opcode that assembles them, so a
string literal is a little flurry of chords followed by a "make‑string" chord. Concatenating
strings uses the same `+` as integer addition (the VM concatenates when the operands are
strings).

### 3.2 Boolean operators (`and` / `or` / `not`)

Supported in **both** the Python subset and MD. They **short‑circuit** and desugar to existing
`IF`/`ELSE` opcodes (no new opcodes, so the music round-trip guarantee is preserved):

```python
if (x and y):     print(1)           # b is not evaluated when x is falsy
if (x or  y):     print(1)
if (not x):       print(1)
if (a > 0 and a < 10): print(1)      # works with comparisons; precedence: not > and > or
```

### 3.3 Not supported (yet)

Functions/`def`, lists/dicts/tuples, floats, f‑strings, multiple `print` arguments, imports,
comparison chaining (`a < b < c`). `for` desugars to a `while` with a counter, so decompiled
code shows the `while` form.

### 3.4 The MD language — same opcodes, C/Python‑flavored surface

`mc_codec.compile_md` parses a brace‑and‑semicolon surface that compiles to the **identical**
opcodes as the Python compiler — so Python ↔ MD ↔ music are all conversions through the same
IR. Errors carry line/column info via `MDSyntaxError`.

```c
// FizzBuzz, in MD
for (i in range(1, 16)) {
    if      (i % 15 == 0) { print("FizzBuzz"); }
    elif    (i % 3  == 0) { print("Fizz");     }
    elif    (i % 5  == 0) { print("Buzz");     }
    else                  { print(i);          }
}

let x = 1;                                    // 'let' is optional; `x = 1;` also works
let y = 0;
if (x and y) { print(1); }                   // boolean and / or / not
elif (not y) { print(0); }
```

Bridges through the IR are one call:

```python
mc_codec.python_to_md(src)   # Python source -> MD source (via opcodes)
mc_codec.md_to_python(src)   # MD source -> Python source (via opcodes)
```

### 3.5 Hello, World!

```python
print("Hello, World!")
print("Musical " + "Dynamics")
```

### 3.6 FizzBuzz with words

```python
for i in range(1, 16):
    if i % 15 == 0:
        print("FizzBuzz")
    elif i % 3 == 0:
        print("Fizz")
    elif i % 5 == 0:
        print("Buzz")
    else:
        print(i)
```

---

## 4. How the music encodes the program

### 4.1 Opcodes → chord families (the redundancy)

There are 21 opcodes: `PUSH LOAD STORE MKSTR ADD SUB MUL DIV MOD EQ NE LT GT LE GE IF ELSE
WHILE END OUT DUP`. Each opcode owns a **family** of one or more distinct chord qualities
(27 chords in total, all provably distinct). When encoding, you (or the tool) pick which
family member to voice; when decoding, every chord maps back to exactly one opcode. That is
the legitimate redundancy: the *same instruction can sound several ways*.

The chord **quality** is read as the set of intervals **above the bass**, and the bass is
always the chord's root (no inversions move it). That is why the decoder doesn't care about
octave, register, key, or how the chord is spread — transposition and voicing don't change the
intervals.

### 4.2 Operands → a fixed "data register"

`PUSH`, `LOAD`, `STORE`, and `MKSTR` carry a number (a literal, a variable index, or a string
length). It is written **losslessly** as **base‑12 digits on a fixed set of pitches** (one
octave band per digit, starting low so every band stays within MIDI 0–127), where each digit's
octave band encodes its position. These operand notes are **never transposed** by
key/octave/climb, so they're recovered exactly. The range is **0–429,981,695** per operand
(12⁸−1), which covers **every Unicode code point** (so any character — CJK, emoji — is fine),
variable indices, and string lengths. Larger integer literals are built with arithmetic
(e.g. `100 * 100`).

### 4.3 Two encoding modes

- **Score** — the music encodes the **static program**; loops play once. Decoding gives your
  looped source back cleanly. This is the round trip Python → music → Python.
- **Performance** — the music encodes the **execution trace**; the loop body repeats and
  *climbs* a few scale‑steps each pass (you hear the computation unfold). Decoding recovers the
  exact execution and replaying it reproduces the output. Note: a performance
  **under‑determines** the looped source (many programs share one trace), so it decompiles to
  the unrolled, straight‑line version.

### 4.4 Determinism

The output is fixed by the program alone. The realization controls (mode, key, octave, climb,
tempo, feel, melody map, timbre, **variation**) only change how it sounds. "Variation" is a
deterministic selector over chord‑family choices and voicings — pick the same number and you
get the identical performance. There is no randomness anywhere in the system.

---

## 5. The decoder (music → code)

Section **③** of the player decodes the notes you just heard:

1. Cluster notes by onset. The chord (channel 0) gives the opcode via *intervals above the
   bass → quality → opcode*. The operand notes (channel 1, fixed register) give the number.
   The bass‑doubling channel is ignored.
2. The recovered opcodes are run (score mode) or replayed (performance mode) to get the output.
3. The opcodes are decompiled back to Python.

The **round‑trip‑verified ✓** badge confirms that the decoded opcodes match what was encoded
and that the decoded output matches the direct output. Because decoding only reads
bass‑relative intervals and a fixed operand register, it is identical across every key, scale,
octave, climb, tempo, feel, and variation.

---

## 6. Realization controls (section ②)

| Control | Effect (sound only) |
|---|---|
| **encoding** | score (reversible to source) vs performance (hear it run) |
| **scale / mode** | major, minor, the church modes, two pentatonics, whole‑tone |
| **key** | transposes everything |
| **octave** | shifts register |
| **loop climb** | how many scale‑steps each loop pass rises (performance mode) |
| **tempo** | playback speed |
| **feel** | straight / swing / staccato / legato |
| **melody map** | how each printed value maps to a pitch (ladder / compact / chromatic / pulse) — decorative; the real value is recovered by running, not by pitch |
| **sound style** | a full instrument-and-effects preset: Warm Keys, Crystalline, Chiptune, Cinematic, Jazz Club, Lo-fi, Music Box, Cathedral, Classic. Each gives every **construct category** (data / memory / math / control / i-o) its own voice — so you *hear* the program's structure — plus its own reverb / chorus / delay / filter and musical defaults (mode, feel, tempo, melody) that you can still override |
| **variation** | deterministic choice of chord voicings (press **next** to step through) |

None of these change the program's output or the decoder's result. The synth is a multi-voice
engine (layered oscillators, ADSR, per-voice filter envelopes, convolution reverb + chorus +
delay) but it only changes *how* each note sounds — the note set fed to the decoder is identical,
verified across **1728 renderings** spanning every style's mode/feel/octave/variation (0 decode
failures).

---

## 7. Visual programming — "program by ear" (section ④)

Instead of writing Python, you can **compose** a program from a palette of chord‑bricks, one
per opcode, grouped by role (data, memory, math, compare, control, i/o). 

- Click a brick to append it; you hear that chord immediately.
- For `PUSH`/`LOAD`/`STORE`, set the **operand** number first.
- The panel shows the growing opcode sequence, whether it is a valid/complete program, its
  output if it runs, and a best‑effort Python reconstruction.
- **▶ play sequence** plays the whole thing; **remove last** / **clear** edit it.

### The validity toggle

**"only allow valid program steps"** (on by default) greys out any brick that would break the
program — you can't add `END` with no open block, can't add a second `ELSE`, can't add an
operator without enough values on the stack. Every brick you place keeps the program valid and
completable. Turn it off and anything goes; the panel then *reports* what's wrong (e.g.
`stack underflow at ADD`, `1 unclosed block(s)`) instead of preventing it.

---

## 8. Steganography — hide arbitrary files in music

### 8.1 The full framework (`stego/` package)

A general file-in-music steganography toolkit, separable from the language core. Hide
**arbitrary files** (any bytes — text, JPEG, ZIP, an executable) inside any music file. Several
carriers, all sharing one **format‑independent payload pipeline** so the redundancy and
fail‑safe guarantees are uniform:

| Carrier | Capacity (per minute of audio) | Survives lossy re‑encode |
|---|---|---|
| WAV / FLAC / AIFF — **uniform** (LSB matching, ±1 sample) | ~1.6 MB at 1 bit-plane | n/a (bit‑exact) |
| WAV / FLAC / AIFF — **adaptive** (psychoacoustic per‑sample bit-allocation) | up to ~6 MB on loud audio (4× uniform), masked | n/a (bit‑exact) |
| Speech WAV — **adaptive + voice-activity gate** | tracks the speech; silence left untouched | n/a (bit‑exact) |
| MP3 / AAC / Ogg (spread‑spectrum watermark in mid-band FFT) | ~300 B | **yes** — verified through MP3+MP3 double encode |
| MIDI (low bits of note‑on velocities) | ~750 B at 2 bits/note (3000-note track) | yes (re-export) |
| MD‑native (variation/voicing bits the decoder *ignores*) | ~10–20 B per program | yes — *the music **is** the program* |

The pipeline is `frame(name+len+CRC) → optional zlib → optional AES‑256‑GCM → LT fountain
code → per‑symbol Reed‑Solomon + CRC`. Header is replicated and spread across the whole
carrier; body symbols are cell‑spread, so a localized overwrite erases a *proportional* set of
whole symbols which the fountain rebuilds from any K′≈K survivors. Decode is fail‑safe — header
CRC, per‑symbol CRC, and final payload CRC must all pass, or it **refuses** rather than
returning corrupted bytes.

#### Adaptive (psychoacoustic) embedding — `--adaptive`

Instead of a fixed bit-depth everywhere, the adaptive carrier allocates a **per‑sample bit-depth
from the local signal energy**: loud passages hide up to 4 bits (masked by the signal), quiet
ones hide fewer or none. The allocation is derived from the bits **at or above** the embedding
boundary (which embedding never touches), so the decoder recomputes it blind — no side channel.
Versus fixed 1‑LSB this gives **~4× the capacity** on loud audio, keeps the embedding noise
provably below `local‑signal / 32` (masked, not a constant hiss), and — since the data is spread
across bit-planes 0..k−1 — **survives LSB‑plane stripping** (zeroing the lowest plane loses only
~25% of the slots; the fountain rebuilds the rest). The `speech` profile adds a **voice‑activity
gate** so silence is left byte‑identical and the speech stays natural and intelligible.

#### General CLI (WAV/FLAC/AIFF/MP3/AAC/Ogg/MIDI)

```bash
python3 -m stego embed   carrier.wav secret.zip -o stego.wav --redundancy 4 --password hunter2
python3 -m stego embed   song.flac   secret.zip --adaptive                 # 4x capacity, masked
python3 -m stego embed   voice.wav   note.txt   --adaptive --profile speech # speech-safe (skips silence)
python3 -m stego extract stego.wav -o ./out --password hunter2             # auto-detects the method
python3 -m stego capacity carrier.wav [--adaptive [--profile speech]]
```

#### MD‑native CLI (no PCM tampering — the produced MIDI is just *a different arrangement*)

```bash
python3 -m stego.md_native embed   program.md secret.bin -o stego.mid [--password] [--repetition 3]
python3 -m stego.md_native extract stego.mid  -o ./out                [--password] [--repetition 3]
python3 -m stego.md_native capacity program.md
```

The native channel's headline guarantee: the produced MIDI **still decodes to the same program
and runs to the same output**. The hidden bits ride entirely in the variation/voicing the
decoder is provably blind to.

#### Selftest demo

```bash
python3 -m stego.selftest
```

Shows WAV/FLAC bit‑exact round-trip, recovery under 0.5–2% scattered LSB noise, recovery under
30/60/80% contiguous overwrite, AES‑GCM with wrong‑password rejection, and (with PyAV
installed) MP3 single + double encode survival.

#### Cross‑decodable with the browser

The Python and JS implementations share one MDX1 wire format (same mulberry32 PRNG, same
CRC‑16/CRC‑32, same fountain seeding). A stego WAV embedded by `python3 -m stego embed`
extracts in the browser's "extract" panel (and vice versa). Verified by Node tests in both
directions.

### 8.2 The original LSB demo in the v6 player (section ⑤)

`mc_stego.py` is the original side feature: text or a JPEG hidden in the LSB of 16‑bit
samples, with a fixed‑R repetition + interleave + CRC scheme. The change is about **−96 dBFS**
(one part in 65,536). Run `python3 mc_stego.py` for its demo (text + JPEG round-trip, error
correction under random and burst corruption, on-disk WAV round-trip). The included
`carrier_stego.wav` sounds like a four-chord pad but contains a complete hidden JPEG.

Superseded by `stego/` for new work — but the API is still there for backwards compatibility.

---

## 9. The Python tools

### `mc_codec.py` — the language and music codec
Both compilers (Python‑subset → opcodes, **MD → opcodes**), the looping VM and straight‑line
trace VM, the deterministic realizer, the **decoder**, the **decompiler** (opcodes → Python or
MD), the Python ↔ MD bridges (`python_to_md`, `md_to_python`), and MIDI read/write. Run it to
exercise the full self-test — every demo round-trips through encode → decode (across many
renderings each), through a real `.mid` file, through the MD language, and through the Python
↔ MD bridge:

```bash
python3 mc_codec.py
```

### `mc_song_to_md.py` — turn any MIDI into the closest valid MD program
Clusters chords by onset, scores them by Jaccard distance over pitch-class sets to find the
nearest opcode, then **beam-searches** through the validity engine (same `POPS`/`PUSHN` tables
the visual composer uses) to repair the stream into a balanced, runnable MD program. Reports
fidelity ∈ [0, 1].

```bash
python3 mc_song_to_md.py path/to/song.mid                 # prints MD + fidelity
python3 mc_song_to_md.py path/to/song.mid --show-opcodes  # also dumps the opcode stream
python3 mc_song_to_md.py path/to/song.mid -o out.md       # write to file
```

### `stego/` — file-in-music steganography
See §8.1 above. CLIs: `python3 -m stego` (general carriers) and `python3 -m stego.md_native`
(native channel).

### `mc_stego.py` — the legacy LSB side feature
See §8.2 above. `python3 mc_stego.py` runs its built-in demo.

### The pytest suite
140 tests across the codec, language, all four stego carriers, the native channel, and the
song-to-MD prototype. Public-domain payload fixtures (US Constitution preamble, Shakespeare's
Sonnet 18, Poe's "The Raven", *Alice in Wonderland* via Project Gutenberg). Run with:

```bash
python3 -m pytest tests/                   # 140 tests, ~70s
cd web && npm test                          # 9 JS tests (incl. Python <-> JS cross-decode)
```

**Dependencies** (or just run `./setup.sh` / `setup.bat`):
`numpy mido pillow soundfile cryptography reedsolo av pytest`. `av` (PyAV) is optional —
without it, MP3/AAC/Ogg stego is disabled but everything else still works.

### `web/` — the redesigned Vite app
Browser player + **file-in-WAV stego UI** + MIDI / MusicXML / rendered WAV exports. Modular
ES-module port of the codec under `web/src/codec/`; stego pipeline at `web/src/stego/`
byte-compatible with Python. Run with:

```bash
cd web && npm install && npm run dev    # http://localhost:5173
cd web && npm run build                  # static build to web/dist/ (for GitHub Pages)
```

---

## 10. Worked examples and expected output

| Program | Output |
|---|---|
| `print("Hello, World!")` | `Hello, World!` |
| Fibonacci (10 terms) | `0 1 1 2 3 5 8 13 21 34` |
| `for i in range(1,11): print(i)` | `1 … 10` |
| FizzBuzz (words, 1–15) | `1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz` |
| Primes < 30 | `2 3 5 7 11 13 17 19 23 29` |
| `print("Fizz" + "Buzz")` | `FizzBuzz` |

---

## 11. Limitations & notes

- The language is a deliberately small, integer/string subset of Python (see §3.2).
- `for` loops decompile back to `while` loops (they are compiled that way); the behavior is
  identical, the surface form differs.
- A single operand literal is limited to 0–429,981,695 (12⁸−1); build larger constants arithmetically.
- In **performance** mode, decoded source is the unrolled execution (loops are not re‑rolled).
- The steganography is robust in proportion to the carrier's spare capacity: a longer piece
  tolerates more corruption. It always **fails safe** (detect‑and‑refuse) rather than returning
  corrupted data.
- Audio uses the Web Audio API; some browsers require a click before sound will play.

---

*Musical Dynamics — write a program, hear it, and read it back out of the music.*
