#!/usr/bin/env bash
# Regenerates the report screenshots and the demo GIF from the bundled demo data.
# Needs: uv, vhs, and Playwright with Google Chrome (uvx --with playwright).
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d)
uv run doesitfire demo --no-open --out "$out" >/dev/null
shoot() { uvx --with playwright==1.56.0 python scripts/screenshot.py "file://$out/report.html?$1" "$2" "$3" "$4" "$5"; }
shoot "lang=en&theme=light" docs/assets/report-light.png 1280 1000 light
shoot "lang=en&theme=dark" docs/assets/report-dark.png 1280 1000 dark
shoot "lang=es&theme=dark" docs/assets/report-mobile.png 390 844 dark
vhs docs/demo.tape
echo "assets written to docs/assets/"
