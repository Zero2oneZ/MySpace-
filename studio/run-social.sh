#!/usr/bin/env bash
# Launch the Social Studio Streamlit app (port 8515+).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [ ! -d ".venv" ]; then
  echo "run-social.sh: first launch — creating .venv…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --disable-pip-version-check -r requirements.txt 2>/dev/null || true

python3 bootstrap.py >/dev/null

port_in_use() {
  ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"
}

if [ -n "${PORT:-}" ]; then
  PICKED="$PORT"
else
  PICKED=8515
  while port_in_use "$PICKED"; do
    PICKED=$((PICKED + 1))
    if [ "$PICKED" -gt 8599 ]; then
      echo "run-social.sh: no free port found in 8515-8599" >&2
      exit 1
    fi
  done
fi

echo "run-social.sh: launching Social Studio on http://localhost:$PICKED"
exec streamlit run social_app.py --server.headless true --server.port "$PICKED"
