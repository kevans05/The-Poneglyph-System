#!/usr/bin/env bash
# Start The Poneglyph System SCADA server.
#
# Usage:
#   ./start.sh                  # defaults: host 0.0.0.0, port 8000
#   PONEGLYPH_PORT=9000 ./start.sh
#   PONEGLYPH_HOST=127.0.0.1 PONEGLYPH_PORT=9000 ./start.sh

set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found on PATH" >&2
    exit 1
fi

REQUIRED=("openpyxl" "serial")
MISSING=()
for pkg in "${REQUIRED[@]}"; do
    python3 -c "import $pkg" 2>/dev/null || MISSING+=("$pkg")
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo "ERROR: missing Python packages: ${MISSING[*]}"
    echo "  Run:  pip install -r requirements.txt" >&2
    exit 1
fi

HOST="${PONEGLYPH_HOST:-0.0.0.0}"
PORT="${PONEGLYPH_PORT:-8000}"
echo "Starting Poneglyph System → http://${HOST}:${PORT}"
exec python3 api.py
