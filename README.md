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

Hide an **arbitrary file** inside any **WAV/FLAC/AIFF** (whether or not Musical Dynamics made
it), with **fountain-coded redundancy** so it survives partial corruption/overwrite, optional
**AES-GCM** encryption, and an inaudible ±1 LSB change:

```bash
python -m stego embed song.flac secret.zip -o stego.flac --redundancy 4 --password hunter2
python -m stego extract stego.flac -o ./out --password hunter2
python -m stego capacity song.wav
python -m stego.selftest        # demonstrates recovery under scattered noise and large overwrites
```

The pipeline is *fail-safe* (verify-and-refuse, never silent-wrong). MP3/AAC/Ogg watermarking,
a MIDI channel, and the MD-native compositional channel are planned; lossless carriers work today.
