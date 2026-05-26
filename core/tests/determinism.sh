#!/usr/bin/env bash
# MySpace++ Phase 0 determinism test
# Calls `cc tiny "<prompt>"` twice with the same prompt and asserts:
#   1. byte-identical responses
#   2. second call served from cache (proven by cache-file mtime not changing)
#   3. cache key is deterministic across runs (same sha256 file appears)
#
# Skips entirely if ollama is not reachable at $CC_OLLAMA_URL — this lets
# Phase 0 ship before the docker stack is wired in Phase 2.
#
# Usage:
#   core/tests/determinism.sh
#   CC_BIN=/path/to/cc CC_TINY_MODEL=qwen2.5-coder:1.5b core/tests/determinism.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CC_BIN="${CC_BIN:-$SCRIPT_DIR/../cc}"
OLLAMA_URL="${CC_OLLAMA_URL:-http://localhost:11434}"
MODEL="${CC_TINY_MODEL:-qwen2.5-coder:1.5b}"
PROMPT="${DETERMINISM_PROMPT:-What is two plus two? Answer with a single number.}"

# Probe ollama availability
if ! curl -sfm 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  echo "SKIP: ollama not reachable at $OLLAMA_URL"
  echo "      (this test runs in Phase 2 once docker compose brings ollama up)"
  exit 0
fi

# Probe model presence
if ! curl -sfm 3 "$OLLAMA_URL/api/tags" | grep -q "\"$MODEL\""; then
  echo "SKIP: model '$MODEL' not pulled in this ollama"
  echo "      pull with: ollama pull $MODEL"
  exit 0
fi

SMOKE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/myspace-determinism.XXXXXX")"
export CC_HOME="$SMOKE_ROOT/.cc-home"
export CC_CACHE="$CC_HOME/cache"
export CC_GLOBAL_DB="$CC_HOME/cc.db"
export CC_TINY_MODEL="$MODEL"
mkdir -p "$CC_CACHE"

cleanup() { rm -rf "$SMOKE_ROOT"; }
trap cleanup EXIT INT TERM

PASS=0; FAIL=0
pass() { echo "  PASS: $*"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $*"; FAIL=$((FAIL+1)); }

echo "=== determinism: prompt='$PROMPT' model='$MODEL' ==="
echo

# Call 1
echo "--- call 1 (expect: cache miss, real inference) ---"
out1="$("$CC_BIN" tiny "$PROMPT" 2>/dev/null)"
rc1=$?
echo "rc=$rc1"
echo "response (first 200 chars): $(printf '%s' "$out1" | head -c 200)"

# Note cache files after first call
cache_count_1="$(find "$CC_CACHE" -type f -name '*.txt' 2>/dev/null | wc -l)"
echo "cache files after call 1: $cache_count_1"

# Capture mtimes of cache files
mtimes_1="$(find "$CC_CACHE" -type f -name '*.txt' -exec stat -c '%Y %n' {} \; 2>/dev/null | sort)"

echo
echo "--- call 2 (expect: cache hit, identical bytes) ---"
sleep 1  # ensure mtime resolution would catch a re-write
out2="$("$CC_BIN" tiny "$PROMPT" 2>/dev/null)"
rc2=$?
echo "rc=$rc2"

cache_count_2="$(find "$CC_CACHE" -type f -name '*.txt' 2>/dev/null | wc -l)"
echo "cache files after call 2: $cache_count_2"

mtimes_2="$(find "$CC_CACHE" -type f -name '*.txt' -exec stat -c '%Y %n' {} \; 2>/dev/null | sort)"

# T1: byte-identical
if [ "$out1" = "$out2" ]; then
  pass "responses are byte-identical"
else
  fail "responses differ"
  echo "    out1: $(printf '%s' "$out1" | head -c 100)"
  echo "    out2: $(printf '%s' "$out2" | head -c 100)"
fi

# T2: cache file count unchanged
if [ "$cache_count_1" = "$cache_count_2" ] && [ "$cache_count_1" -ge 1 ]; then
  pass "cache file count stable ($cache_count_1)"
else
  fail "cache file count changed: $cache_count_1 → $cache_count_2"
fi

# T3: mtimes unchanged (i.e. second call read from cache, didn't rewrite)
if [ "$mtimes_1" = "$mtimes_2" ]; then
  pass "cache mtimes unchanged (second call hit cache)"
else
  fail "cache mtimes changed — second call rewrote cache"
  diff <(echo "$mtimes_1") <(echo "$mtimes_2") | head -10
fi

# T4: rc match
if [ "$rc1" = "$rc2" ]; then
  pass "exit codes match ($rc1)"
else
  fail "exit codes differ: $rc1 vs $rc2"
fi

echo
echo "================================="
echo "  determinism: $PASS pass / $FAIL fail"
echo "================================="
[ "$FAIL" -eq 0 ]
