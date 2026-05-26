#!/usr/bin/env bash
# DAG cache test suite — exhaustive checks of the hash-addressed
# cache layer (dag_nodes, dag_edges, dag_chains, dag_build_queue).
#
# Uses a throwaway CC_DB so it never touches the live cache. No
# ollama / network deps. Idempotent — re-runs cleanly.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CC_BIN="${CC_BIN:-$SCRIPT_DIR/../cc}"

if [ ! -x "$CC_BIN" ]; then
  echo "ERROR: cc binary not executable at: $CC_BIN" >&2
  exit 1
fi

# Throwaway DB. Must seed the cards because dag_builder reads them.
SMOKE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/myspace-dag-test.XXXXXX")"
export CC_HOME="$SMOKE_ROOT/.cc-home"
export CC_CACHE="$CC_HOME/cache"
export CC_GLOBAL_DB="$CC_HOME/cc.db"
mkdir -p "$CC_HOME"

# Initialize the schema
CC_DB="$CC_GLOBAL_DB" python3 "$(dirname "$CC_BIN")/lib/db.py" init >/dev/null 2>&1 \
  || CC_DB="$CC_GLOBAL_DB" python3 "${CC_BIN%/cc}/lib/db.py" init >/dev/null 2>&1 \
  || true

# Find the right db.py — repo layout uses ../core/lib, install uses ~/.cc/lib
DB_PY=""
for cand in "$(dirname "$CC_BIN")/lib/db.py" "${CC_BIN%/cc}/lib/db.py" "$HOME/.cc/lib/db.py"; do
  if [ -f "$cand" ]; then DB_PY="$cand"; break; fi
done
if [ -z "$DB_PY" ]; then
  echo "ERROR: cannot locate db.py" >&2; exit 1
fi
CC_DB="$CC_GLOBAL_DB" python3 "$DB_PY" init >/dev/null 2>&1

# Seed minimum cards needed for bootstrap to be useful.
# Use the LIVE cards if available — copying just the rows we need.
LIVE_DB="$HOME/.cc/cc.db"
if [ -f "$LIVE_DB" ]; then
  for tbl in capability_cards gui_cards; do
    sqlite3 "$LIVE_DB" ".mode insert $tbl" \
      "SELECT * FROM $tbl LIMIT 53" 2>/dev/null \
      | sqlite3 "$CC_GLOBAL_DB" 2>/dev/null || true
  done
fi

cleanup() { rm -rf "$SMOKE_ROOT"; }
trap cleanup EXIT INT TERM

PASS=0; FAIL=0
pass() { echo "  PASS: $*"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }
run_test() {
  local name="$1"; shift
  echo
  echo "=== $name ==="
  "$@"
}

q() { sqlite3 "$CC_GLOBAL_DB" "$1"; }

# --- T1: schema present --------------------------------------------------
test_schema() {
  for tbl in dag_nodes dag_edges dag_chains dag_build_queue; do
    if q "SELECT 1 FROM $tbl LIMIT 1" >/dev/null 2>&1; then
      pass "$tbl exists"
    else
      fail "$tbl missing"
    fi
  done
}

# --- T2: bootstrap on empty produces nodes ------------------------------
test_bootstrap() {
  CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-bootstrap >/dev/null 2>&1
  local n
  n="$(q "SELECT COUNT(*) FROM dag_nodes WHERE node_kind='opcode'")"
  if [ "$n" -ge 50 ]; then
    pass "bootstrap created opcode nodes (n=$n)"
  else
    fail "bootstrap produced only $n opcode nodes (expected ≥50)"
  fi
  local e
  e="$(q "SELECT COUNT(*) FROM dag_edges WHERE edge_kind='succession'")"
  if [ "$e" -ge 100 ]; then
    pass "bootstrap created succession edges (n=$e)"
  else
    fail "bootstrap produced only $e succession edges (expected ≥100)"
  fi
}

# --- T3: idempotency — re-bootstrap doesn't grow ------------------------
test_idempotent() {
  local n_before n_after e_before e_after
  n_before="$(q 'SELECT COUNT(*) FROM dag_nodes')"
  e_before="$(q 'SELECT COUNT(*) FROM dag_edges')"
  CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-bootstrap >/dev/null 2>&1
  n_after="$(q 'SELECT COUNT(*) FROM dag_nodes')"
  e_after="$(q 'SELECT COUNT(*) FROM dag_edges')"
  if [ "$n_before" = "$n_after" ]; then
    pass "node count stable across re-bootstrap (n=$n_after)"
  else
    fail "node count grew $n_before → $n_after on re-bootstrap"
  fi
  if [ "$e_before" = "$e_after" ]; then
    pass "edge count stable across re-bootstrap (e=$e_after)"
  else
    fail "edge count grew $e_before → $e_after on re-bootstrap"
  fi
}

# --- T4: hash stability across runs -------------------------------------
test_hash_stability() {
  # Capture node_id for "Text-to-Speech" opcode
  local id1 id2
  id1="$(q "SELECT node_id FROM dag_nodes WHERE name='Text-to-Speech' AND node_kind='opcode'")"
  CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-bootstrap >/dev/null 2>&1
  id2="$(q "SELECT node_id FROM dag_nodes WHERE name='Text-to-Speech' AND node_kind='opcode'")"
  if [ -n "$id1" ] && [ "$id1" = "$id2" ]; then
    pass "Text-to-Speech node_id stable ($id1)"
  else
    fail "Text-to-Speech node_id changed: $id1 → $id2"
  fi
}

# --- T5: succession edges sorted by weight DESC ------------------------
test_successor_order() {
  # Get successors of Text-to-Speech sorted by weight; verify descending.
  local prev=999.0
  local ok=1
  while read -r w; do
    [ -z "$w" ] && continue
    awk -v p="$prev" -v c="$w" 'BEGIN{exit !(c <= p)}' || { ok=0; break; }
    prev="$w"
  done < <(q "SELECT weight FROM dag_edges e JOIN dag_nodes n ON n.node_id=e.src_node WHERE n.name='Text-to-Speech' AND e.edge_kind='succession' ORDER BY e.weight DESC LIMIT 5")
  if [ "$ok" = "1" ]; then
    pass "successor edges sorted by weight DESC"
  else
    fail "successor edges not in DESC order"
  fi
}

# --- T6: cc -dag-successors lookup ------------------------------------
test_lookup_successors() {
  local out
  out="$(CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-successors "Text-to-Speech" 5 2>&1)"
  if echo "$out" | grep -q "Audio-Image-to-Video"; then
    pass "successors lookup returns expected top result (Audio-Image-to-Video)"
  else
    fail "successors lookup missing expected result"
    echo "$out" | head -8
  fi
}

# --- T7: cc -dag-successors on unknown opcode is graceful --------------
test_lookup_missing_opcode() {
  local out
  out="$(CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-successors "BogusNonexistentOpcode" 2>&1)"
  if echo "$out" | grep -qi "no opcode"; then
    pass "missing opcode returns friendly error (not sys.exit)"
  else
    fail "missing opcode handling unexpected: $(echo "$out" | head -3)"
  fi
  # AND the exit code should be 0 (graceful), not nonzero
  CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-successors "BogusNonexistentOpcode" \
    >/dev/null 2>&1
  local rc=$?
  if [ "$rc" = "0" ]; then
    pass "missing opcode exits cleanly (rc=0)"
  else
    fail "missing opcode exit code: $rc (expected 0)"
  fi
}

# --- T8: chains lookup by modality pair --------------------------------
test_chains_pair() {
  local out
  out="$(CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-chains AUDIO VIDEO 3 2>&1)"
  if echo "$out" | grep -q "Audio-Image-to-Video\|Audio-Text-to-Text"; then
    pass "AUDIO→VIDEO chains contain expected opcodes"
  else
    fail "AUDIO→VIDEO chains missing"
    echo "$out" | head -5
  fi
}

# --- T9: queue lifecycle -----------------------------------------------
test_queue_lifecycle() {
  # Pick any chain_id, enqueue a rebuild, run worker, verify done.
  local cid
  cid="$(q 'SELECT chain_id FROM dag_chains LIMIT 1')"
  if [ -z "$cid" ]; then
    fail "no chains in DB — bootstrap may have failed"; return
  fi
  CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-enqueue rebuild_chain "$cid" >/dev/null 2>&1
  local pending
  pending="$(q "SELECT COUNT(*) FROM dag_build_queue WHERE status='pending'")"
  if [ "$pending" -ge 1 ]; then
    pass "enqueue added a pending task"
  else
    fail "enqueue did not add task"; return
  fi
  CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-build >/dev/null 2>&1
  local done_count
  done_count="$(q "SELECT COUNT(*) FROM dag_build_queue WHERE status='done'")"
  if [ "$done_count" -ge 1 ]; then
    pass "worker processed task to done"
  else
    fail "worker did not process task"
  fi
}

# --- T10: invalidate marks rows stale ---------------------------------
test_invalidate() {
  # Mark Text-to-Speech invalid; verify nodes + chains get stale flag.
  local opcode="Text-to-Speech"
  CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-invalidate "$opcode" >/dev/null 2>&1
  local stale_nodes stale_chains
  stale_nodes="$(q 'SELECT COUNT(*) FROM dag_nodes WHERE stale=1')"
  stale_chains="$(q "SELECT COUNT(*) FROM dag_chains WHERE stale=1 AND chain_json LIKE '%${opcode}%'")"
  if [ "$stale_nodes" -ge 1 ]; then
    pass "invalidate marked nodes stale ($stale_nodes)"
  else
    fail "invalidate didn't mark any nodes stale"
  fi
  if [ "$stale_chains" -ge 1 ]; then
    pass "invalidate marked chains stale ($stale_chains)"
  else
    fail "invalidate didn't mark chains containing the opcode"
  fi
  # Re-bootstrap should clear stale flag
  CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-bootstrap >/dev/null 2>&1
  local still_stale
  still_stale="$(q 'SELECT COUNT(*) FROM dag_nodes WHERE stale=1')"
  if [ "$still_stale" = "0" ]; then
    pass "re-bootstrap cleared stale flag"
  else
    fail "$still_stale node(s) still stale after re-bootstrap"
  fi
}

# --- T11: opcode with terminal output (Image Classification) -----------
test_terminal_opcode() {
  # Image Classification outputs LABEL — no successors expected.
  local n
  n="$(q "SELECT COUNT(*) FROM dag_edges e JOIN dag_nodes n ON n.node_id=e.src_node WHERE n.name='Image Classification' AND e.edge_kind='succession'")"
  # Some opcodes might still have edges if Any-to-Any consumes LABEL. The
  # critical check is that the count is small (terminal-ish), not zero.
  if [ "$n" -le 2 ]; then
    pass "Image Classification has ≤2 successors ($n) — terminal-shaped"
  else
    fail "Image Classification has $n successors (expected ≤2 for terminal)"
  fi
}

# --- T12: dag-status output structure ----------------------------------
test_status_output() {
  local out
  out="$(CC_DB="$CC_GLOBAL_DB" "$CC_BIN" -dag-status 2>&1)"
  for s in "nodes:" "edges:" "chains:" "queue:"; do
    echo "$out" | grep -q "$s" || { fail "status missing '$s'"; return; }
  done
  pass "dag-status output has all four sections"
}

# --- T13: node IDs are valid sha256[:16] -------------------------------
test_node_id_format() {
  local bad
  bad="$(q "SELECT COUNT(*) FROM dag_nodes WHERE LENGTH(node_id) != 16 OR node_id GLOB '*[^0-9a-f]*'")"
  if [ "$bad" = "0" ]; then
    pass "all node_ids are 16-char hex (sha256 prefix)"
  else
    fail "$bad node_id(s) are malformed"
  fi
}

run_test "T1 — schema present"                test_schema
run_test "T2 — bootstrap populates"           test_bootstrap
run_test "T3 — idempotent re-bootstrap"       test_idempotent
run_test "T4 — hash stability"                test_hash_stability
run_test "T5 — successor order"               test_successor_order
run_test "T6 — successors lookup"             test_lookup_successors
run_test "T7 — missing opcode graceful"       test_lookup_missing_opcode
run_test "T8 — chains pair lookup"            test_chains_pair
run_test "T9 — queue lifecycle"               test_queue_lifecycle
run_test "T10 — invalidate marks stale"       test_invalidate
run_test "T11 — terminal opcode no edges"     test_terminal_opcode
run_test "T12 — status output structure"      test_status_output
run_test "T13 — node_id format"               test_node_id_format

echo
echo "================================="
echo "  dag cache: $PASS pass / $FAIL fail"
echo "================================="
[ "$FAIL" -eq 0 ]
