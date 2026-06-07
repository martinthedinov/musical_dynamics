#!/usr/bin/env bash
# Musical Dynamics — dependency installer (Linux / macOS / WSL / Git Bash).
# Windows cmd users: run setup.bat instead.
set -euo pipefail
cd "$(dirname "$0")"

echo "── Musical Dynamics · setup ───────────────────────────────"

# --- Python (for the reference codec, stego, MIDI/WAV/MusicXML tooling) ---
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "✗ Python 3 not found. Install it from https://www.python.org/downloads/ and re-run." >&2
  exit 1
fi
echo "• Python: $($PY --version 2>&1)"
"$PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
echo "• Installing Python packages (codec + stego)…"
"$PY" -m pip install --user --upgrade numpy mido pillow soundfile cryptography reedsolo
echo "• Installing PyAV for MP3/AAC/Ogg stego (best-effort)…"
"$PY" -m pip install --user --upgrade av || echo "  (PyAV unavailable here — MP3/AAC stego will be disabled; lossless WAV/FLAC/AIFF still work)"
echo "• Installing pytest for the test suite…"
"$PY" -m pip install --user --upgrade pytest

# --- Node (for the web app, only if present) ---
if command -v npm >/dev/null 2>&1 && [ -f web/package.json ]; then
  echo "• npm: $(npm -v) — installing web dependencies…"
  ( cd web && npm install )
else
  echo "• Skipping web build deps (npm or web/package.json not found)."
  echo "  The single-file app (index.html) still works with no build."
fi

echo "✓ Setup complete.  Launch with:  ./run.sh"
