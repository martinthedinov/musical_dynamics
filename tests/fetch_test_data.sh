#!/usr/bin/env bash
# Fetch a few real Wikipedia articles into tests/data/ for richer integration tests.
# Wikipedia content is CC BY-SA 4.0; cite Wikipedia if you redistribute these files.
# Requires `curl` and network access. Tests run fine without this — they fall back to the
# bundled public-domain fixtures.
set -euo pipefail
cd "$(dirname "$0")/data"

UA="musical-dynamics-stego-tests/0.1 (+https://github.com/martinthedinov/musical_dynamics) curl"

fetch_plain () {
  # $1 = article title (URL-encoded), $2 = output filename
  local title="$1" out="$2"
  echo "• ${out} <- en.wikipedia.org/wiki/${title}"
  curl -sSfA "$UA" \
    "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1&titles=${title}&format=json&exlimit=1&redirects=1" \
    | python3 -c '
import sys, json
data = json.load(sys.stdin)
pages = data["query"]["pages"]
page  = next(iter(pages.values()))
sys.stdout.write(page.get("extract", ""))
' > "$out"
  if [ ! -s "$out" ]; then
    echo "  (empty result; left $out empty)" >&2
  else
    echo "  ($(wc -c < "$out") bytes)"
  fi
}

fetch_plain Steganography                 wikipedia_steganography.txt
fetch_plain Reed%E2%80%93Solomon_error_correction wikipedia_reed_solomon.txt
fetch_plain MP3                           wikipedia_mp3.txt

echo
echo "Done. License reminder: Wikipedia text is CC BY-SA 4.0 — attribute if you redistribute."
