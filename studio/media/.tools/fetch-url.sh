#!/usr/bin/env bash
# fetch-url.sh — download a URL (or list of URLs), classify, drop into the
# right Images/ subfolder, then run a background-removal + mask pass on images.
#
# Usage:
#   ./fetch-url.sh -url <URL>                    # single URL
#   ./fetch-url.sh -url <URL> -dest <subpath>    # force destination subpath
#   ./fetch-url.sh -list <file>                  # one URL per line
#   ./fetch-url.sh -url <URL> -no-bg             # skip bg removal
#   ./fetch-url.sh -url <URL> -gender Male       # gender hint for cloths
#   ./fetch-url.sh -dir <pinterest-search-url>   # treat as page; wget recursively, images only
#
# Env:
#   IMG_ROOT  - override root (default: parent of this script's .tools dir)
set -euo pipefail

SELF="$(readlink -f "$0")"
# Script now lives at studio/media/.tools/fetch-url.sh — so IMG_ROOT is the
# parent of the .tools dir. Back-compat: if the script is sitting at the
# media root (older layouts), fall back to its own dir.
_self_dir="$(dirname "$SELF")"
if [ "$(basename "$_self_dir")" = ".tools" ]; then
  IMG_ROOT="${IMG_ROOT:-$(dirname "$_self_dir")}"
else
  IMG_ROOT="${IMG_ROOT:-$_self_dir}"
fi
TOOLS="$IMG_ROOT/.tools"
STAGE="$IMG_ROOT/.staging"
LOGS="$IMG_ROOT/.logs"
mkdir -p "$STAGE" "$LOGS"

LOG="$LOGS/fetch-$(date +%Y%m%d-%H%M%S).log"

URL=""
LIST=""
DEST_FORCE=""
NO_BG=0
GENDER_HINT=""
RECURSIVE=0

while [ $# -gt 0 ]; do
  case "$1" in
    -url)     URL="$2"; shift 2 ;;
    -list)    LIST="$2"; shift 2 ;;
    -dest)    DEST_FORCE="$2"; shift 2 ;;
    -no-bg)   NO_BG=1; shift ;;
    -gender)  GENDER_HINT="$2"; shift 2 ;;
    -dir)     URL="$2"; RECURSIVE=1; shift 2 ;;
    -h|--help)
      sed -n '2,15p' "$SELF"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }

# --- helpers -----------------------------------------------------------------

classify_path() {
  # Echo classification dest; injects gender hint into filename if user gave one.
  local f="$1"
  if [ -n "$GENDER_HINT" ]; then
    # symlink with gender suffix so classifier picks it up
    local hinted="${f%.*}__${GENDER_HINT}.${f##*.}"
    ln -sf "$f" "$hinted" 2>/dev/null || true
    python3 "$TOOLS/process.py" classify "$hinted"
    rm -f "$hinted"
  else
    python3 "$TOOLS/process.py" classify "$f"
  fi
}

process_one() {
  local src="$1"
  local base; base="$(basename "$src")"
  local dest_rel
  if [ -n "$DEST_FORCE" ]; then
    dest_rel="$DEST_FORCE"
  else
    dest_rel="$(classify_path "$src")"
  fi
  local dest_dir="$IMG_ROOT/$dest_rel"
  mkdir -p "$dest_dir"

  # Resolve collisions
  local final="$dest_dir/$base"
  if [ -e "$final" ]; then
    final="$dest_dir/$(date +%s)_$base"
  fi
  mv -- "$src" "$final"
  log "  -> $dest_rel/$(basename "$final")"

  # Background removal + mask pass (images only)
  local ext="${final##*.}"
  ext="${ext,,}"
  case "$ext" in
    jpg|jpeg|png|webp|bmp|tif|tiff|avif)
      if [ "$NO_BG" -eq 0 ]; then
        local stem; stem="$(basename "${final%.*}")"
        local bg_out="$IMG_ROOT/Media/Image/${stem}_nobg.png"
        local mk_out="$IMG_ROOT/Media/Mask/${stem}_mask.png"
        if python3 "$TOOLS/process.py" bgremove "$final" "$bg_out" >>"$LOG" 2>&1; then
          log "     bg-removed -> Media/Image/${stem}_nobg.png"
        fi
        if python3 "$TOOLS/process.py" mask "$final" "$mk_out" >>"$LOG" 2>&1; then
          log "     mask       -> Media/Mask/${stem}_mask.png"
        fi
      fi
      ;;
  esac
}

fetch_single() {
  local u="$1"
  log "fetch: $u"
  local before; before="$(find "$STAGE" -maxdepth 1 -type f | wc -l)"
  ( cd "$STAGE" && wget -q --content-disposition --no-clobber \
      --user-agent="Mozilla/5.0" --tries=2 --timeout=30 "$u" ) || {
        log "  wget failed: $u"; return 0; }
  # Process any new files
  find "$STAGE" -maxdepth 1 -type f -newer "$LOG" -print0 2>/dev/null |
    while IFS= read -r -d '' f; do process_one "$f"; done
}

fetch_recursive() {
  local u="$1"
  log "fetch (recursive image scrape): $u"
  ( cd "$STAGE" && wget -q -nd -H -p -A "jpg,jpeg,png,webp,gif" \
      --user-agent="Mozilla/5.0" --tries=2 --timeout=30 \
      -e robots=off "$u" ) || log "  wget recursive partial fail"
  find "$STAGE" -maxdepth 1 -type f -print0 |
    while IFS= read -r -d '' f; do process_one "$f"; done
}

# --- main --------------------------------------------------------------------

if [ -n "$URL" ] && [ "$RECURSIVE" -eq 1 ]; then
  fetch_recursive "$URL"
elif [ -n "$URL" ]; then
  fetch_single "$URL"
elif [ -n "$LIST" ]; then
  [ -r "$LIST" ] || { echo "list not readable: $LIST" >&2; exit 2; }
  while IFS= read -r line; do
    line="${line%%#*}"; line="${line## }"; line="${line%% }"
    [ -z "$line" ] && continue
    # Accept either bare URL or "FILENAME=foo URL=https://..." style
    if [[ "$line" == *"="* ]] && [[ "$line" == *"http"* ]]; then
      u="$(printf '%s\n' "$line" | grep -oE 'https?://[^ ]+' | head -1)"
    else
      u="$line"
    fi
    [ -n "$u" ] && fetch_single "$u"
  done < "$LIST"
else
  sed -n '2,15p' "$SELF"
  exit 2
fi

log "done. log: $LOG"
