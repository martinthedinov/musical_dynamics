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

Everything runs in a single HTML file — **`musical_dynamics_v6.html`** — with no server or
install. Open it in a browser.

---

## 2. Quick start (the player)

1. Open `musical_dynamics_v6.html`.
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

### 3.2 Not supported (yet)

Functions/`def`, lists/dicts/tuples, `and`/`or`/`not`, floats, f‑strings, multiple `print`
arguments, imports, comparison chaining (`a < b < c`). `for` desugars to a `while` with a
counter, so decompiled code shows the `while` form.

### 3.3 Hello, World!

```python
print("Hello, World!")
print("Musical " + "Dynamics")
```

### 3.4 FizzBuzz with words

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
length). It is written **losslessly** as **base‑12 digits on a fixed set of pitches** (1–3
notes starting at MIDI 84), where each digit's octave band encodes its position. These operand
notes are **never transposed** by key/octave/climb, so they're recovered exactly. The range is
0–1727 per operand, which covers character codes (≤127), variable indices, and string lengths.
Larger integer literals are built with arithmetic (e.g. `100 * 100`).

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
| **timbre** | oscillator flavor |
| **variation** | deterministic choice of chord voicings (press **next** to step through) |

None of these change the program's output or the decoder's result.

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

## 8. Steganography — hide data in the audio (section ⑤, **side feature**)

This is a separate utility, unrelated to the language core. It hides arbitrary bytes — a text
message or a whole **JPEG** — inside an existing piece by toggling the **least‑significant bit**
of 16‑bit audio samples. The change is about **−96 dBFS** (one part in 65,536): inaudible to a
person, exactly recoverable by software.

Robustness is layered:

- a fixed‑size, fixed‑redundancy **header** so the decoder bootstraps with no side channel;
- the payload **repetition‑coded** and **pseudo‑randomly interleaved** across the carrier, so
  bursts and periodic noise are spread over many copies (corrects up to ⌊R/2⌋ flips per bit);
- a **CRC‑32** integrity check that detects any residual corruption and *refuses* rather than
  returning silent‑wrong data.

In the player: type a message, **hide → download .wav** (it self‑checks the decode before
downloading), then re‑upload that file and **decode** it to read the message back.

For images and heavy testing, use the Python tool (below). The included `carrier_stego.wav`
sounds like a four‑chord pad but contains a complete hidden JPEG.

---

## 9. The Python reference tools

Two scripts implement and **test** the whole system outside the browser.

### `mc_codec.py` — the language
Compiler (Python‑subset → opcodes), the looping VM and the straight‑line trace VM, the
deterministic realizer, the **decoder**, the **decompiler**, and MIDI read/write. Run it to see
the full test suite — every demo round‑trips through encode → decode (across 12 renderings each)
and through a real `.mid` file:

```bash
python mc_codec.py
```

### `mc_stego.py` — the steganography
LSB embedding with the header/repetition/interleave/CRC scheme. Run it to embed a text message
**and** a JPEG into a synthesized carrier, verify bit‑exact recovery, watch error‑correction
under random and burst corruption, and round‑trip through a `.wav` on disk:

```bash
python mc_stego.py
```

**Dependencies:** Python 3, `numpy` (stego), `mido` (MIDI in the codec), `pillow` (the JPEG
demo). Embed a payload programmatically with `mc_stego.embed_file(in_wav, out_wav, payload,
ptype)` and read it back with `mc_stego.extract_file(out_wav)`.

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
- A single operand literal is limited to 0–1727; build larger constants arithmetically.
- In **performance** mode, decoded source is the unrolled execution (loops are not re‑rolled).
- The steganography is robust in proportion to the carrier's spare capacity: a longer piece
  tolerates more corruption. It always **fails safe** (detect‑and‑refuse) rather than returning
  corrupted data.
- Audio uses the Web Audio API; some browsers require a click before sound will play.

---

*Musical Dynamics — write a program, hear it, and read it back out of the music.*
