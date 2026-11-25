#!/usr/bin/env bash
# orchestrator-loop.sh — Interactive ToDo-JobBoard orchestrator
# Reads pending tasks, shows them one at a time, waits for [y/N] approval,
# then dispatches to the configured model via cc.
#
# Usage:
#   ./scripts/orchestrator-loop.sh [MODEL] [SLEEP_SECS]
#   ./scripts/orchestrator-loop.sh qwen3-coder-next:cloud 10
#
set -euo pipefail

JOB_BOARD_MD="/data/Projects/MySpace++/ToDo-JobBoard.md"
JOB_BOARD_JSONL="/data/Projects/MySpace++/ToDo-JobBoard.jsonl"
MODEL="${1:-qwen3-coder-next:cloud}"
SLEEP_SECS="${2:-10}"

green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*"; }
cyan()   { printf '\033[36m%s\033[0m\n' "$*"; }
dim()    { printf '\033[2m%s\033[0m\n' "$*"; }

# Ensure cc is available
if ! command -v cc >/dev/null 2>&1; then
  red "cc not on PATH — aborting"
  exit 1
fi

# Validate model exists in ollama
if ! curl -sS --max-time 5 "http://localhost:11434/api/tags" 2>/dev/null | jq -r '.models[].name' 2>/dev/null | grep -Fxq "$MODEL"; then
  yellow "WARNING: $MODEL not found in ollama list — will try anyway"
fi

iter=0
while true; do
  iter=$((iter+1))
  cyan ""
  cyan "╔════════════════════════════════════════════════════════════════════╗"
  cyan "║  Orchestrator Loop #$iter | Model: $MODEL                        ║"
  cyan "╚════════════════════════════════════════════════════════════════════╝"

  # Find latest state of each pending task from JSONL
  local pending_tasks=""
  if [ -f "$JOB_BOARD_JSONL" ]; then
    pending_tasks="$(jq -s '
      group_by(.task_id)
      | map(last)
      | map(select(.status == "pending" or .status == "held"))
      | .[]
      | "\(.task_id)|\(.plan_id)|\(.checkpoint)|\(.step)|\(.agent)|\(.benchmark)|\(.path)"
    ' "$JOB_BOARD_JSONL" 2>/dev/null || true)"
  fi

  if [ -z "$pending_tasks" ]; then
    green "No pending tasks found. Board is clean."
    dim "Sleeping ${SLEEP_SECS}s before next scan … (Ctrl+C to stop)"
    sleep "$SLEEP_SECS"
    continue
  fi

  yellow "Pending tasks:"
  local task_count=0
  echo "$pending_tasks" | while IFS='|' read -r tid plan_id checkpoint step agent benchmark path; do
    [ -z "$tid" ] && continue
    task_count=$((task_count+1))
    printf '  %s | plan=%s | checkpoint=%s | agent=%s | model=%s\n' "$tid" "$plan_id" "$checkpoint" "$agent" "$MODEL"
  done

  # Dispatch the first pending task
  local first_task
  first_task="$(echo "$pending_tasks" | head -n 1)"
  IFS='|' read -r TID PLAN_ID CHECKPOINT STEP AGENT BENCHMARK PATH <<< "$first_task"

  echo ""
  yellow "─────────────────────────────────────────────────────────────────────"
  yellow "Next task to dispatch:"
  printf '  %-12s %s\n' "Task ID:"     "$TID"
  printf '  %-12s %s\n' "Plan:"        "$PLAN_ID"
  printf '  %-12s %s\n' "Checkpoint:" "$CHECKPOINT"
  printf '  %-12s %s\n' "Step:"        "$STEP"
  printf '  %-12s %s\n' "Agent:"       "$AGENT"
  printf '  %-12s %s\n' "Model:"       "$MODEL"
  printf '  %-12s %s\n' "Benchmark:"   "$BENCHMARK"
  printf '  %-12s %s\n' "Path:"        "$PATH"
  yellow "─────────────────────────────────────────────────────────────────────"

  printf 'Dispatch this task to %s? [y/N/q] ' "$MODEL"
  read -r ans </dev/tty || ans=""
  case "$ans" in
    y|Y|yes|YES)
      yellow "Dispatching task $TID to $MODEL …"
      ;;
    q|Q|quit|QUIT)
      green "Quitting orchestrator loop. Goodbye."
      exit 0
      ;;
    *)
      dim "Skipped. Sleeping ${SLEEP_SECS}s …"
      sleep "$SLEEP_SECS"
      continue
      ;;
  esac

  # Build prompt from the task context
  local prompt
  prompt="You are the agent '$AGENT' working on task $TID of plan $PLAN_ID.
Checkpoint: $CHECKPOINT | Step: $STEP
Benchmark for completion: $BENCHMARK
Path: $PATH

Execute this step now. Be deterministic and specific. Output ONLY the result.
When finished, end your response with the literal token: DONE"

  local response rc
  response=""
  rc=0

  # Try cc tiny first (fast, cached, deterministic)
  yellow "Calling cc tiny -summarize …"
  response="$(CC_MODEL="$MODEL" CC_AUTO_SCOPE=0 cc tiny -summarize "$prompt" 2>/dev/null)" || rc=$?

  # Fallback to direct model_call via cc if tiny fails
  if [ "$rc" -ne 0 ] || [ -z "$response" ]; then
    yellow "cc tiny returned empty/failed (rc=$rc). Trying direct model call …"
    # We invoke cc's model_call indirectly via a freeform prompt that just echoes
    # Actually, use cc phase step if in a project, otherwise use a direct curl
    response="$(curl -sS --max-time 120 "http://localhost:11434/api/generate" \
      -d "$(jq -n --arg m "$MODEL" --arg p "$prompt" --arg ka "30s" \
      '{model:$m, prompt:$p, stream:false, options:{"temperature":0,"seed":42}, keep_alive:$ka}')" \
      | jq -r '.response // empty' 2>/dev/null)" || rc=$?
    if [ -z "$response" ]; then
      rc=1
    else
      rc=0
    fi
  fi

  # Strip DONE if present
  response="$(printf '%s' "$response" | sed -E 's/\s*\bDONE\s*$//')"

  # Append result to JSONL with hash chain
  local ts unix hash prev_hash
  ts="$(date -Iseconds)"
  unix="$(date +%s)"
  prev_hash="$(tail -n 1 "$JOB_BOARD_JSONL" 2>/dev/null | jq -r '.hash // "genesis"' 2>/dev/null || echo "genesis")"

  local row_without_hash
  row_without_hash="$(jq -n \
    --arg ts "$ts" \
    --argjson unix "$unix" \
    --arg event "orchestrate" \
    --arg task_id "$TID" \
    --arg plan_id "$PLAN_ID" \
    --arg checkpoint "$CHECKPOINT" \
    --arg step "$STEP" \
    --arg substep "" \
    --arg agent "$AGENT" \
    --arg model "$MODEL" \
    --arg status "$([ "$rc" = "0" ] && echo "active" || echo "failed")" \
    --arg gate "$([ "$rc" = "0" ] && echo "GO" || echo "HOLD")" \
    --arg benchmark "$BENCHMARK" \
    --arg next_agent "$AGENT" \
    --arg path "$PATH" \
    --arg svg_hash "" \
    --arg error "$([ "$rc" = "0" ] && echo "" || echo "rc=$rc")" \
    --argjson meta '{"orchestrator_loop":true,"iteration":'$iter',"approval":"manual"}' \
    '{ts:$ts,unix:$unix,hash:"",event:$event,task_id:$task_id,plan_id:$plan_id,checkpoint:$checkpoint,step:$step,substep:$substep,agent:$agent,model:$model,status:$status,gate:$gate,benchmark:$benchmark,next_agent:$next_agent,path:$path,svg_hash:$svg_hash,error:$error,meta:$meta}')"

  hash="$(printf '%s%s' "$prev_hash" "$row_without_hash" | sha256sum | awk '{print $1}')"

  printf '%s\n' "$row_without_hash" | jq --arg h "$hash" '.hash = $h' >> "$JOB_BOARD_JSONL"

  # Also append to markdown audit trail
  printf '\n- `[x] %s — Orchestrator Loop #%d dispatched %s via %s | rc=%d`\n' "$ts" "$iter" "$TID" "$MODEL" "$rc" >> "$JOB_BOARD_MD"

  if [ "$rc" -eq 0 ] && [ -n "$response" ]; then
    green "Task $TID dispatched successfully."
    echo ""
    dim "Response preview (first 500 chars):"
    printf '%s' "$response" | head -c 500
    echo ""
  else
    red "Task $TID dispatch failed (rc=$rc). See JSONL for details."
  fi

  echo ""
  dim "Sleeping ${SLEEP_SECS}s before next scan … (Ctrl+C to stop)"
  sleep "$SLEEP_SECS"
done
