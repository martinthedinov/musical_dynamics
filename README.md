# Musical Dynamics

A Turing-complete programming language whose instructions are **musical chords**. Write Python
(or its own **MD** syntax), hear it play as music, and watch a decoder reconstruct the program
— output **and** source — straight from the notes. One program can sound countless ways; any
given set of notes decodes to **exactly one** result.

It's also a full-stack **steganography toolkit**: hide arbitrary files inside any music file
(WAV/FLAC/AIFF, MP3/AAC/Ogg, MIDI), with fountain-coded redundancy that survives partial
corruption, optional AES-GCM, and a fail-safe verify-and-refuse decoder. The browser and Python
implementations are byte-compatible (a stego WAV embedded by one is readable by the other).

---

## Quick start

```bash
./setup.sh             # one-time: installs Python + JS deps (setup.bat on Windows)
./run.sh               # runs self-tests + opens the app in a browser (run.bat on Windows)
```

Or open `index.html` directly in any browser — the original single-file demo has zero install.

---

## What's here

| Path | What |
|---|---|
| `index.html` | Original single-file zero-install demo (just open it). |
| `web/` | Redesigned Vite app: new player + **file-in-WAV stego UI** + MIDI/MusicXML/WAV exports. |
| `mc_codec.py` | Reference codec (Python compiler, MD compiler, VM, decoder, decompiler, MIDI I/O). Also a runnable self-test suite — `python3 mc_codec.py` exercises ~280 codec round-trips. |
| `mc_song_to_md.py` | Turn an arbitrary MIDI song into the closest valid MD program (nearest-opcode + beam-search through the validity engine). |
| `mc_stego.py` | The original LSB-only audio-stego side feature. Run `python3 mc_stego.py` for its demo (text + JPEG round-trips, corruption survival). Superseded by `stego/` for new work. |
| `stego/` | General file-in-music steganography package. CLI: `python3 -m stego embed\|extract\|capacity`. Native channel CLI: `python3 -m stego.md_native embed\|extract\|capacity`. |
| `setup.sh`/`.bat`, `run.sh`/`.bat` | Cross-platform install and launch. |
| `tests/` | 140 pytest tests + public-domain payload fixtures. `tests/fetch_test_data.sh` adds real Wikipedia articles when networked. |
| `Musical_Dynamics_Guide.md` | Full user guide: language, encoding, decoder, visual programming, steganography. |
| `IDEAS.md` | Directions for using/extending MD. |
| `carrier_stego.wav` | A chord pad with a JPEG hidden inside it. |
| `roundtrip.mid` | "Hello, World!" encoded as music. |

---

## The MD language

A tiny C/Python-flavored surface that compiles to the **same 21 opcodes** as the Python subset
(so every program round-trips through music identically). Boolean operators short-circuit via
`if`/`else` desugar — no new opcodes — so the music-round-trip guarantee is preserved.

```c
// hello.md  (or the same as Python in mc_codec.py:DEMOS)
for (i in range(1, 16)) {
    if      (i % 15 == 0) { print("FizzBuzz"); }
    elif    (i % 3  == 0) { print("Fizz");     }
    elif    (i % 5  == 0) { print("Buzz");     }
    else                  { print(i);          }
}

let x = 1; let y = 0;
if (x and y) { print(1); } elif (not y) { print(0); }    // boolean and / or / not
```

Supported: `let`, `if`/`elif`/`else`, `while`, `for…in range(…)`, `print`, integer literals,
strings (including emoji + CJK), `=` and `+= -= *= //= %=`, arithmetic `+ - * // %`,
comparisons `< > <= >= == !=`, boolean `and` / `or` / `not`, parenthesized expressions,
`#`/`/* */` comments. Errors carry line/column info via `MDSyntaxError`.

Python ↔ MD bridge: `mc_codec.python_to_md(src)`, `mc_codec.md_to_python(src)`.

---

## Hide files in music (`stego/`)

| Carrier | Method | Capacity per minute | Survives re-encode | CLI |
|---|---|---|---|---|
| **WAV / FLAC / AIFF** (uniform) | LSB matching (±1) on samples | ~1.6 MB @ 1 bit-plane | n/a (lossless) | `python3 -m stego` |
| **WAV / FLAC / AIFF** (adaptive) | **psychoacoustic per-sample bit-allocation** | up to ~6 MB on loud audio (4× uniform), masked | n/a (lossless) | `python3 -m stego --adaptive` |
| **Speech WAV** (adaptive) | adaptive **+ voice-activity gate** (skips silence) | tracks the speech; silence untouched | n/a (lossless) | `python3 -m stego --adaptive --profile speech` |
| **MP3 / AAC / Ogg** | DSSS watermark in mid-band FFT | ~300 B | yes — verified through double MP3 encode | `python3 -m stego` (small payloads only) |
| **MIDI** | Low bits of note-on velocities | ~750 B at `--n-lsb 2` (3k-note track) | yes (re-export) | `python3 -m stego` |
| **MD-native** | Variation/voicing bits the decoder *ignores* | ~10–20 B per program | yes — *the music **is** the program* | `python3 -m stego.md_native` |

### The general CLI

```bash
python3 -m stego embed    <carrier> <payload> [-o OUT] [--password] [--redundancy R] [--n-lsb N] [--adaptive [--profile music|speech]]
python3 -m stego extract  <carrier> [-o DIR]  [--password]
python3 -m stego capacity <carrier> [--n-lsb N] [--adaptive [--profile music|speech]]
```

- `--redundancy` defaults to `fill` (use all spare capacity for error-correction; tolerates
  losing ~85–90% of the carrier). Use `--redundancy 2` if you want to keep room for a longer
  payload, or omit for max robustness.
- `--n-lsb` defaults to `1` (stealthiest, ±1 sample). Higher = more capacity, more audible.
- `--out` defaults to `<carrier>_stego.<ext>` for embed and `.` for extract.
- All payloads are framed with their filename + CRC-32; recovery is fail-safe (refuses rather
  than returning corrupted bytes).
- `extract` auto-detects whether a file was embedded uniformly or adaptively — you don't pass
  `--adaptive` to extract.

### Adaptive (psychoacoustic) embedding — pack more, hear less

Instead of a fixed number of LSBs everywhere, `--adaptive` allocates **per-sample bit-depth from
the local signal energy**: loud passages hide up to 4 bits (the signal masks the embedding
noise), quiet/silent passages hide fewer or none. The allocation is computed from the *high*
bits the embedding never touches, so the decoder reproduces it blind. Versus fixed 1-LSB this
gives, on loud audio, **~4× the capacity**, the embedding noise stays provably below
`local-signal / 32` (so it's masked rather than a constant hiss in quiet parts), and — because
the data is spread across bit-planes 0..k-1 — it **survives LSB-plane stripping** (zeroing the
lowest plane only loses ~25% of the slots; the fountain rebuilds the rest).

```bash
python3 -m stego embed song.flac secret.zip --adaptive                 # max capacity, inaudible
python3 -m stego extract song_stego.flac -o ./out                       # auto-detected
```

### Hiding data in speech (without ruining it)

`--profile speech` adds a **voice-activity gate** (no embedding in silence — that's where any
perturbation would be audible) and a gentler masking margin, so the speech stays natural and
intelligible. Works on any 16-bit speech WAV (8/16/44.1 kHz, mono or stereo):

```bash
python3 -m stego embed  voicemail.wav secret.txt --adaptive --profile speech -o voicemail_stego.wav
python3 -m stego extract voicemail_stego.wav -o ./out
```

Silent gaps come out byte-identical; data rides only the energetic voiced/fricative regions
where it's masked.

### The MD-native channel (no PCM tampering at all)

```bash
python3 -m stego.md_native embed    <prog.md|prog.py> <payload> [-o stego.mid] [--password] [--repetition R]
python3 -m stego.md_native extract  <stego.mid>      [-o DIR]  [--password]   [--repetition R]
python3 -m stego.md_native capacity <prog.md|prog.py>          [--repetition R]
```

The decoder is provably blind to the per-opcode variation/voicing choice, so a payload-driven
arrangement still decodes to the **exact same program**. Capacity is small (per-opcode budget
is 1–3 bits), but the produced MIDI is indistinguishable from any other valid performance.

### Quick try-it-out

```bash
# make a 30-second 16-bit WAV carrier
python3 -c "
import numpy as np, soundfile as sf
t = np.linspace(0, 30, 30*44100, endpoint=False)
s = 0.4*np.sin(2*np.pi*220*t) + 0.3*np.sin(2*np.pi*440*t)
sf.write('carrier.wav', (np.stack([s,s],1)*30000).astype(np.int16), 44100, subtype='PCM_16')
"
echo "hello from cli" > secret.txt
python3 -m stego embed carrier.wav secret.txt
python3 -m stego extract carrier_stego.wav -o ./out
diff secret.txt out/secret.txt && echo "BIT-EXACT ✓"
```

The same `carrier_stego.wav` opens in the new Vite app's "extract" panel and gives you
`secret.txt` back. Cross-tested in both directions under Node (`cd web && npm test`).

### The selftest demo

```bash
python3 -m stego.selftest      # ~10 seconds; demonstrates all carriers
```

Shows WAV/FLAC bit-exact round-trip, recovery under 0.5–2% scattered LSB noise, recovery under
30/60/80% contiguous overwrite, AES-GCM with wrong-password rejection, and (with PyAV
installed) MP3 single + double encode survival.

---

## Web app (Vite — the redesign)

```bash
cd web && npm install && npm run dev    # http://localhost:5173
cd web && npm run build                  # static build into web/dist/ (for GitHub Pages)
cd web && npm test                       # 9 JS tests, incl. Python <-> JS cross-decode
```

Sections in the new UI:
1. **Python editor + run & play** — write code, hear it as chords, see the decoded Python.
2. **Realization controls** — mode/key/octave/tempo/variation; all change the sound only.
3. **Export buttons** — `⤓ MIDI (.mid)`, `⤓ MusicXML` (opens in MuseScore etc.), `⤓ rendered WAV`.
4. **Hide file in WAV** — pick a carrier WAV + any payload file, choose redundancy, click embed
   → downloads `stego.wav`. Use the right card to extract from an existing stego WAV.

The stego format is **byte-identical** to the Python CLI's output — files embedded by Python
extract in the browser, and vice versa (the JS uses the same mulberry32 PRNG and MDX1 wire
format as `stego/pipeline.py`).

---

## Song → MD program

```bash
python3 mc_song_to_md.py path/to/song.mid                 # prints MD source + fidelity score
python3 mc_song_to_md.py path/to/song.mid --show-opcodes  # also dump the opcode stream
python3 mc_song_to_md.py path/to/song.mid -o out.md       # write to file instead of stdout
```

Reads any MIDI, clusters notes by onset, finds the nearest opcode per chord by Jaccard distance
over pitch-class sets, and beam-searches the stream into a balanced, runnable MD program. On
`roundtrip.mid` (Hello World) it recovers fidelity = **1.0**.

---

## Testing

```bash
./setup.sh && python3 -m pytest tests/    # 140 Python tests, ~70s
cd web && npm test                         # 9 JS tests (incl. Python <-> JS cross-decode)
python3 mc_codec.py                        # the reference's own self-test suite (~280 round-trips)
```

Test fixtures use public-domain text (US Constitution preamble, Shakespeare's Sonnet 18, Poe's
"The Raven", Lewis Carroll's *Alice in Wonderland* via Project Gutenberg) plus synthesized
audio. `tests/fetch_test_data.sh` downloads real Wikipedia articles (CC BY-SA 4.0) when
networked, for richer integration tests.

---

## Deploy on GitHub Pages

**Option A — original single-file demo (zero build):**
1. Push to a public repo.
2. **Settings → Pages → Build and deployment → Source: Deploy from a branch → `main` / `/(root)` → Save.**
3. Site appears at `https://<username>.github.io/<repo>/`, serving `index.html`.

**Option B — the new Vite app:**

The Vite build is already configured with `base: "./"` so assets are path-relative. After
`npm run build`, you have three choices:
- **Commit `web/dist/`** and point Pages at `/web/dist` (simplest; but commits build output).
- **Use a Pages Action** that runs `cd web && npm ci && npm run build` and uploads `web/dist/`.
- **Serve both side-by-side**: keep `index.html` at the root for the legacy demo, deploy
  `web/dist/` separately (e.g. at `/web/`).

I haven't wired the Pages Action yet — say the word and I'll add it.

---

## Python dependencies (if you skip `setup.sh`)

```bash
pip install numpy mido pillow soundfile cryptography reedsolo av pytest
```

`av` (PyAV) is optional — without it, MP3/AAC/Ogg stego is disabled but the lossless path still
works.
