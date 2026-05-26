#!/usr/bin/env bash
# MySpace++ Phase 0 smoke test
# Verifies the ported cc substrate works end-to-end against a throwaway
# CC_HOME and a throwaway project dir. Does NOT touch the user's real
# ~/.cc/ or any existing project.
#
# Exits 0 on full pass, non-zero on any failure. Prints a summary at end.
#
# Usage:
#   core/tests/smoke.sh                     # uses ./core/cc
#   CC_BIN=/path/to/cc core/tests/smoke.sh  # uses a specific binary

set -uo pipefail

# Resolve cc binary
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CC_BIN="${CC_BIN:-$SCRIPT_DIR/../cc}"
if [ ! -x "$CC_BIN" ]; then
  echo "ERROR: cc binary not executable at: $CC_BIN" >&2
  exit 1
fi

# Throwaway scratch dirs
SMOKE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/myspace-smoke.XXXXXX")"
export CC_HOME="$SMOKE_ROOT/.cc-home"
export CC_CACHE="$CC_HOME/cache"
export CC_GLOBAL_DB="$CC_HOME/cc.db"
PROJECT_DIR="$SMOKE_ROOT/project"
mkdir -p "$PROJECT_DIR"

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

# --- T1: cc -help returns text -------------------------------------------
test_help() {
  local out
  out="$("$CC_BIN" -help 2>&1)" || { fail "-help exit nonzero"; return; }
  if printf '%s' "$out" | grep -q "cc — model-controlled"; then
    pass "help text present"
  else
    fail "help text missing expected banner"
  fi
}

# --- T2: cc -setup creates .cc/local.db with all tables ------------------
test_setup() {
  ( cd "$PROJECT_DIR" && "$CC_BIN" -setup >/dev/null 2>&1 ) || {
    fail "-setup exit nonzero"; return; }
  local db="$PROJECT_DIR/.cc/local.db"
  if [ ! -f "$db" ]; then
    fail "local.db not created at $db"; return
  fi
  pass "local.db created"
  # Every table the schema should produce. Update this list when adding
  # new tables in db.py.
  local expected=(projects todos bash_scripts directory_log queue current_task \
                  meta entrypoints runs agents tools workflows workflow_runs \
                  agent_defs swarm_defs swarm_runs swarm_run_steps phases \
                  phase_steps chats \
                  chain_runs chain_run_steps \
                  capability_cards gui_cards \
                  workflow_templates workflow_jobs workflow_job_steps)
  local missing=()
  for t in "${expected[@]}"; do
    if ! sqlite3 "$db" ".tables" 2>/dev/null | tr -s ' \n' '\n' | grep -qx "$t"; then
      missing+=("$t")
    fi
  done
  if [ "${#missing[@]}" -eq 0 ]; then
    pass "all ${#expected[@]} expected tables present"
  else
    fail "missing tables: ${missing[*]}"
  fi
  # Check CLAUDE.md was created with import line
  if grep -q '@.cc/CLAUDE.context.md' "$PROJECT_DIR/CLAUDE.md" 2>/dev/null; then
    pass "CLAUDE.md import wired"
  else
    fail "CLAUDE.md missing @.cc/CLAUDE.context.md import"
  fi
}

# --- T3: cc scope shows all expected fields -------------------------------
test_scope() {
  local out
  out="$( cd "$PROJECT_DIR" && "$CC_BIN" scope 2>&1 )" || {
    fail "scope exit nonzero"; return; }
  local fields=("project (global)" "project (local)" "cwd:" "local_root:" "local_db:" "model:" "tiny:" "agent_uuid:")
  local missing=()
  for f in "${fields[@]}"; do
    printf '%s' "$out" | grep -q "$f" || missing+=("$f")
  done
  if [ "${#missing[@]}" -eq 0 ]; then
    pass "all scope fields present"
  else
    fail "missing scope fields: ${missing[*]}"
  fi
}

# --- T4: agent lifecycle (claim then release) -----------------------------
test_agent_lifecycle() {
  # Run a quick cc command; afterwards its row should have finished_at set
  local before_uuid after_state
  ( cd "$PROJECT_DIR" && "$CC_BIN" -context >/dev/null 2>&1 )
  # Newest row
  local row
  row="$(sqlite3 -separator '|' "$PROJECT_DIR/.cc/local.db" \
    "SELECT uuid, action, COALESCE(finished_at,'') FROM agents ORDER BY started_at DESC LIMIT 1" 2>/dev/null)"
  if [ -z "$row" ]; then
    fail "no agent row recorded for cc -context"; return
  fi
  local fin="${row##*|}"
  if [ -n "$fin" ]; then
    pass "agent released cleanly (finished_at set)"
  else
    fail "agent leaked — finished_at empty: $row"
  fi
}

# --- T5: cc -agents lists the runs ----------------------------------------
test_agents_list() {
  local out
  out="$( cd "$PROJECT_DIR" && "$CC_BIN" -agents 2>&1 )" || {
    fail "-agents exit nonzero"; return; }
  if printf '%s' "$out" | grep -qE '^\[(live|done)\]'; then
    pass "-agents shows lifecycle rows"
  else
    fail "-agents output unexpected: $(printf '%s' "$out" | head -3)"
  fi
}

# --- T6: install-root auto-discovery ---------------------------------------
test_install_root() {
  # The script should have discovered CC_INSTALL_ROOT = dirname of cc itself,
  # since core/lib/db.py exists alongside core/cc.
  local install_root_expected
  install_root_expected="$(cd "$(dirname "$CC_BIN")" && pwd)"
  # We can probe by running cc -context and checking it didn't fail to find db.py
  if ( cd "$PROJECT_DIR" && "$CC_BIN" -context >/dev/null 2>&1 ); then
    pass "install-root discovery worked (db.py found at $install_root_expected/lib/db.py)"
  else
    fail "install-root discovery failed"
  fi
}

# --- T7: setup idempotency (re-run shouldn't break) -----------------------
test_setup_idempotent() {
  if ( cd "$PROJECT_DIR" && "$CC_BIN" -setup >/dev/null 2>&1 ); then
    pass "second -setup did not error"
  else
    fail "second -setup errored"
  fi
}

# --- T8: -chain parser (doesn't need ollama with --parse / --dry) ---------
test_chain_parser() {
  local out
  out="$("$CC_BIN" -chain --parse '{{"hello"} | {"world"}}' 2>/dev/null)" || {
    fail "-chain --parse exit nonzero"; return; }
  if printf '%s' "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["type"]=="Expr" and len(d["terms"])==2 and d["ops"]==["|"]' 2>/dev/null; then
    pass "-chain --parse produces correct AST"
  else
    fail "-chain --parse AST malformed"
  fi
  # --dry plan output for a nested cc-group
  out="$("$CC_BIN" -chain --dry '{{"A"} | cc {{"B"} + {"C"}}}' 2>/dev/null)" || {
    fail "-chain --dry exit nonzero"; return; }
  if printf '%s' "$out" | grep -q "cc-group (isolated)" && printf '%s' "$out" | grep -q "parallel × 2"; then
    pass "-chain --dry shows isolated group + parallel batch"
  else
    fail "-chain --dry plan missing expected structure"
  fi
  # Parse error path
  if "$CC_BIN" -chain --parse '{"A"} {"B"}' >/dev/null 2>&1; then
    fail "expected parse error for adjacent steps"
  else
    pass "parse error reported for adjacent steps"
  fi
}

# --- T9: chain DB schema present (ollama not needed) ----------------------
test_chain_schema() {
  local db="$PROJECT_DIR/.cc/local.db"
  for tbl in chain_runs chain_run_steps; do
    if sqlite3 "$db" ".tables" 2>/dev/null | tr -s ' \n' '\n' | grep -qx "$tbl"; then
      pass "$tbl table present"
    else
      fail "$tbl table missing"
    fi
  done
  # Verify -chain-list runs cleanly on an empty table
  if ( cd "$PROJECT_DIR" && "$CC_BIN" -chain-list >/dev/null 2>&1 ); then
    pass "-chain-list runs cleanly on empty table"
  else
    fail "-chain-list errored on empty table"
  fi
}

run_test "T1 — cc -help"                       test_help
run_test "T2 — cc -setup creates local.db"    test_setup
run_test "T3 — cc scope shows all fields"     test_scope
run_test "T4 — agent lifecycle (claim/release)" test_agent_lifecycle
run_test "T5 — cc -agents lists rows"         test_agents_list
run_test "T6 — install-root discovery"        test_install_root
run_test "T7 — setup idempotency"             test_setup_idempotent
run_test "T8 — chain parser (--parse / --dry)" test_chain_parser
run_test "T9 — chain DB schema + -chain-list"  test_chain_schema

echo
echo "================================="
echo "  smoke: $PASS pass / $FAIL fail"
echo "================================="
[ "$FAIL" -eq 0 ]
