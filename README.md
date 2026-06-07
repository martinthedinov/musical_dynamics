# Musical Dynamics

A Turing-complete programming language whose instructions are musical chords. Write a small
subset of Python, hear it play as music, and watch a decoder reconstruct the program — output
**and** source — straight from the notes. One program can sound countless ways; any given set
of notes decodes to exactly one result.

### ▶ Live demo

**https://YOUR-USERNAME.github.io/musical-dynamics/**

*(Replace with your URL after enabling GitHub Pages — see below.)*

### What's here

- **`index.html`** — the whole app. Open it in any browser; nothing to install.
- **`Musical_Dynamics_Guide.md`** — full user guide (language, encoding, decoder, visual programming, steganography).
- **`mc_codec.py`** — reference implementation + test suite (compiler, VM, decoder, decompiler, **the MD language**, MIDI I/O). Run `python mc_codec.py`.
- **`mc_stego.py`** — the original LSB audio-steganography side feature. Run `python mc_stego.py`.
- **`stego/`** — a general file-in-music steganography package (arbitrary files, fountain-coded redundancy, optional AES-GCM, works on any WAV/FLAC/AIFF — MD-generated or not). Run `python -m stego.selftest`.
- **`setup.sh` / `setup.bat`, `run.sh` / `run.bat`** — cross-platform install and launch.
- **`IDEAS.md`** — directions for using/extending the MD language.
- **`carrier_stego.wav`** — a chord pad with a JPEG hidden inside it.
- **`roundtrip.mid`** — "Hello, World!" encoded as music.

### Run locally

Just open `index.html` in a browser. (Some browsers need a click before audio plays — use the **▶ run & play** button.)

### Deploy on GitHub Pages

1. Push this folder to a public repo.
2. **Settings → Pages → Build and deployment → Source: Deploy from a branch → `main` / `/ (root)` → Save**.
3. Wait ~1 minute; your site appears at `https://<username>.github.io/<repo>/`.

### Python tools (optional)

Run `./setup.sh` (Linux/macOS/WSL/Git Bash) or `setup.bat` (Windows), or
`pip install numpy mido pillow soundfile cryptography reedsolo av`, then run the scripts.

### Hide files in music (`stego/`)

Hide an **arbitrary file** inside any music file, with **fountain-coded redundancy** so it
survives partial corruption/overwrite, optional **AES-GCM** encryption, and a fail-safe
verify-and-refuse decoder. Carriers:

| Carrier | Method | Capacity (per minute of audio) | Survives lossy re-encode |
|---|---|---|---|
| **WAV/FLAC/AIFF** | LSB matching (±1) on samples | ~1.6 MB @ 1 bit-plane | n/a (bit-exact) |
| **MP3/AAC/Ogg** | DSSS watermark in mid-band FFT | ~300 B | yes — verified through MP3+MP3 double-encode |
| **MIDI**         | Low bits of note-on velocities | ~750 B @ 2 bits/note (3000-note track) | yes (re-export) |
| **MD-native** | Variation/voicing bits the decoder *ignores* | ~10–20 B per program | yes — the music *is* the program |

```bash
python -m stego embed song.flac secret.zip -o stego.flac --redundancy 4 --password hunter2
python -m stego embed song.mp3  note.txt   -o stego.mp3
python -m stego embed song.mid  msg.txt    -o stego.mid --n-lsb 2
python -m stego extract stego.flac -o ./out --password hunter2
python -m stego capacity song.wav
python -m stego.selftest                  # full demo: recovery under noise and large overwrites
```

### Testing

```bash
./setup.sh && python -m pytest tests/     # 137 tests, ~70s
```

Test fixtures use public-domain text (US Constitution preamble, Shakespeare, Poe, Alice in
Wonderland from Project Gutenberg) and synthesized audio. `tests/fetch_test_data.sh` downloads
real Wikipedia articles when networked, for richer integration tests.
