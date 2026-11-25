#!/usr/bin/env bash
# ============================================================================
# datasets_index.sh — /home/tom/Datasets indexer (the "hot fire" goldmine).
#
# Walks the Datasets tree, classifies every asset by purpose, emits a
# deterministic JSONL chain (ParserCursor-compatible) to stdout.
#
# Pipe to ~/.cc/datasets_index.jsonl, walk with parser_cursor.py.
# Cross-joinable with model_index.jsonl + comfy_dag.jsonl + scan_chain.jsonl
# via shared n-gram hashes.
#
# Usage:
#   datasets_index.sh [root1] [root2] ...
#   default root: /home/tom/Datasets
# ============================================================================

set -uo pipefail
# -e disabled deliberately — per-file iteration should never abort the whole walk

ROOTS=("$@")
[ ${#ROOTS[@]} -eq 0 ] && ROOTS=(/home/tom/Datasets)

jline() {
  python3 -c '
import json, sys
d = {}
for arg in sys.argv[1:]:
    k, _, v = arg.partition("=")
    try:
        d[k] = json.loads(v) if v and v[0] in "{[\"0123456789tfn-" else v
    except json.JSONDecodeError:
        d[k] = v
sys.stdout.write(json.dumps(d, ensure_ascii=True, sort_keys=True, separators=(",",":")))
sys.stdout.write("\n")
' "$@"
}

# Classify by extension + dir hint
classify() {
  local rel="$1"
  local fname="$2"
  local ext_lc; ext_lc=$(echo "${fname##*.}" | tr '[:upper:]' '[:lower:]')
  local lc_rel; lc_rel=$(echo "$rel" | tr '[:upper:]' '[:lower:]')

  case "$ext_lc" in
    fbx|obj|gltf|glb|blend|dae|3ds|stl|ply) echo "3d_mesh";       return ;;
    png|jpg|jpeg|webp|tga|bmp|gif)          echo "image";          return ;;
    exr|hdr)                                 echo "hdri_or_env";   return ;;
    psd|ai|xcf)                              echo "design_source"; return ;;
    svg)                                     echo "vector";        return ;;
    mp4|mov|mkv|webm|avi)                    echo "video";         return ;;
    wav|mp3|flac|ogg|aiff)                   echo "audio";         return ;;
    csv|tsv|parquet|arrow|feather)           echo "tabular";       return ;;
    json|jsonl|ndjson|yaml|yml)              echo "structured_data"; return ;;
    bvh|anim)                                echo "animation";     return ;;
    safetensors|ckpt|pt|pth|gguf|bin|onnx)   echo "model_weight";  return ;;
    txt|md|rst|html|htm)                     echo "text";          return ;;
  esac

  # Fallback by dir hint
  case "$lc_rel" in
    *blueprint*|*floorplan*|*floor_plan*) echo "blueprint";     return ;;
    *furniture*)                          echo "furniture";     return ;;
    *texture*|*material*)                 echo "texture";       return ;;
    *animation*|*mocap*|*motion*)         echo "animation";     return ;;
    *sprite*)                             echo "sprite";        return ;;
    *character*|*avatar*|*humanoid*)      echo "character";     return ;;
    *room*|*scene*|*environment*)         echo "scene";         return ;;
  esac
  echo "other"
}

# Bucket by size in bytes
size_bucket() {
  local n="$1"
  if   [ "$n" -lt 102400 ];      then echo tiny           # < 100 KB
  elif [ "$n" -lt 10485760 ];    then echo small          # < 10 MB
  elif [ "$n" -lt 104857600 ];   then echo medium         # < 100 MB
  elif [ "$n" -lt 1073741824 ];  then echo large          # < 1 GB
  else                                echo huge
  fi
}

ts="$(date -Iseconds)"
jline type=element name=chain depth=0 \
  attributes="$(python3 -c "
import json, sys
print(json.dumps({'schema':'datasets_index_v0','ts':'$ts','roots':sys.argv[1:]}, sort_keys=True, separators=(',',':')))
" "${ROOTS[@]}")"

for root in "${ROOTS[@]}"; do
  [ -d "$root" ] || continue
  root_name="$(basename "$root")"

  total_files=$(find "$root" -type f -not -path '*/.git/*' 2>/dev/null | wc -l | tr -d ' ')
  total_size_kb=$(du -sk --exclude='.git' "$root" 2>/dev/null | awk '{print $1}')

  jline type=element name=root depth=1 parent=chain \
    attributes="$(python3 -c "import json; print(json.dumps({'path':'$root','name':'$root_name','total_files':$total_files,'total_size_kb':$total_size_kb}, sort_keys=True, separators=(',',':')))")"

  # Per top-level subdir summary
  for sub in $(find "$root" -maxdepth 1 -mindepth 1 -type d -not -name '.*' 2>/dev/null | sort); do
    sub_name="$(basename "$sub")"
    sub_files=$(find "$sub" -type f -not -path '*/.git/*' 2>/dev/null | wc -l | tr -d ' ')
    sub_size_kb=$(du -sk --exclude='.git' "$sub" 2>/dev/null | awk '{print $1}')
    has_readme=0; [ -f "$sub/README.md" ] && has_readme=1
    has_manifest=0; [ -f "$sub/manifest.json" ] && has_manifest=1
    # Top extensions in this collection
    top_exts=$(find "$sub" -maxdepth 4 -type f -not -path '*/.git/*' 2>/dev/null \
      | grep -oE '\.[a-zA-Z0-9]+$' | sort | uniq -c | sort -rn | head -5 \
      | awk '{printf "%s(%s),", $2, $1}' | sed 's/,$//')

    jline type=element name=collection depth=2 parent=root \
      attributes="$(python3 -c "import json; print(json.dumps({'rel':'$sub_name','files':$sub_files,'size_kb':$sub_size_kb,'readme':bool($has_readme),'manifest':bool($has_manifest),'top_exts':'$top_exts'}, sort_keys=True, separators=(',',':')))")"

    if [ -f "$sub/README.md" ]; then
      snippet="$(head -n 20 "$sub/README.md" 2>/dev/null | tr '\r' ' ')"
      jline type=text name=readme_snippet depth=3 parent=collection \
        data="$snippet" \
        attributes="$(python3 -c "import json; print(json.dumps({'collection':'$sub_name'}, sort_keys=True, separators=(',',':')))")"
    fi
  done

  # Per-file emit (bounded depth to keep this fast)
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    rel="${f#$root/}"
    fname="$(basename "$f")"
    ext="${fname##*.}"
    size=$(stat -c %s "$f" 2>/dev/null || echo 0)
    mtime=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    kind="$(classify "$rel" "$fname")"
    bucket="$(size_bucket "$size")"
    collection="${rel%%/*}"

    jline type=element name=asset depth=2 parent=root \
      attributes="$(python3 -c "import json; print(json.dumps({'rel':'$rel','collection':'$collection','fname':'$fname','ext':'$ext','kind':'$kind','size_bucket':'$bucket','size':$size,'mtime':$mtime,'root':'$root_name'}, sort_keys=True, separators=(',',':')))")"
  done < <(find "$root" -maxdepth 6 -type f -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/node_modules/*' 2>/dev/null | sort)
done
