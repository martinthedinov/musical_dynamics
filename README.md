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
- **`mc_codec.py`** — reference implementation + test suite (compiler, VM, decoder, decompiler, MIDI I/O). Run `python mc_codec.py`.
- **`mc_stego.py`** — the audio-steganography side feature. Run `python mc_stego.py`.
- **`carrier_stego.wav`** — a chord pad with a JPEG hidden inside it.
- **`roundtrip.mid`** — "Hello, World!" encoded as music.

### Run locally

Just open `index.html` in a browser. (Some browsers need a click before audio plays — use the **▶ run & play** button.)

### Deploy on GitHub Pages

1. Push this folder to a public repo.
2. **Settings → Pages → Build and deployment → Source: Deploy from a branch → `main` / `/ (root)` → Save**.
3. Wait ~1 minute; your site appears at `https://<username>.github.io/<repo>/`.

### Python tools (optional)

`pip install numpy mido pillow`, then run either script.
