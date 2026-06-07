#!/usr/bin/env bash
# Musical Dynamics — run the reference self-tests, serve the app, open a browser tab.
# Linux / macOS / WSL / Git Bash.  Windows cmd users: run run.bat instead.
set -euo pipefail
cd "$(dirname "$0")"

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python

open_url() {
  local url="$1"
  if   command -v xdg-open    >/dev/null 2>&1; then xdg-open    "$url" >/dev/null 2>&1 &
  elif command -v open        >/dev/null 2>&1; then open        "$url"            # macOS
  elif command -v wslview     >/dev/null 2>&1; then wslview     "$url"            # WSL
  elif command -v powershell.exe >/dev/null 2>&1; then powershell.exe -NoProfile -Command "Start-Process '$url'"  # Git Bash
  else echo "→ Open this in your browser:  $url"; fi
}

echo "── Musical Dynamics · run ─────────────────────────────────"
echo "• Reference self-tests (codec round-trips, MD language):"
"$PY" mc_codec.py || echo "  (self-tests reported an issue — see above)"
if "$PY" -c "import pytest" 2>/dev/null; then
  echo
  echo "• Stego test suite:"
  "$PY" -m pytest tests/ -q 2>&1 | tail -3 || true
fi

# Prefer the modular web app (Vite) if it has been set up; else serve the single file.
if command -v npm >/dev/null 2>&1 && [ -f web/package.json ]; then
  echo "• Starting Vite dev server (Ctrl-C to stop)…"
  ( sleep 2; open_url "http://localhost:5173" ) &
  ( cd web && npm run dev )
else
  PORT=8000
  echo "• Serving the single-file app at http://localhost:$PORT/index.html (Ctrl-C to stop)…"
  ( sleep 1; open_url "http://localhost:$PORT/index.html" ) &
  "$PY" -m http.server "$PORT"
fi
