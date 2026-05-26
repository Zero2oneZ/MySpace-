#!/usr/bin/env bash
# Launch the DAG Studio Streamlit app.
# Friend-installable: works on Linux, macOS, Windows (WSL/Git-Bash), NixOS.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [ ! -d ".venv" ]; then
  echo "run.sh: first launch — creating .venv (this can take a couple of minutes)…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --disable-pip-version-check -r requirements.txt

port_in_use() {
  ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"
}

if [ -n "${PORT:-}" ]; then
  PICKED="$PORT"
else
  PICKED=8501
  while port_in_use "$PICKED"; do
    PICKED=$((PICKED + 1))
    if [ "$PICKED" -gt 8599 ]; then
      echo "run.sh: no free port found in 8501-8599" >&2
      exit 1
    fi
  done
fi

echo "run.sh: launching DAG Studio on http://localhost:$PICKED"
exec streamlit run app.py --server.headless true --server.port "$PICKED"
