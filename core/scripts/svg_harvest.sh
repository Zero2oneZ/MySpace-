#!/usr/bin/env bash
# ============================================================================
# svg_harvest.sh — local SVG file harvester (the 5th retrieval axis input).
#
# Walks one or more roots, finds every *.svg file, extracts every <path d=...>
# element, computes its 64-dim DCT-II shape descriptor, emits ParserCursor-
# compatible JSONL to stdout.
#
# Pipe to ~/.cc/svg_index.jsonl. Queryable via svg_vector_embed.find_svg_neighbors
# or (when wired) moe_router.find_svg_neighbors.
#
# Usage:
#   svg_harvest.sh [root1] [root2] ...
#   default roots: /data/Projects/MySpace++ (current repo)
# ============================================================================

set -uo pipefail

ROOTS=("$@")
[ ${#ROOTS[@]} -eq 0 ] && ROOTS=(/data/Projects/MySpace++)

# JSONL emitter — pure Python for safety
ts="$(date -Iseconds)"
python3 -c "
import json, sys
print(json.dumps({'type':'element','name':'chain','depth':0,'attributes':{'schema':'svg_index_v0','ts':'$ts','roots':sys.argv[1:]}}, sort_keys=True, ensure_ascii=True, separators=(',',':')))
" "${ROOTS[@]}"

for root in "${ROOTS[@]}"; do
  [ -d "$root" ] || continue
  root_name="$(basename "$root")"

  total=$(find "$root" -type f -name "*.svg" -not -path '*/.git/*' -not -path '*/node_modules/*' 2>/dev/null | wc -l | tr -d ' ')

  python3 -c "
import json
print(json.dumps({'type':'element','name':'root','depth':1,'parent':'chain','attributes':{'path':'$root','name':'$root_name','total_svg_files':$total}}, sort_keys=True, ensure_ascii=True, separators=(',',':')))
"

  # Walk each SVG file and emit its paths
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    rel="${f#$root/}"
    size=$(stat -c %s "$f" 2>/dev/null || echo 0)

    python3 - "$f" "$root" "$rel" "$size" <<'PYEOF'
import json, sys, math
from pathlib import Path

sys.path.insert(0, '/data/Projects/MySpace++/core/lib')
from svg_vector_embed import embed_svg_file

svg_path, root, rel, size = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])

# Emit the file node first
print(json.dumps({
    "type":"element","name":"svg_file","depth":2,"parent":"root",
    "attributes":{"rel":rel,"size":size,"root":root.split('/')[-1]},
}, sort_keys=True, ensure_ascii=True, separators=(',',':')))

try:
    recs = embed_svg_file(svg_path)
except Exception as e:
    print(json.dumps({
        "type":"text","name":"svg_error","depth":3,"parent":"svg_file",
        "data":f"{type(e).__name__}: {e}",
        "attributes":{"rel":rel},
    }, sort_keys=True, ensure_ascii=True, separators=(',',':')))
    sys.exit(0)

for r in recs:
    # Round embedding to 5 decimals to save space; still deterministic enough
    emb_rounded = [round(x, 5) for x in r.embedding]
    bbox_rounded = [round(v, 4) for v in r.bbox]
    print(json.dumps({
        "type":"element","name":"svg_path","depth":3,"parent":"svg_file",
        "attributes":{
            "src_file": rel,
            "path_index": r.path_index,
            "point_count": r.point_count,
            "crystal": r.crystal,
            "bbox": bbox_rounded,
        },
        "data": {
            "d_head": r.d[:200],
            "embedding": emb_rounded,
        },
    }, sort_keys=True, ensure_ascii=True, separators=(',',':')))
PYEOF
  done < <(find "$root" -type f -name "*.svg" -not -path '*/.git/*' -not -path '*/node_modules/*' 2>/dev/null | sort)

done
