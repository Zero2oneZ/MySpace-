#!/usr/bin/env bash
# Launch the YouTube time-slider cutter Streamlit app.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# Install deps only when missing (skip the slow network round-trip on every launch).
need_install=0
python -c "import streamlit" 2>/dev/null || need_install=1
python -c "import plotly"   2>/dev/null || need_install=1
command -v yt-dlp >/dev/null 2>&1 || need_install=1
if [ "$need_install" -eq 1 ]; then
  pip install -q --disable-pip-version-check streamlit yt-dlp plotly
fi

# Ensure ffmpeg is reachable. Try, in order:
#   1. system PATH        2. ~/.nix-profile/bin   3. any ffmpeg in /nix/store
find_ffmpeg() {
  command -v ffmpeg 2>/dev/null && return 0
  for candidate in \
      "$HOME/.nix-profile/bin/ffmpeg" \
      /run/current-system/sw/bin/ffmpeg \
      /etc/profiles/per-user/"$USER"/bin/ffmpeg; do
    [ -x "$candidate" ] && { echo "$candidate"; return 0; }
  done
  # Last resort: pick the newest ffmpeg binary in /nix/store.
  local nix_ff
  nix_ff="$(ls -t /nix/store/*-ffmpeg*/bin/ffmpeg 2>/dev/null | head -n1 || true)"
  [ -n "$nix_ff" ] && [ -x "$nix_ff" ] && { echo "$nix_ff"; return 0; }
  return 1
}

if ! command -v ffmpeg >/dev/null 2>&1; then
  if FF="$(find_ffmpeg)"; then
    export PATH="$(dirname "$FF"):$PATH"
  else
    echo "run_yt_cutter.sh: ffmpeg not found. Install it (e.g. 'nix profile install nixpkgs#ffmpeg' or apt install ffmpeg)." >&2
    exit 1
  fi
fi

port_in_use() {
  ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"
}

if [ -n "${PORT:-}" ]; then
  PICKED="$PORT"
else
  PICKED=8511
  while port_in_use "$PICKED"; do
    PICKED=$((PICKED + 1))
    if [ "$PICKED" -gt 8599 ]; then
      echo "run_yt_cutter.sh: no free port found in 8511-8599" >&2
      exit 1
    fi
  done
fi

mkdir -p "$HERE/media/video" "$HERE/media/sound"
echo "run_yt_cutter.sh: launching yt_cutter on port $PICKED (video → $HERE/media/video, audio → $HERE/media/sound, ffmpeg=$(command -v ffmpeg))"
exec streamlit run yt_cutter.py --server.headless true --server.port "$PICKED"
