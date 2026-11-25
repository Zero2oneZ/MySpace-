#!/usr/bin/env bash
# download-seeds.sh — fetch the curated URL set from DOWNLOAD_INSYRUCTIONS.md
# into the right canonical bucket.
#
# Each LABEL=URL pair in DOWNLOAD_INSYRUCTIONS.md maps to a known destination
# under studio/media/. Single pin URLs are skipped automatically because
# Pinterest's per-pin pages don't serve scrapable image content — only the
# search URLs (`-dir` mode) actually return images.
#
# Usage:
#   ./download-seeds.sh                # fetch everything
#   ./download-seeds.sh TEXTURES       # fetch one label only
#   ./download-seeds.sh -n             # dry run — print plan, fetch nothing
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

python3 bootstrap.py >/dev/null

DRY=0
FILTER=""
while [ $# -gt 0 ]; do
  case "$1" in
    -n|--dry-run) DRY=1; shift ;;
    -h|--help)    sed -n '2,15p' "$0"; exit 0 ;;
    *)            FILTER="$1"; shift ;;
  esac
done

# label                dest_subpath_under_media           gender_hint
# Pinterest pin URLs (single posts) are kept here for the record but skipped
# because pinterest.com/pin/<id> is a JS-rendered page with no image in the
# HTML that wget can grab.
SEARCH_TARGETS=(
  "TEXTURES|Media/3d/textures|"
  "MAKEUP_MODEL|Models/Females/HeadShots|Female"
  "BLUE_PRINTS|House_Blueprints|"
  "FURNITURE_BLUEPRINTS|House_Blueprints|"
)

PIN_TARGETS=(
  "ALPHA|HEAD_TEMPLET"
  "TIKTOK_CHIC|Models/Females/Solo"
  "MAKEUP_TEMPLET|HEAD_TEMPLET"
  "CLOTHS_TEMPLET|Cloths/Female/Templets"
  "HEAD_TEMPLET|HEAD_TEMPLET"
)

INSTR="$HERE/DOWNLOAD_INSYRUCTIONS.md"
[ -r "$INSTR" ] || { echo "missing $INSTR" >&2; exit 2; }

url_for() {
  grep -E "^$1=" "$INSTR" | head -1 | cut -d= -f2-
}

run_fetch_dir() {
  local label="$1" dest="$2" gender="$3"
  local url; url="$(url_for "$label")"
  if [ -z "$url" ]; then echo "  skip (no URL): $label"; return; fi
  echo "  fetch dir: $label -> media/$dest"
  if [ "$DRY" -eq 1 ]; then return; fi
  local args=(-dir "$url" -dest "$dest")
  [ -n "$gender" ] && args+=(-gender "$gender")
  ./media/.tools/fetch-url.sh "${args[@]}" || echo "    (partial)"
}

note_pin() {
  local label="$1" dest="$2"
  local url; url="$(url_for "$label")"
  [ -z "$url" ] && return
  echo "  pin (manual save needed): $label -> media/$dest  [$url]"
}

echo "Canonical layout ready. Seeding from DOWNLOAD_INSYRUCTIONS.md..."
echo

for row in "${SEARCH_TARGETS[@]}"; do
  IFS='|' read -r label dest gender <<<"$row"
  [ -n "$FILTER" ] && [ "$FILTER" != "$label" ] && continue
  run_fetch_dir "$label" "$dest" "$gender"
done

echo
echo "Single-pin URLs (Pinterest blocks recursive scrape; open in browser + save):"
for row in "${PIN_TARGETS[@]}"; do
  IFS='|' read -r label dest <<<"$row"
  [ -n "$FILTER" ] && [ "$FILTER" != "$label" ] && continue
  note_pin "$label" "$dest"
done

echo
echo "done. (re-run with one label as argument to refresh just that bucket)"
