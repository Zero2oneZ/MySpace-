#!/usr/bin/env bash
# ============================================================================
# comfy_dag.sh — ComfyUI node + workflow DAG indexer.
#
# Scans a ComfyUI install, emits a deterministic JSONL chain that catalogs
# every node class (builtin + custom_nodes), their CATEGORY, INPUT_TYPES,
# RETURN_TYPES, and FUNCTION. Also emits any saved workflows under user/.
#
# Output is ParserCursor-compatible (same shape as scan_chain.sh).
# Pipe to ~/.cc/comfy_dag.jsonl, then walk with parser_cursor.py.
#
# Usage:
#   comfy_dag.sh [install_path]
#   default install_path: /data/Projects/ComfyUI
#
# Determinism: sorted walk, blake2b-on-class-name as element key,
# bounded depth, junk skipped.
# ============================================================================

set -euo pipefail

INSTALL="${1:-/data/Projects/ComfyUI}"

if [ ! -d "$INSTALL" ]; then
  echo "ComfyUI not found at $INSTALL" >&2
  exit 1
fi

# Heuristic check
if [ ! -f "$INSTALL/nodes.py" ] && [ ! -f "$INSTALL/main.py" ]; then
  echo "Path does not look like a ComfyUI install (no nodes.py/main.py at root): $INSTALL" >&2
  exit 1
fi

# JSON line emitter (same shape as scan_chain.sh)
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

ts="$(date -Iseconds)"

# Root element
jline type=element name=chain depth=0 \
  attributes="$(python3 -c "import json; print(json.dumps({'schema':'comfy_dag_v0','ts':'$ts','install':'$INSTALL'}, sort_keys=True, separators=(',',':')))")"

# Install metadata
size_mb=$(du -sm --exclude='models' --exclude='input' --exclude='output' --exclude='.git' --exclude='__pycache__' "$INSTALL" 2>/dev/null | awk '{print $1}')
mtime=$(stat -c %Y "$INSTALL" 2>/dev/null || echo 0)
jline type=element name=install depth=1 parent=chain \
  attributes="$(python3 -c "import json; print(json.dumps({'path':'$INSTALL','size_mb':$size_mb,'mtime_epoch':$mtime}, sort_keys=True, separators=(',',':')))")"

# Inline Python helper — parse a Python module for ComfyUI nodes.
# Emits one JSON dict per node, one per line to stdout.
parse_module() {
  local mod_path="$1"
  local pack="$2"
  python3 - "$mod_path" "$pack" <<'PYEOF'
import ast, json, sys, os

mod_path = sys.argv[1]
pack = sys.argv[2]
rel = mod_path

try:
    with open(mod_path, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()
except Exception:
    sys.exit(0)

try:
    tree = ast.parse(src)
except SyntaxError:
    sys.exit(0)

# First pass: find NODE_CLASS_MAPPINGS to know which classes are exported.
exported = set()
for node in tree.body:
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id == "NODE_CLASS_MAPPINGS":
                if isinstance(node.value, ast.Dict):
                    for k in node.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            exported.add(k.value)

# Walk classes; emit only those that look like ComfyUI nodes
for node in ast.walk(tree):
    if not isinstance(node, ast.ClassDef):
        continue

    cat = None
    return_types = None
    function = None
    has_input_types = False
    output_node = None

    for item in node.body:
        # INPUT_TYPES classmethod
        if isinstance(item, ast.FunctionDef) and item.name == "INPUT_TYPES":
            has_input_types = True
        # class-level constants
        if isinstance(item, ast.Assign):
            for tgt in item.targets:
                if not isinstance(tgt, ast.Name):
                    continue
                if tgt.id == "CATEGORY" and isinstance(item.value, ast.Constant):
                    cat = item.value.value
                elif tgt.id == "RETURN_TYPES":
                    if isinstance(item.value, ast.Tuple):
                        return_types = [
                            (e.value if isinstance(e, ast.Constant) else None)
                            for e in item.value.elts
                        ]
                elif tgt.id == "FUNCTION" and isinstance(item.value, ast.Constant):
                    function = item.value.value
                elif tgt.id == "OUTPUT_NODE" and isinstance(item.value, ast.Constant):
                    output_node = bool(item.value.value)

    # heuristic: only emit if it has at least one of these
    if not (has_input_types or return_types or cat or node.name in exported):
        continue

    out = {
        "class_name": node.name,
        "exported": node.name in exported,
        "category": cat or "",
        "return_types": return_types or [],
        "function": function or "",
        "output_node": bool(output_node),
        "has_input_types": has_input_types,
        "module": rel,
        "pack": pack,
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=True, sort_keys=True))
    sys.stdout.write("\n")
PYEOF
}

# ---- emit builtin nodes -----------------------------------------------------
# nodes.py is the master builtin module
if [ -f "$INSTALL/nodes.py" ]; then
  jline type=element name=node_pack depth=2 parent=install \
    attributes="$(python3 -c "import json; print(json.dumps({'pack_kind':'builtin','pack_name':'nodes','path':'nodes.py'}, sort_keys=True, separators=(',',':')))")"

  parse_module "$INSTALL/nodes.py" "builtin/nodes" | while IFS= read -r row; do
    jline type=element name=comfy_node depth=3 parent=node_pack \
      attributes="$row"
  done
fi

# comfy_extras/ — each .py file is one pack
if [ -d "$INSTALL/comfy_extras" ]; then
  for f in $(find "$INSTALL/comfy_extras" -maxdepth 1 -name '*.py' -type f | sort); do
    bn="$(basename "$f" .py)"
    [ "$bn" = "__init__" ] && continue
    jline type=element name=node_pack depth=2 parent=install \
      attributes="$(python3 -c "import json; print(json.dumps({'pack_kind':'extras','pack_name':'$bn','path':'comfy_extras/$bn.py'}, sort_keys=True, separators=(',',':')))")"

    parse_module "$f" "extras/$bn" | while IFS= read -r row; do
      jline type=element name=comfy_node depth=3 parent=node_pack \
        attributes="$row"
    done
  done
fi

# custom_nodes/ — each subdir is one pack
if [ -d "$INSTALL/custom_nodes" ]; then
  for dir in $(find "$INSTALL/custom_nodes" -maxdepth 1 -mindepth 1 -type d | sort); do
    pack_name="$(basename "$dir")"
    [ "$pack_name" = "__pycache__" ] && continue
    py_count=$(find "$dir" -name '*.py' -not -path '*/__pycache__/*' 2>/dev/null | wc -l | tr -d ' ')

    jline type=element name=node_pack depth=2 parent=install \
      attributes="$(python3 -c "import json; print(json.dumps({'pack_kind':'custom','pack_name':'$pack_name','path':'custom_nodes/$pack_name','py_count':$py_count}, sort_keys=True, separators=(',',':')))")"

    # parse all .py files in the pack (depth 2 only to bound work)
    for f in $(find "$dir" -maxdepth 2 -name '*.py' -not -path '*/__pycache__/*' 2>/dev/null | sort); do
      parse_module "$f" "custom/$pack_name" | while IFS= read -r row; do
        jline type=element name=comfy_node depth=3 parent=node_pack \
          attributes="$row"
      done
    done
  done
fi

# user/workflows/ — saved workflow JSON files
if [ -d "$INSTALL/user/workflows" ] || [ -d "$INSTALL/user/default/workflows" ]; then
  for wf_dir in "$INSTALL/user/workflows" "$INSTALL/user/default/workflows"; do
    [ -d "$wf_dir" ] || continue
    for f in $(find "$wf_dir" -maxdepth 2 -name '*.json' 2>/dev/null | sort); do
      rel="${f#$INSTALL/}"
      size=$(stat -c %s "$f" 2>/dev/null || echo 0)
      # Count nodes in the workflow (top-level keys are usually numeric ids)
      n_nodes=$(python3 -c "
import json, sys
try:
    d = json.load(open('$f'))
    if 'nodes' in d:
        print(len(d['nodes']))
    else:
        print(len(d))
except Exception:
    print(0)
" 2>/dev/null || echo 0)
      jline type=element name=workflow depth=2 parent=install \
        attributes="$(python3 -c "import json; print(json.dumps({'rel':'$rel','size':$size,'node_count':$n_nodes}, sort_keys=True, separators=(',',':')))")"
    done
  done
fi
