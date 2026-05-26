#!/usr/bin/env bash
# Launch Wardrobe Studio Streamlit app.
# Friend-installable: works on Linux, macOS, Windows (WSL/Git-Bash), NixOS.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [ ! -d ".venv" ]; then
  echo "run-wardrobe.sh: first launch — creating .venv (this can take a couple of minutes)…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --disable-pip-version-check -r requirements.txt

# Nix-aware lib paths so numpy/cv2 native extensions resolve on NixOS.
# Safe no-op on every other OS (the dirs simply won't exist).
LDP=""
for p in \
  /nix/store/*-gfortran-*-lib/lib \
  /nix/store/*-zlib-*/lib \
  /run/current-system/sw/lib ; do
  for resolved in $p; do
    [ -d "$resolved" ] && LDP="$LDP:$resolved"
  done
done
[ -n "$LDP" ] && export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}${LDP}"

port_in_use() { ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"; }

PICKED="${PORT:-8510}"
while port_in_use "$PICKED"; do
  PICKED=$((PICKED + 1))
  [ "$PICKED" -gt 8599 ] && { echo "run-wardrobe.sh: no free port in 8510-8599" >&2; exit 1; }
done

echo "run-wardrobe.sh: launching Wardrobe Studio on http://localhost:$PICKED"
exec streamlit run wardrobe_studio.py --server.headless true --server.port "$PICKED"
