#!/usr/bin/env bash
# Launch the Pinterest search Streamlit app.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [ ! -d ".venv" ]; then
  echo "run-pinterest.sh: first launch — creating .venv (this can take a couple of minutes)…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --disable-pip-version-check -r requirements.txt
# Pinterest API mode needs httpx (only installed if proxy reqs are also there).
pip install --disable-pip-version-check 'httpx>=0.27' || true

# Canonical layout — idempotent.
python3 bootstrap.py >/dev/null

port_in_use() { ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"; }

PICKED="${PORT:-8512}"
while port_in_use "$PICKED"; do
  PICKED=$((PICKED + 1))
  [ "$PICKED" -gt 8599 ] && { echo "run-pinterest.sh: no free port in 8512-8599" >&2; exit 1; }
done

echo "run-pinterest.sh: launching Pinterest Search on http://localhost:$PICKED"
exec streamlit run pinterest_app.py --server.headless true --server.port "$PICKED"
