#!/usr/bin/env bash
# ============================================================================
# scan_chain.sh — bash JSONL chain emitter for project trees.
#
# Walks one or more project roots and emits a deterministic JSONL stream that
# is ParserCursor-compatible (same schema as ~/.cc/inference_master_chain.jsonl).
# Pipe the output to a file, then walk it with:
#     python3 core/lib/parser_cursor.py walk <out.jsonl>
#
# Schema (one per line):
#   {"type":"element","name":"chain","depth":0,"attributes":{...}}
#   {"type":"element","name":"project","depth":1,"parent":"chain","attributes":{...}}
#   {"type":"element","name":"dir","depth":2,"parent":"project","attributes":{...}}
#   {"type":"element","name":"file","depth":3,"parent":"dir","attributes":{...}}
#   {"type":"text","name":"snippet","depth":4,"parent":"file","data":"..."}
#
# Deterministic: sorted walk, bounded depth, junk dirs skipped.
# Usage: scan_chain.sh <root1> [root2 ...] > chain.jsonl
# ============================================================================

set -euo pipefail

MAX_DEPTH="${SCAN_MAX_DEPTH:-3}"
SNIPPET_LINES="${SCAN_SNIPPET_LINES:-30}"

SKIP_DIRS='.git|.cache|.venv|venv|__pycache__|node_modules|target|dist|build|.vscode|.idea|.next|.pytest_cache|.mypy_cache|.ruff_cache|out|tmp|.tmp'
MANIFEST_FILES='README.md|README.rst|README.txt|README|Cargo.toml|package.json|pyproject.toml|requirements.txt|Move.toml|Move.lock|manifest.json|project.godot|Caddyfile|docker-compose.yml|Dockerfile|fly.toml|run.sh|install.sh|deploy.sh|CLAUDE.md|AGENT_CARD.md|REGISTRY.md|BB.md|NORTHSTAR_AGENT.md|main.gd|main.tscn'

# JSON line emitter — uses python for safe escaping, deterministic key order.
jline() {
  python3 -c '
import json, sys
d = {}
for arg in sys.argv[1:]:
    k, _, v = arg.partition("=")
    # try to parse as JSON for nested data; else treat as string
    try:
        d[k] = json.loads(v) if v and v[0] in "{[\"0123456789tfn-" else v
    except json.JSONDecodeError:
        d[k] = v
sys.stdout.write(json.dumps(d, ensure_ascii=True, sort_keys=True, separators=(",",":")))
sys.stdout.write("\n")
' "$@"
}

# Detect language by extension
lang_of() {
  case "${1##*.}" in
    rs) echo rust ;;
    py) echo python ;;
    ts|tsx) echo typescript ;;
    js|jsx|mjs|cjs) echo javascript ;;
    go) echo go ;;
    move) echo move ;;
    sol) echo solidity ;;
    cpp|cc|cxx|hpp|hxx|h) echo cpp ;;
    c) echo c ;;
    lua) echo lua ;;
    gd) echo gdscript ;;
    tscn|tres|gdextension) echo godot ;;
    sh|bash) echo bash ;;
    toml) echo toml ;;
    json|jsonl) echo json ;;
    yaml|yml) echo yaml ;;
    md|rst) echo markdown ;;
    html|htm) echo html ;;
    css) echo css ;;
    svg) echo svg ;;
    xml) echo xml ;;
    sql) echo sql ;;
    fbx|gltf|glb|obj|dae) echo 3d_model ;;
    png|jpg|jpeg|webp|gif) echo image ;;
    mp4|webm|mov|mkv) echo video ;;
    wav|mp3|flac|ogg) echo audio ;;
    *) echo "" ;;
  esac
}

# Capture top N lines of a manifest file as a single string
snippet_of() {
  head -n "$SNIPPET_LINES" "$1" 2>/dev/null | tr '\r' ' ' || true
}

# ---- emit root chain element ------------------------------------------------
ts="$(date -Iseconds)"
jline type=element name=chain depth=0 attributes="$(python3 -c '
import json,sys; print(json.dumps({"schema":"project_scan_chain_v1","ts":"'"$ts"'","roots":[ "'"$1"'"]+sys.argv[1:]}, ensure_ascii=True, sort_keys=True, separators=(",",":")))' "${@:2}")"

# ---- per-project walk -------------------------------------------------------
for root in "$@"; do
  [ -d "$root" ] || { jline type=element name=project depth=1 parent=chain attributes='{"path":"'"$root"'","status":"missing"}'; continue; }

  pname="$(basename "$root")"

  # Count summary (cheap, fast)
  total_files=$(find "$root" -maxdepth "$MAX_DEPTH" -type f -not -regex ".*/\($SKIP_DIRS\)/.*" 2>/dev/null | wc -l | tr -d ' ')
  total_dirs=$(find "$root" -maxdepth "$MAX_DEPTH" -type d -not -regex ".*/\($SKIP_DIRS\)/.*" 2>/dev/null | wc -l | tr -d ' ')
  total_size_kb=$(du -sk --exclude='.git' --exclude='node_modules' --exclude='target' --exclude='__pycache__' --exclude='.cache' --exclude='.venv' "$root" 2>/dev/null | awk '{print $1}')

  # Detect language mix (top 6)
  langs="$(find "$root" -maxdepth "$MAX_DEPTH" -type f -not -regex ".*/\($SKIP_DIRS\)/.*" 2>/dev/null \
    | grep -oE '\.[a-zA-Z0-9]+$' | sort | uniq -c | sort -rn | head -6 \
    | awk '{printf "%s(%s),", $2, $1}' | sed 's/,$//')"

  # Detect signature subsystems
  has_rust=0; [ -f "$root/Cargo.toml" ] || find "$root" -maxdepth 2 -name "Cargo.toml" -print -quit 2>/dev/null | grep -q . && has_rust=1
  has_python=0; [ -f "$root/pyproject.toml" ] || [ -f "$root/requirements.txt" ] || find "$root" -maxdepth 2 -name "*.py" -print -quit 2>/dev/null | grep -q . && has_python=1
  has_move=0; find "$root" -maxdepth 4 -name "*.move" -print -quit 2>/dev/null | grep -q . && has_move=1
  has_godot=0; [ -f "$root/project.godot" ] && has_godot=1
  has_node=0; [ -f "$root/package.json" ] && has_node=1
  has_htmx=0; grep -rl "htmx" "$root" --include='*.html' --include='*.js' -l 2>/dev/null | head -1 | grep -q . && has_htmx=1
  has_3d=0; find "$root" -maxdepth 4 \( -name "*.fbx" -o -name "*.gltf" -o -name "*.glb" \) -print -quit 2>/dev/null | grep -q . && has_3d=1
  has_db=0; find "$root" -maxdepth 4 \( -name "*.sql" -o -name "schema.sql" -o -name "*.db" -o -name "*.sqlite" \) -print -quit 2>/dev/null | grep -q . && has_db=1

  jline type=element name=project depth=1 parent=chain \
    attributes="$(python3 -c "
import json
print(json.dumps({
    'path': '$root',
    'name': '$pname',
    'total_files': $total_files,
    'total_dirs': $total_dirs,
    'total_size_kb': $total_size_kb,
    'langs': '$langs',
    'has_rust': bool($has_rust),
    'has_python': bool($has_python),
    'has_move': bool($has_move),
    'has_godot': bool($has_godot),
    'has_node': bool($has_node),
    'has_htmx': bool($has_htmx),
    'has_3d_assets': bool($has_3d),
    'has_db': bool($has_db),
}, ensure_ascii=True, sort_keys=True, separators=(',',':')))
")"

  # ---- emit top-level files (depth 2) -------------------------------------
  for f in "$root"/* "$root"/.[!.]*; do
    [ -e "$f" ] || continue
    bn="$(basename "$f")"
    rel="${f#$root/}"
    if [ -d "$f" ]; then
      # skip junk dirs
      echo "$bn" | grep -qE "^($SKIP_DIRS)$" && continue
      sub_files=$(find "$f" -maxdepth "$MAX_DEPTH" -type f -not -regex ".*/\($SKIP_DIRS\)/.*" 2>/dev/null | wc -l | tr -d ' ')
      jline type=element name=dir depth=2 parent=project \
        attributes="$(python3 -c "import json; print(json.dumps({'rel':'$rel','file_count':$sub_files,'project':'$pname'}, sort_keys=True, separators=(',',':')))")"
    elif [ -f "$f" ]; then
      ext="${bn##*.}"
      lang="$(lang_of "$bn")"
      size=$(stat -c %s "$f" 2>/dev/null || echo 0)
      jline type=element name=file depth=2 parent=project \
        attributes="$(python3 -c "import json; print(json.dumps({'rel':'$rel','ext':'$ext','lang':'$lang','size':$size,'project':'$pname'}, sort_keys=True, separators=(',',':')))")"

      # Manifest snippet
      if echo "$bn" | grep -qE "^($MANIFEST_FILES)$"; then
        snippet="$(snippet_of "$f")"
        jline type=text name=snippet depth=3 parent=file \
          data="$snippet" \
          attributes="$(python3 -c "import json; print(json.dumps({'file':'$rel','project':'$pname','lines':$SNIPPET_LINES}, sort_keys=True, separators=(',',':')))")"
      fi
    fi
  done

  # ---- emit notable nested manifests (depth 3, only manifests) -----------
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    rel="${f#$root/}"
    bn="$(basename "$f")"
    # depth of rel
    rel_depth=$(echo "$rel" | awk -F/ '{print NF}')
    [ "$rel_depth" -gt "$MAX_DEPTH" ] && continue
    [ "$rel_depth" -le 1 ] && continue   # already emitted as top-level
    size=$(stat -c %s "$f" 2>/dev/null || echo 0)
    jline type=element name=manifest depth=3 parent=project \
      attributes="$(python3 -c "import json; print(json.dumps({'rel':'$rel','name':'$bn','size':$size,'project':'$pname'}, sort_keys=True, separators=(',',':')))")"
    snippet="$(snippet_of "$f")"
    jline type=text name=snippet depth=4 parent=manifest \
      data="$snippet" \
      attributes="$(python3 -c "import json; print(json.dumps({'file':'$rel','project':'$pname'}, sort_keys=True, separators=(',',':')))")"
  done < <(find "$root" -maxdepth "$MAX_DEPTH" -type f -not -regex ".*/\($SKIP_DIRS\)/.*" \
            \( -name "Cargo.toml" -o -name "package.json" -o -name "pyproject.toml" \
            -o -name "README.md" -o -name "Move.toml" -o -name "CLAUDE.md" \
            -o -name "AGENT_CARD.md" -o -name "REGISTRY.md" -o -name "BB.md" \
            -o -name "project.godot" \) 2>/dev/null | sort)

done
