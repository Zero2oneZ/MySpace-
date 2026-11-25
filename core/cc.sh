#!/usr/bin/env bash
# cc — model-controlled bash + python automation with split global/local DBs
# WARNING: this shadows /run/current-system/sw/bin/cc (system C compiler).
#          `make`, `cmake`, build systems calling `cc` directly will hit this
#          script instead. Rename if that bites you.
#
# DB scoping:
#   ~/.cc/cc.db                       GLOBAL  — projects, todos, queue, log
#   <project>/.cc/local.db            LOCAL   — meta, entrypoints, runs, agents
# Resolution: walk up from cwd; the first ancestor with .cc/local.db wins.
# `cc -setup` creates one in cwd. With no local DB, only global ops work.
#
# Getting Started:
#   cc h                                interactive menu with brief descriptions
#   cc h -v                             verbose mode with more details
#   cc h --full                         full command reference
#
# Subcommands:
#   cc tui                              launch the curses dashboard (color, tabs,
#                                       assign-to-project, view transcripts/agents)
#   cc -setup [instruction...]          discover venv/repo/entries, init local.db,
#                                       maintain CLAUDE.md context import
#   cc -context                         dump everything cc knows about cwd
#   cc scope                            one-line scope summary
#   cc -agents                          list active+recent cc instances
#   cc -runs [-n N]                     recent runs in this project (local)
#
#   cc py <script> [args...]            run via local venv; diagnose on failure
#   cc bash <script-or-name> [args...]  run a local .sh or registered script
#
#   cc claude <instruction...>          one-shot Claude with full cc context
#   cc claude -i [instruction...]       interactive Claude primed with cc state
#   cc claude -plan <instruction...>    Claude decomposes into todos (vs local model)
#   cc claude -last                     show last Claude response saved in runs
#   cc claude-import                    import all ~/.claude sessions for this cwd
#   cc chat [prompt...]                 deterministic chat gateway — spell-fix,
#                                       enhance structure, count tokens, route
#                                       to the right model by scope budget, build
#                                       keyword similarity chains, emit Godot bridge
#   cc chat --route-only [prompt...]    only token count + model selection
#   cc chat --enhance-only [prompt...]  only spell-fix + structure
#   cc chat --chain-only [prompt...]    only keyword chain expansion
#   cc chat --godot [prompt...]         emit Godot bridge packet JSON
#   cc inference-chain [-n N]           show last N crystal-chained inference records
#   cc inference-verify                 verify crystal chain integrity (replay hashes)
#   cc inference-search <query>        semantic search over inference logs
#   cc inference-get <crystal_id>      retrieve one inference record by crystal hash
#   cc workflow-card generate <card> [--target all|streamlit|godot_scene|godot_gd|godot_cpp|blender|spriteforge|comfyui]
#                                       emit surface(s) from a workflow_card_v0 JSON
#   cc workflow-card crystal <card>     compute the card_crystal (BLAKE3 hex)
#   cc workflow-card list               list workflow cards in studio/assets/_workflows/
#   cc workflow-card show <name>        dump a workflow card by name
#   cc queue-status                     task_queue + GPU + cache snapshot (JSON)
#   cc gpu-status                       GPU VRAM + reservations + nvidia-smi reality
#   cc cache-stats                      result_cache hit-rate + size
#   cc comfy-index                      rescan /data/Projects/ComfyUI → ~/.cc/comfy_dag.jsonl
#   cc models-index [root...]           rescan /home/tom/models  → ~/.cc/model_index.jsonl
#   cc datasets-index [root...]         rescan /home/tom/Datasets → ~/.cc/datasets_index.jsonl
#   cc scan-projects <root...>          run scan_chain.sh across given project dirs
#   cc ops-dag {build|summary|topo|parallel|placeholders|ready|path <a> <b>}
#                                       the operational DAG — auto-built from agent_defs +
#                                       workflows + text_placeholders. Tells you what's ready
#                                       to build next + optimal parallel order
#   cc studio-list                      list workflow_cards in studio/assets/_workflows/
#   cc studio-run <card> [--dry-run] [--json]
#                                       end-to-end orchestration: every declared pass dispatches
#                                       through the right substrate, every surface emits to disk,
#                                       trace_crystal logs to the inference chain
#   cc dialectic-walk {walk|summary|step N}
#                                       reverse-walk the chain: IS / IS-NOT / BECOMING per step
#   cc model-search <query>             search HuggingFace + Ollama unified model catalog
#   cc model-install --hf <repo> --category <cat> --subtype <sub>   install HF model
#   cc model-install --ollama <name> --category <cat> --subtype <sub>  install Ollama model
#   cc model-list [--brand|--category|--subtype]                    list installed models
#   cc model-taxonomy                   show all 43 category/subtype slots
#   cc model-sync                       rebuild registry.json from disk configs
#
#   cc third_party-connect --service <svc> --token <t>   register outbound connector
#   cc third_party-send --service <svc> --to <id> --message <msg>  send message
#   cc third_party-list [--service|--state]             list active outbound connections
#   cc third_party-status                             health check of all connectors
#   cc third_party-archive --asset-id <id>              archive a connection config
#
#   cc endpoint-start --kind <k> --name <n> [--port <p>]  register inbound listener
#   cc endpoint-list [--kind|--service|--state|--tag]   list inbound endpoints
#   cc endpoint-status                                health check of all listeners
#   cc endpoint-sync                                  rebuild endpoint registry
#   cc route-add --name <n> --priority <p> --match-tag <t> --action <a>
#                                                     add routing rule
#   cc route-list [--tag <t>]                         list active routing rules
#   cc route-test --event-json <json>                 simulate event against rules
#   cc route-archive --asset-id <id>                  archive a route rule
#
#   cc chats                            list captured Claude chats (this project)
#   cc chat-show <id>                   render a captured chat readably
#
#   cc tiny [-debug|-summarize] [prompt...]   call the small local model (default
#                                             qwen3.5:0.8b, deterministic). Use this
#                                             to offload classification, parsing,
#                                             summarization, debug from Claude.
#
#   cc -chain '<spec>'                        structured multi-step chain over the
#                                             local model. Grammar:
#                                               {"prompt"}       leaf step
#                                               { EXPR }         group, inherits ctx
#                                               cc { EXPR }      isolated group
#                                             Operators between terms:
#                                               |  pipe (prev output → context)
#                                               +  parallel batch (concurrent)
#                                               -  sequential, context reset
#                                             Use --parse / --dry to introspect.
#                                             Example:
#                                               cc -chain '{{"draft a haiku"} | {"translate to French"}}'
#                                             Each run is persisted to local.db:
#   cc -chain-last                            full dump of the most recent chain run
#   cc -chain-show <id>                       dump chain run #id with per-step I/O
#   cc -chain-list [-n N]                     list recent chain runs (id, status, ms)
#
#   cc -cards                                 list per-opcode capability cards (global)
#   cc -card-show <opcode>                    full JSON card for an opcode
#   cc -card-delete <opcode>                  remove a card
#   cc -author-cards <opcode>                 draft a card via tiny-model chain
#   cc -author-cards --all                    draft cards for every opcode in JSONL
#   cc -author-cards --missing                only opcodes that don't have a card yet
#
#   cc -gui-cards                             list per-opcode GUI widget specs (global)
#   cc -gui-show <opcode>                     full JSON widget spec for an opcode
#   cc -gui-delete <opcode>                   remove a gui card
#   cc -author-gui-cards <opcode>             draft widget spec (uses capability card if present)
#   cc -author-gui-cards --all                draft for every opcode with a capability card
#   cc -author-gui-cards --baseline-only OP   skip tiny model, use modality defaults
#
#   cc -templates                             list Claude-authored workflow templates
#   cc -template-show <name>                  full JSON for a template
#   cc -template-delete <name>                remove a template
#   cc -authorize-templates <opcode>          DRY mode: print the Claude prompt only
#   cc -authorize-templates <opcode> --execute    actually call Claude (~$0.02)
#   cc -authorize-templates --all --execute   author for every opcode w/ both cards
#   cc -authorize-templates --missing --execute  only opcodes without a template yet
#
#   cc -jobs [-n N]                           list workflow jobs (local, per-project)
#   cc -job-show <id>                         full state dump for a job + its steps
#   cc -job-last                              most recent job
#                                             (executor `cc -job` is W4 work, not yet built)
#
#   cc -dag-bootstrap                         scan source data → populate global DAG cache
#   cc -dag-status                            counts: nodes / edges / chains / queue / hot
#   cc -dag-node <node_id>                    inspect a node + outgoing edges
#   cc -dag-chain <chain_id>                  inspect a cached chain (increments hit count)
#   cc -dag-build [--loop] [--sleep N]        process build-queue tasks (one or loop)
#   cc -dag-enqueue <kind> <target_id>        enqueue a rebuild task
#   cc -dag-successors <opcode> [top]         zero-compute: top successors from cache
#   cc -dag-chains-from <opcode> [top]        zero-compute: chains starting w/ opcode
#   cc -dag-chains <src_mod> <dst_mod> [top]  zero-compute: chains by modality pair
#   cc -dag-invalidate <opcode>               mark all related cache rows stale
#   cc -template-walk <name>                  dry-run: walk through a template
#                                             step-by-step, predict GUI elements
#                                             per step, validate binds, preview
#                                             next-step UI (no models called)
#
#   cc phase start <name>                     open a new orchestration phase
#   cc phase step [-model <m>|-tiny|-claude] <prompt>
#                                             run one step against active phase.
#                                             Parent ('tween level') reconstructs
#                                             context from prior steps in the db;
#                                             child sees only what parent provides
#                                             and MUST end its reply with 'DONE'.
#   cc phase log                              show steps of active phase
#   cc phase show <id>                        full dump of any phase
#   cc phase list                             list all phases (this project)
#   cc phase end [-summary <text>]            close the active phase
#
#   cc -set-project <name>              global: set/switch active project
#   cc -list-projects                   global: list all
#   cc -add-bash <name> [desc...]       model-author + register a bash script
#   cc -list-bash                       list registered scripts (global)
#   cc -plan [-model <m>] <instr...>    decompose instruction into todos
#   cc -todos                           todos for active project (global)
#   cc -done <id>                       mark todo complete
#   cc -edit-todo <id> <text...>        edit todo text only
#   cc -current                         show pinned current task
#   cc -current-set <todo-id>           pin current task
#   cc -current-clear                   unpin
#   cc -queue                           list queued cmds
#   cc -run <queue-id>                  execute queued cmd
#   cc -log [-n N]                      recent directory-log (global)
#
#   cc -clear-cache                     drop the deterministic prompt cache
#   cc -help                            this help
#   cc <freeform...>                    no flag = quick action; model proposes
#                                       a bash cmd, you confirm, it runs, logged.

set -uo pipefail

# ---- install-root discovery ---------------------------------------------
# CC_HOME is where user DATA lives (cc.db, local.db, cache, scripts) — it's
# user-configurable and defaults to ~/.cc/.
# CC_INSTALL_ROOT is where the CODE lives (this script + lib/* + setup/*).
# The two are separate so a repo checkout doesn't pollute user data and a
# user-data dir doesn't need to bundle copies of the lib.
#
# Discovery order for CC_INSTALL_ROOT:
#   1. explicit env var
#   2. script-dir co-located with lib/db.py  (repo: core/cc + core/lib/)
#   3. script-dir/../lib/db.py               (bin/myspace + lib/db.py install)
#   4. fall back to $CC_HOME (legacy ~/.cc/ install)
_cc_script_path="$(readlink -f "$0" 2>/dev/null || \
  python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$0" 2>/dev/null || \
  echo "$0")"
_cc_script_dir="$(cd "$(dirname "$_cc_script_path")" && pwd)"

CC_HOME="${CC_HOME:-$HOME/.cc}"
if [ -z "${CC_INSTALL_ROOT:-}" ]; then
  if [ -f "$_cc_script_dir/lib/db.py" ]; then
    CC_INSTALL_ROOT="$_cc_script_dir"
  elif [ -f "$_cc_script_dir/../lib/db.py" ]; then
    CC_INSTALL_ROOT="$(cd "$_cc_script_dir/.." && pwd)"
  else
    CC_INSTALL_ROOT="$CC_HOME"
  fi
fi

CC_GLOBAL_DB="${CC_GLOBAL_DB:-$CC_HOME/cc.db}"
CC_LIB="$CC_INSTALL_ROOT/lib/db.py"
CC_SCRIPTS="$CC_HOME/scripts"
CC_CACHE="$CC_HOME/cache"
CC_STUDIO_HOME="${CC_STUDIO_HOME:-$HOME/myspace-studio}"
CC_MODEL="${CC_MODEL:-glm-5.2:cloud}"
CC_TINY_MODEL="${CC_TINY_MODEL:-qwen2.5:3b}"
CC_OLLAMA_URL="${CC_OLLAMA_URL:-http://localhost:11434}"
CC_DETERMINISTIC="${CC_DETERMINISTIC:-1}"
CC_MODEL_TIMEOUT="${CC_MODEL_TIMEOUT:-120}"
CC_KEEP_ALIVE="${CC_KEEP_ALIVE:-30s}"
CC_AUTO_SCOPE="${CC_AUTO_SCOPE:-1}"  # prepend scope header to every model prompt
CC_BASH_PROMPT="${CC_BASH_PROMPT:-$CC_HOME/bash_system_prompt.md}"  # system prompt for all `cc bash` calls

mkdir -p "$CC_HOME" "$CC_SCRIPTS" "$CC_CACHE" 2>/dev/null || {
  printf '\033[31mcc: cannot create %s — check permissions\033[0m\n' "$CC_HOME" >&2
  exit 1
}

dim()    { printf '\033[2m%s\033[0m' "$*"; }
red()    { printf '\033[31m%s\033[0m' "$*"; }
green()  { printf '\033[32m%s\033[0m' "$*"; }
yellow() { printf '\033[33m%s\033[0m' "$*"; }
cyan()   { printf '\033[36m%s\033[0m' "$*"; }

# --- robustness: preflight, temp cleanup, signal handling ----------------
# Fail fast with a clear message if a required binary is missing. Better
# than 50 lines down getting "command not found: jq" in the middle of a run.
_cc_require_bin() {
  local missing=() b
  for b in "$@"; do
    command -v "$b" >/dev/null 2>&1 || missing+=("$b")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    printf '\033[31mcc: missing required binaries: %s\033[0m\n' "${missing[*]}" >&2
    printf 'install them and retry. (PATH=%s)\n' "$PATH" >&2
    exit 127
  fi
}
_cc_require_bin python3 curl jq sha256sum awk sed grep mktemp date dirname basename

if [ ! -f "$CC_LIB" ]; then
  printf '\033[31mcc: missing helper %s — reinstall cc\033[0m\n' "$CC_LIB" >&2
  exit 1
fi

# Centralized temp-file tracker. Anything created via _cc_tmp gets removed
# on EXIT/INT/TERM, even if the script is killed mid-run.
CC_TMP_FILES=()
_cc_tmp() {
  local f
  f="$(mktemp "${TMPDIR:-/tmp}/cc.XXXXXX")" || {
    printf '\033[31mcc: mktemp failed\033[0m\n' >&2
    return 1
  }
  CC_TMP_FILES+=("$f")
  printf '%s' "$f"
}
_cc_cleanup() {
  local f
  # `${arr[@]:+...}` is the set-u-safe way to test for non-empty arrays;
  # `${#arr[@]:-0}` is not valid bash syntax.
  if [ -n "${CC_TMP_FILES[*]:+x}" ]; then
    for f in "${CC_TMP_FILES[@]}"; do
      [ -n "${f:-}" ] && rm -f "$f" 2>/dev/null || true
    done
    CC_TMP_FILES=()
  fi
  # Idempotent agent release — guarded against double-fire (explicit call
  # followed by EXIT trap).
  if [ -z "${CC_AGENT_RELEASED:-}" ] && [ -n "${CC_AGENT_UUID:-}" ] \
       && [ -n "${CC_LOCAL_DB:-}" ]; then
    CC_AGENT_RELEASED=1
    CC_DB="$CC_LOCAL_DB" python3 "$CC_LIB" agent-release "$CC_AGENT_UUID" \
      >/dev/null 2>&1 || true
  fi
}
trap _cc_cleanup EXIT
# On INT/TERM: clean up, then re-raise with the conventional signal exit code
# so callers can distinguish "user cancelled" from "command failed".
trap '_cc_cleanup; trap - INT;  exit 130' INT
trap '_cc_cleanup; trap - TERM; exit 143' TERM

# DB helpers — each call targets a specific DB by exporting CC_DB.
G() { CC_DB="$CC_GLOBAL_DB" python3 "$CC_LIB" "$@"; }
L() { CC_DB="$CC_LOCAL_DB" python3 "$CC_LIB" "$@"; }

# initialize global DB once per invocation
G init

# Walk up from $PWD looking for .cc/local.db. Guards against $PWD being
# unset (rare) or pointing at a deleted directory (happens when a parent
# shell rm'd the cwd out from under us).
find_local_db() {
  local dir="${PWD:-}"
  [ -z "$dir" ] && return 1
  [ ! -d "$dir" ] && return 1
  while [ -n "$dir" ] && [ "$dir" != "/" ]; do
    if [ -f "$dir/.cc/local.db" ]; then
      echo "$dir/.cc/local.db"
      return 0
    fi
    local parent
    parent="$(dirname "$dir")"
    # dirname of "/" is "/" — guard against infinite loop.
    [ "$parent" = "$dir" ] && break
    dir="$parent"
  done
  return 1
}

CC_LOCAL_DB="$(find_local_db || true)"
CC_LOCAL_ROOT=""
if [ -n "$CC_LOCAL_DB" ]; then
  CC_LOCAL_ROOT="$(dirname "$(dirname "$CC_LOCAL_DB")")"
  # Initialize/migrate the LOCAL db (creates tables + ALTER-backfills new
  # columns like chain_run_steps.cell_cid/recipe_cid). Without this, an
  # older local.db missing a column would silently drop step persistence.
  L init >/dev/null 2>&1 || true
fi

# Resolve project name from local meta, falling back to global active project.
resolve_project() {
  local local_proj=""
  if [ -n "$CC_LOCAL_DB" ]; then
    local_proj="$(L meta-get project)"
  fi
  local global_proj
  global_proj="$(G active)"
  if [ -n "$local_proj" ]; then echo "$local_proj"; return; fi
  echo "$global_proj"
}

scope_log() {
  local global_proj local_proj
  global_proj="$(G active)"
  local_proj=""
  if [ -n "$CC_LOCAL_DB" ]; then
    local_proj="$(L meta-get project 2>/dev/null || true)"
  fi
  {
    dim "[cc"
    dim " | global: "
    if [ -n "$global_proj" ]; then green "$global_proj"; else red "(none)"; fi
    dim " | local: "
    if [ -n "$local_proj" ]; then
      if [ "$local_proj" = "$global_proj" ]; then
        green "$local_proj"
      else
        red "$local_proj"
        dim " (mismatch — fix with: cc -set-project $local_proj)"
      fi
    else
      red "(unscoped)"
    fi
    dim " | cwd: "
    yellow "$(pwd)"
    dim " | model: "
    yellow "$CC_MODEL"
    dim " | agent: "
    cyan "${CC_AGENT_UUID:0:8}"
    dim "]"
    echo
  } >&2
}

# ---- agent lifecycle ----------------------------------------------------
mkdir -p "$CC_CACHE"
# Prefer the kernel's UUID source — no fork+python startup cost, and still
# works if python3 is somehow broken mid-script. Fall back through python,
# then a pid+epoch+random composite so the script never aborts here.
if [ -r /proc/sys/kernel/random/uuid ]; then
  CC_AGENT_UUID="$(< /proc/sys/kernel/random/uuid)"
elif command -v uuidgen >/dev/null 2>&1; then
  CC_AGENT_UUID="$(uuidgen)"
else
  CC_AGENT_UUID="$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null)" \
    || CC_AGENT_UUID="fallback-$$-$(date +%s)-${RANDOM:-0}${RANDOM:-0}"
fi
export CC_AGENT_UUID

# Export scope env vars so any child process (claude, scripts, etc.) inherits.
export CC_SCOPE_CWD="$PWD"
export CC_SCOPE_LOCAL_ROOT="${CC_LOCAL_ROOT:-}"
export CC_SCOPE_LOCAL_DB="${CC_LOCAL_DB:-}"
export CC_SCOPE_GLOBAL_PROJECT="$(CC_DB="$CC_GLOBAL_DB" python3 "$CC_LIB" active 2>/dev/null || true)"
if [ -n "$CC_LOCAL_DB" ]; then
  export CC_SCOPE_LOCAL_PROJECT="$(CC_DB="$CC_LOCAL_DB" python3 "$CC_LIB" meta-get project 2>/dev/null || true)"
else
  export CC_SCOPE_LOCAL_PROJECT=""
fi

agent_claim() {
  if [ -n "$CC_LOCAL_DB" ]; then
    L agent-claim "$CC_AGENT_UUID" "$$" "$(pwd)" "$*"
  fi
}
agent_update() {
  if [ -n "$CC_LOCAL_DB" ]; then
    L agent-update "$CC_AGENT_UUID" "$*" >/dev/null 2>&1 || true
  fi
}
agent_release() {
  # Idempotent — same guard as _cc_cleanup uses.
  if [ -n "${CC_AGENT_RELEASED:-}" ]; then return 0; fi
  if [ -n "$CC_LOCAL_DB" ]; then
    CC_AGENT_RELEASED=1
    L agent-release "$CC_AGENT_UUID" >/dev/null 2>&1 || true
  fi
}
# EXIT/INT/TERM traps already installed at top via _cc_cleanup (which calls
# agent-release directly). Calling agent_release explicitly before `exec`
# is what lets tui/studio release cleanly.

# ---- deterministic model call -------------------------------------------
# Uses ollama HTTP API with temperature=0, seed=42 by default. Caches by
# sha256(model + prompt + options). Always:
#   - hard-bounds with curl --max-time $CC_MODEL_TIMEOUT (no infinite hangs)
#   - sets keep_alive so models unload promptly (no orphaned 99%-CPU runners)
#   - appends a "DONE" directive — models MUST end with that token, so the
#     orchestrator can tell completion from truncation/abort.
# Returns:
#   0  - response received with DONE; printed (DONE stripped)
#   1  - transport/timeout/empty failure
#   2  - response received but DONE missing — partial. Still printed, cached
#        with a .partial sibling marker; callers may retry or escalate.
scope_header_text() {
  # IMPORTANT: this text becomes part of the prompt AND part of the cache
  # key. Every field here must be deterministic across invocations with
  # the same scope, otherwise caching is broken. Specifically, NEVER add
  # per-invocation values like agent_uuid, pid, or timestamps — they have
  # no semantic value to the model and they destroy cache hit rate.
  local global_proj local_proj
  global_proj="$(G active 2>/dev/null)"
  local_proj=""
  if [ -n "$CC_LOCAL_DB" ]; then
    local_proj="$(L meta-get project 2>/dev/null || true)"
  fi
  cat <<EOF
[Scope from cc — you are constrained to this context]
- project (global): ${global_proj:-(none)}
- project (local):  ${local_proj:-(unscoped)}
- cwd:              $(pwd)
- local_root:       ${CC_LOCAL_ROOT:-(none)}
Only operate within local_root unless explicitly asked otherwise.
EOF
}

model_call() {
  local model="$1" raw_prompt="$2"
  local opts='{"temperature":0,"seed":42}'
  if [ "$CC_DETERMINISTIC" = "0" ]; then opts='{}'; fi

  local scope_block=""
  if [ "$CC_AUTO_SCOPE" = "1" ]; then
    scope_block="$(scope_header_text)

"
  fi

  local prompt="${scope_block}${raw_prompt}

When finished, end your response with the literal token: DONE"

  local key cache_path partial_marker
  key="$(printf '%s\0%s\0%s' "$model" "$opts" "$prompt" | sha256sum | awk '{print $1}')"
  cache_path="$CC_CACHE/$key.txt"
  partial_marker="$CC_CACHE/$key.partial"

  if [ "$CC_DETERMINISTIC" = "1" ] && [ -s "$cache_path" ]; then
    cat "$cache_path"
    [ -f "$partial_marker" ] && return 2 || return 0
  fi

  local body
  body="$(jq -n --arg m "$model" --arg p "$prompt" --argjson o "$opts" --arg ka "$CC_KEEP_ALIVE" \
    '{model:$m, prompt:$p, stream:false, options:$o, keep_alive:$ka}')"

  local resp
  resp="$(curl -sS --max-time "$CC_MODEL_TIMEOUT" "$CC_OLLAMA_URL/api/generate" -d "$body")" || {
    red "ollama call failed or timed out after ${CC_MODEL_TIMEOUT}s" >&2; echo >&2
    return 1
  }
  local text
  text="$(printf '%s' "$resp" | jq -r '.response // empty')"
  if [ -z "$text" ]; then
    # fallback: if the primary model returned empty (e.g. glm-5.2:cloud not served
    # on the local ollama), retry with CC_TINY_MODEL (qwen2.5:3b, which IS available).
    if [ "$model" != "$CC_TINY_MODEL" ] && [ -n "$CC_TINY_MODEL" ]; then
      yellow "empty response from $model — falling back to $CC_TINY_MODEL" >&2; echo >&2
      body="$(jq -n --arg m "$CC_TINY_MODEL" --arg p "$prompt" --argjson o "$opts" --arg ka "$CC_KEEP_ALIVE" \
        '{model:$m, prompt:$p, stream:false, options:$o, keep_alive:$ka}')"
      resp="$(curl -sS --max-time "$CC_MODEL_TIMEOUT" "$CC_OLLAMA_URL/api/generate" -d "$body")" || return 1
      text="$(printf '%s' "$resp" | jq -r '.response // empty')"
      model="$CC_TINY_MODEL"
    fi
    if [ -z "$text" ]; then
      red "empty response from $model" >&2; echo >&2
      printf '%s' "$resp" | jq -r '.error // empty' >&2 || true
      return 1
    fi
  fi

  # Accept DONE as the final token; strip it. Done in Python — bash regex
  # `\b` is unreliable across grep/sed versions for trailing matches.
  local has_done=0
  local stripped done_flag_file
  done_flag_file="$(_cc_tmp)" || return 1
  stripped="$(python3 -c '
import re, sys
t = sys.stdin.read()
m = re.search(r"(^|\s)DONE\s*$", t)
sys.stderr.write("1" if m else "0")
sys.stdout.write(re.sub(r"\s*\bDONE\s*$", "", t))
' <<<"$text" 2>"$done_flag_file")"
  has_done="$(cat "$done_flag_file" 2>/dev/null || echo 0)"
  rm -f "$done_flag_file"
  text="$stripped"

  printf '%s' "$text" > "$cache_path"
  if [ "$has_done" = "0" ]; then
    : > "$partial_marker"
    yellow "WARNING: model did not signal DONE — response treated as partial" >&2; echo >&2
    printf '%s' "$text"
    return 2
  fi
  rm -f "$partial_marker" 2>/dev/null || true
  printf '%s' "$text"
}

require_local() {
  if [ -z "$CC_LOCAL_DB" ]; then
    red "no local cc context — run 'cc -setup' in this folder first" >&2; echo >&2
    exit 1
  fi
}

require_project_global() {
  local p; p="$(G active)"
  if [ -z "$p" ]; then
    red "no active global project — run 'cc -set-project <name>'" >&2; echo >&2
    exit 1
  fi
  printf '%s' "$p"
}

# ---- interactive help system -------------------------
cmd_help() {
  local quiet=0
  if [ "${1:-}" = "-q" ]; then
    quiet=1
    shift
  fi

  # Parse the comment section to build command list
  # Extract full command pattern including hyphens and dots
  local cmd_list
  cmd_list="$(grep "^#   cc " "$0" 2>/dev/null | sed 's/^#   cc //' | sed 's/[[:space:]]*$//' | head -60 | while IFS= read -r line; do
    local cmd desc
    # Extract command - check for options first (-x, --flag), then words
    if echo "$line" | grep -qE '^(-+[-a-z0-9]+)'; then
      cmd="$(echo "$line" | sed -E 's/^(-+[-a-z0-9]+).*/\1/')"
    else
      cmd="$(echo "$line" | sed -E 's/^([a-z][a-z0-9_-]*).*/\1/')"
    fi
    # Extract description (everything after first token)
    desc="$(echo "$line" | sed -E "s/^$cmd[[:space:]]*//")"
    printf '%-25s %s\n' "$cmd" "$desc"
  done | awk '!seen[$1]++')"

  # Display menu
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  cc - Interactive CLI Helper"
  echo "  Model: $CC_TINY_MODEL"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  echo "Available Commands:"
  echo ""
  printf '%-25s %s\n' "COMMAND" "DESCRIPTION"
  printf '%-25s %s\n' "-------" "-----------"
  echo "$cmd_list"

  if [ "$quiet" -eq 1 ]; then
    return 0
  fi

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Type a command name for details, or ask a question"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  local user_input
  echo -n "Command or question: "
  read -r user_input

  if [ -z "$user_input" ]; then
    echo ""
    return 0
  fi

  # Try to match user input to a command
  local matched_cmd=""
  while IFS= read -r line; do
    local cmd desc
    cmd="$(echo "$line" | sed -E 's/^([a-z][a-z0-9_-]*|-[-a-z0-9]+).*/\1/')"
    desc="$(echo "$line" | sed -E "s/^$cmd[[:space:]]*//")"
    if [[ "$cmd" == "$user_input" ]]; then
      matched_cmd="$cmd"
      echo ""
      echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      echo "  Command: $matched_cmd"
      echo "  Description: $desc"
      echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      echo ""
      return 0
    fi
  done <<< "$cmd_list"

  # If no command matched, try to answer as a question using tiny model
  echo ""
  echo "Asking about: $user_input"
  model_call "$CC_TINY_MODEL" "You are a helpful CLI assistant for the 'cc' bash tool. Answer this question about the commands: $user_input. Keep your answer concise and practical."
}

usage() {
  # Print the entire top-of-file comment block. Stops at the first
  # non-comment line, so adding subcommands above doesn't need
  # touching this sed range.
  awk '/^[^#]/ && NR>1 {exit} NR>1 {print}' "$0"
}

# ---- discovery helpers ---------------------------------------------------

discover_venv() {
  for v in .venv venv env .env; do
    if [ -x "$v/bin/python" ]; then echo "$(pwd)/$v"; return; fi
  done
  echo ""
}

discover_repo() {
  if [ -d .git ] || git rev-parse --git-dir >/dev/null 2>&1; then
    git config --get remote.origin.url 2>/dev/null || echo ""
  fi
}

discover_entrypoints() {
  # top-level .py and .sh files (depth 1) + anything in a bin/ or scripts/ subdir at depth 2
  find . -maxdepth 1 -type f \( -name "*.py" -o -name "*.sh" \) 2>/dev/null
  find ./bin ./scripts -maxdepth 1 -type f \( -name "*.py" -o -name "*.sh" \) 2>/dev/null
}

# ---- subcommands ---------------------------------------------------------

cmd_setup() {
  local instruction="$*"

  local root="$(pwd)"
  local lroot="$root/.cc"
  mkdir -p "$lroot"
  CC_LOCAL_DB="$lroot/local.db"
  L init

  local proj_name
  proj_name="$(basename "$root")"

  # detect venv, repo
  local venv repo
  venv="$(discover_venv)"
  repo="$(discover_repo)"

  L meta-set project "$proj_name"
  L meta-set root "$root"
  L meta-set venv "$venv"
  L meta-set repo "$repo"
  L meta-set created_at "$(date -Iseconds)"

  # register project globally with its path
  G set-project "$proj_name" >/dev/null
  G set-project-path "$proj_name" "$root" >/dev/null

  # discover entrypoints
  L entry-clear >/dev/null
  local count=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    local kind="bash"
    case "$f" in *.py) kind="python" ;; *.sh) kind="bash" ;; esac
    local name; name="$(basename "$f")"
    L entry-add "$name" "$f" "$kind" >/dev/null
    count=$((count+1))
  done < <(discover_entrypoints | sort -u)

  G log-action "$proj_name" "$root" "setup" "venv=$venv repo=$repo entries=$count"

  # Auto-maintain a CLAUDE.context.md inside .cc/ and import it from
  # <project>/CLAUDE.md so ANY claude invocation in this dir inherits cc scope.
  local ctx_path="$lroot/CLAUDE.context.md"
  local active_global; active_global="$(G active 2>/dev/null)"
  cat > "$ctx_path" <<EOF
# cc scope — auto-generated, do not edit by hand

You are operating inside the cc terminal manager. The state below is the source
of truth for your scope:

- project (global): ${active_global:-(none)}
- project (local):  $proj_name
- local_root:       $root
- venv:             ${venv:-(none)}
- repo:             ${repo:-(none)}

Constraints:
- Modifications scoped to $root and below unless the user explicitly opts out.
- The cc db at .cc/local.db tracks runs, entrypoints, agents.
- Before doing classification / extraction / summarization / debug, try
  \`cc tiny <prompt>\` first — it's free and deterministic.

For the full live state run: \`cc -context\`.
EOF

  local claude_md="$root/CLAUDE.md"
  local import_line='@.cc/CLAUDE.context.md'
  if [ ! -f "$claude_md" ]; then
    printf '%s\n\n# Project notes\n' "$import_line" > "$claude_md"
    yellow "created $claude_md with cc context import" >&2; echo >&2
  elif ! grep -Fq "$import_line" "$claude_md"; then
    # Prepend the import line.
    local tmp; tmp="$(mktemp)"
    printf '%s\n\n' "$import_line" > "$tmp"
    cat "$claude_md" >> "$tmp"
    mv "$tmp" "$claude_md"
    yellow "added cc context import to $claude_md" >&2; echo >&2
  fi

  green "set up project '$proj_name' at $root" >&2; echo >&2
  echo "  venv:    ${venv:-(none)}"
  echo "  repo:    ${repo:-(none)}"
  echo "  entries: $count"
  echo "  CLAUDE.md context: $ctx_path"

  if [ -n "$instruction" ]; then
    yellow "recording setup instruction as a todo …" >&2; echo >&2
    G add-todo "$proj_name" "[setup] $instruction" >/dev/null
    echo "  todo added: [setup] $instruction"
  fi
}

cmd_scope() {
  local global_proj="$CC_SCOPE_GLOBAL_PROJECT"
  local local_proj="$CC_SCOPE_LOCAL_PROJECT"
  [ -z "$global_proj" ] && global_proj="(none)"
  [ -z "$local_proj" ] && local_proj="(unscoped)"
  cat <<EOF
project (global): $global_proj
project (local):  $local_proj
cwd:              $PWD
local_root:       ${CC_SCOPE_LOCAL_ROOT:-(none)}
local_db:         ${CC_SCOPE_LOCAL_DB:-(none)}
model:            $CC_MODEL
tiny:             $CC_TINY_MODEL
agent_uuid:       $CC_AGENT_UUID
auto_scope:       $CC_AUTO_SCOPE  (set CC_AUTO_SCOPE=0 to disable prompt scope header)
EOF
}

cmd_context() {
  local proj; proj="$(resolve_project)"
  echo "=== cc context ==="
  echo "cwd:          $(pwd)"
  echo "global_proj:  $(G active)"
  echo "local_root:   ${CC_LOCAL_ROOT:-(none)}"
  echo "local_db:     ${CC_LOCAL_DB:-(none)}"
  echo "model:        $CC_MODEL"
  echo "agent_uuid:   $CC_AGENT_UUID"
  echo
  if [ -n "$CC_LOCAL_DB" ]; then
    echo "--- local meta ---"
    L meta-list
    echo
    echo "--- entrypoints ---"
    L entry-list
    echo
    echo "--- recent runs ---"
    L run-list 5
    echo
  fi
  echo "--- todos (global, active project) ---"
  G list-todos
  echo
  echo "--- recent global log ---"
  G show-log 10
}

cmd_agents() {
  require_local
  L agent-list
}

cmd_runs() {
  require_local
  local n=20
  if [ "${1:-}" = "-n" ]; then shift; n="${1:-20}"; fi
  L run-list "$n"
}

cmd_py() {
  require_local
  agent_update "py $*"
  local script="${1:-}"
  [ -z "$script" ] && { red "usage: cc py <script> [args...]" >&2; exit 1; }
  shift || true

  local venv
  venv="$(L meta-get venv)"
  local py
  if [ -n "$venv" ] && [ -x "$venv/bin/python" ]; then
    py="$venv/bin/python"
  else
    py="$(command -v python3 || command -v python)"
  fi
  yellow "running: $py $script $*" >&2; echo >&2

  local tmp_stdout tmp_stderr
  tmp_stdout="$(_cc_tmp)" || exit 1
  tmp_stderr="$(_cc_tmp)" || exit 1
  local rc=0
  "$py" "$script" "$@" >"$tmp_stdout" 2>"$tmp_stderr" || rc=$?

  cat "$tmp_stdout"
  cat "$tmp_stderr" >&2

  local stdout_tail stderr_tail
  stdout_tail="$(tail -c 4000 "$tmp_stdout")"
  stderr_tail="$(tail -c 4000 "$tmp_stderr")"
  L run-add "py" "$py $script $*" "$rc" "$stdout_tail" "$stderr_tail" "$CC_AGENT_UUID"

  local proj; proj="$(resolve_project)"
  G log-action "$proj" "$(pwd)" "py" "rc=$rc $script $*"

  if [ "$rc" -ne 0 ]; then
    echo >&2
    red "exit $rc — invoking diagnose with $CC_MODEL …" >&2; echo >&2
    agent_update "py-diagnose"

    local pip_list git_log
    pip_list="$("$py" -m pip list --format=freeze 2>/dev/null | head -30 || true)"
    git_log="$(git -C "$CC_LOCAL_ROOT" log --oneline -5 2>/dev/null || true)"
    local repo; repo="$(L meta-get repo)"

    local prompt
    prompt="A python script exited with rc=$rc. Diagnose succinctly and propose a fix.

Script: $script $*
Python: $py
Repo:   $repo
Recent commits:
$git_log

Top installed packages:
$pip_list

stderr (last 4KB):
$stderr_tail

stdout (last 4KB):
$stdout_tail

Output rules:
- 2-4 sentences of diagnosis, then a fenced bash block with one command to try.
- If the fix is editing a file, output a bash heredoc that performs the edit, not prose."

    model_call "$CC_MODEL" "$prompt" >&2
    echo >&2
  fi
  rm -f "$tmp_stdout" "$tmp_stderr"
  exit "$rc"
}

cmd_tiny() {
  local model="$CC_TINY_MODEL"
  local mode="prompt"
  while [ $# -gt 0 ]; do
    case "$1" in
      -debug)     mode="debug";     shift ;;
      -summarize) mode="summarize"; shift ;;
      -model)     shift; model="${1:-$CC_TINY_MODEL}"; shift ;;
      *) break ;;
    esac
  done
  local input="$*"
  if [ -z "$input" ] && [ ! -t 0 ]; then
    input="$(cat)"
  fi
  if [ -z "$input" ]; then
    red "usage: cc tiny [-debug|-summarize] <prompt...>" >&2; echo >&2
    exit 1
  fi
  local prompt
  case "$mode" in
    prompt)    prompt="$input" ;;
    debug)     prompt="Given the following command and its stderr/output, propose a minimal fix.
Be terse: one paragraph of diagnosis + one fenced bash block with a single command.

$input" ;;
    summarize) prompt="Summarize the following in 1-3 sentences. Be terse, no preamble.

$input" ;;
  esac
  model_call "$model" "$prompt"
  echo
}

cmd_chain() {
  # cc -chain '<spec>'  — structured multi-step orchestration over local
  # models. Grammar in $CC_INSTALL_ROOT/lib/chain.py:
  #   STEP    {"prompt text"}
  #   GROUP   { EXPR }           inherits context from outside
  #   CCGROUP cc { EXPR }        isolated — does NOT inherit context
  #   OPS     |  pipe (prev → context)
  #           +  parallel (concurrent batch)
  #           -  sequential, context reset
  agent_update "chain"
  if [ "$#" -eq 0 ]; then
    red "usage: cc -chain '<spec>'" >&2; echo >&2
    cat >&2 <<'EOF'

Grammar:
  STEP     {"prompt text"}                       leaf — single model call
  BASH     {bash "command"}                      leaf — run bash, stdout = output
                                                  (context is piped to its stdin)
  GROUP    { EXPR }                              nested expr, inherits context
  CCGROUP  cc { EXPR }                           nested expr, isolated scope
  Operators between terms:
    |    pipe — previous output is prepended as context
    +    parallel — adjacent + terms run concurrently
    -    sequential — runs after previous, no context

Every leaf is content-addressed: its output becomes a cell in the global store
(~/.cc/cc.db), and the recipe (upstream content + op + params) is checked against
the transposition table BEFORE execution. A cache hit short-circuits with zero
model calls / zero bash runs. Inspect with: cc cells-list, cc recipes-stats.

Examples:
  cc -chain '{"summarize this text in one sentence"}'
  cc -chain '{{"draft a haiku"} | {"translate that to French"}}'
  cc -chain '{{"list 3 fruits"} + {"list 3 colors"} + {"list 3 animals"}}'
  cc -chain '{{"what changed?"} | {bash "git diff --stat"}}'
  cc -chain '{{"give me a 100-word product blurb"} | cc {{"critique that blurb"} | {"rewrite it to address the critique"}}}'

Flags:
  --parse <spec>      print AST as JSON, do not call any models
  --dry <spec>        print execution plan, do not call any models
  --trust-bash <spec> actually execute {bash "..."} cells (default: dry-run)
EOF
    exit 1
  fi
  local chain_lib="$CC_INSTALL_ROOT/lib/chain.py"
  if [ ! -f "$chain_lib" ]; then
    red "chain.py not found at $chain_lib" >&2; echo >&2
    exit 1
  fi
  # Export CC_BIN so chain.py knows which binary to shell out to. Prefer
  # the wrapped install path (CC_INSTALL_ROOT/cc) so the child run picks
  # up the same scope/cache root we do.
  local cc_self="$CC_INSTALL_ROOT/cc"
  [ -x "$cc_self" ] || cc_self="$(command -v cc 2>/dev/null || command -v myspace || echo cc)"
  # Pass through "$@" intact so --parse/--dry flags reach argparse.
  CC_BIN="$cc_self" python3 "$chain_lib" "$@"
}

cmd_chain_last() {
  require_local
  L chain-run-last
}

cmd_chain_show() {
  require_local
  local id="${1:-}"
  [ -z "$id" ] && { red "usage: cc -chain-show <id>" >&2; exit 1; }
  L chain-run-show "$id"
}

cmd_chain_list() {
  require_local
  local n=20
  if [ "${1:-}" = "-n" ]; then shift; n="${1:-20}"; fi
  L chain-run-list "$n"
}

# ---- cells / recipes (unified content-addressed cell substrate) ---------
# Global tables (~/.cc/cc.db) — every prompt, bash output, object, and model
# response is a content-addressed cell. cell_store.py is the canonical API;
# these wrappers shell to it. cid = blake3(content); recipe_cid → output_cid
# is the transposition table (cache hit = zero execution).

cmd_cells() {
  local sub="${1:-list}"
  shift || true
  local cs="$CC_INSTALL_ROOT/lib/cell_store.py"
  if [ ! -f "$cs" ]; then red "cell_store.py not found at $cs" >&2; exit 1; fi
  case "$sub" in
    list)    python3 "$cs" list "$@" ;;
    get)     [ -z "${1:-}" ] && { red "usage: cc cells get <cid>" >&2; exit 1; }; python3 "$cs" get "$1" ;;
    query)   [ -z "${1:-}" ] && { red "usage: cc cells query <text> [top_k]" >&2; exit 1; }
             python3 "$cs" query "$1" "${2:-5}" ;;
    embed)   python3 "$cs" embed "${1:-200}" ;;
    add)     # cc cells add <kind> <content> [intent] [source] [project]
             [ -z "${2:-}" ] && { red "usage: cc cells add <kind> <content> [intent] [source] [project]" >&2; exit 1; }
             python3 "$cs" add "$1" "$2" "${3:-}" "${4:-manual}" "${5:-}" ;;
    *)       red "usage: cc cells {list|get|query|embed|add} ..." >&2; exit 1 ;;
  esac
}

cmd_recipes() {
  local sub="${1:-stats}"
  shift || true
  local cs="$CC_INSTALL_ROOT/lib/cell_store.py"
  if [ ! -f "$cs" ]; then red "cell_store.py not found at $cs" >&2; exit 1; fi
  case "$sub" in
    stats)  python3 "$cs" recipe-stats ;;
    get)    [ -z "${1:-}" ] && { red "usage: cc recipes get <recipe_cid>" >&2; exit 1; }; python3 "$cs" recipe-get "$1" ;;
    *)      red "usage: cc recipes {stats|get <cid>}" >&2; exit 1 ;;
  esac
}

# ---- cc loop (autoregressive outer transformer) -------------------------
# cc composes a prompt from retrieved cells, dispatches to the cloud FFN,
# awaits, stores the response as a cell, re-attends, re-dispatches — until
# the task is answered / fixpoint / max_steps. Model + bash steps are
# recipe-cached (zero cloud on a hit). Model = CC_LOOP_MODEL or CC_TINY_MODEL.
cmd_loop() {
  local loop_lib="$CC_INSTALL_ROOT/lib/loop.py"
  if [ ! -f "$loop_lib" ]; then red "loop.py not found at $loop_lib" >&2; exit 1; fi
  CC_BIN="$CC_INSTALL_ROOT/cc" python3 "$loop_lib" "$@"
}

# ---- capability cards & workflow templates --------------------------------
# Global tables — these don't require local scope.

cmd_cards() {
  G card-list
}

cmd_card_show() {
  local op="${1:-}"
  [ -z "$op" ] && { red "usage: cc -card-show <opcode>" >&2; exit 1; }
  G card-get "$op"
}

cmd_card_delete() {
  local op="${1:-}"
  [ -z "$op" ] && { red "usage: cc -card-delete <opcode>" >&2; exit 1; }
  G card-delete "$op"
  green "deleted card: $op" >&2; echo >&2
}

cmd_author_cards() {
  # Pass-through to author_cards.py with CC_GLOBAL_DB exported so the
  # cards land in the global DB (cross-project shared knowledge).
  local script="$CC_INSTALL_ROOT/lib/author_cards.py"
  if [ ! -f "$script" ]; then
    red "author_cards.py not found at $script" >&2; echo >&2
    exit 1
  fi
  agent_update "author-cards $*"
  # Use THIS script's actual path for CC_BIN — works in both repo layout
  # (core/cc) and legacy install (~/.local/bin/cc + ~/.cc/lib/).
  # CC_AUTO_SCOPE=0 suppresses the scope-banner the model otherwise echoes
  # into failure_modes (the tiny model was treating cc's scope rules as
  # part of the prompt context and hallucinating about local_root).
  CC_BIN="$_cc_script_path" \
  CC_DB="$CC_GLOBAL_DB" \
  CC_AUTO_SCOPE=0 \
    python3 "$script" "$@"
}

# ---- GUI cards ------------------------------------------------------------

cmd_gui_cards() {
  G gui-list
}

cmd_gui_show() {
  local op="${1:-}"
  [ -z "$op" ] && { red "usage: cc -gui-show <opcode>" >&2; exit 1; }
  G gui-get "$op"
}

cmd_gui_delete() {
  local op="${1:-}"
  [ -z "$op" ] && { red "usage: cc -gui-delete <opcode>" >&2; exit 1; }
  G gui-delete "$op"
  green "deleted gui card: $op" >&2; echo >&2
}

cmd_author_gui_cards() {
  local script="$CC_INSTALL_ROOT/lib/author_gui.py"
  if [ ! -f "$script" ]; then
    red "author_gui.py not found at $script" >&2; echo >&2
    exit 1
  fi
  agent_update "author-gui-cards $*"
  CC_BIN="$_cc_script_path" \
  CC_DB="$CC_GLOBAL_DB" \
  CC_AUTO_SCOPE=0 \
    python3 "$script" "$@"
}

cmd_authorize_templates() {
  # Claude-authored workflow templates. DEFAULTS TO --dry (no API call,
  # no cost) — the user must pass --execute to actually spend tokens.
  # Reads capability_card + gui_card + path_builder paths for an opcode,
  # asks Claude to compose a workflow_templates row.
  local script="$CC_INSTALL_ROOT/lib/author_templates.py"
  if [ ! -f "$script" ]; then
    red "author_templates.py not found at $script" >&2; echo >&2
    exit 1
  fi
  agent_update "authorize-templates $*"
  CC_BIN="$_cc_script_path" \
  CC_DB="$CC_GLOBAL_DB" \
  CC_AUTO_SCOPE=0 \
    python3 "$script" "$@"
}

# ---- workflow jobs (W4 — browse only; executor not yet built) -----------

cmd_jobs() {
  # Jobs live in the LOCAL DB (per-project). Globally browse via L.
  require_local
  local n=20
  if [ "${1:-}" = "-n" ]; then shift; n="${1:-20}"; fi
  L job-list "$n"
}

cmd_job_show() {
  require_local
  local id="${1:-}"
  [ -z "$id" ] && { red "usage: cc -job-show <id>" >&2; exit 1; }
  L job-show "$id"
}

cmd_job_last() {
  require_local
  L job-last
}

# ---- DAG cache (global, hash-addressed) -----------------------------------

cmd_dag_bootstrap() {
  local script="$CC_INSTALL_ROOT/lib/dag_builder.py"
  if [ ! -f "$script" ]; then
    red "dag_builder.py not found at $script" >&2; echo >&2
    exit 1
  fi
  agent_update "dag-bootstrap"
  CC_DB="$CC_GLOBAL_DB" python3 "$script" bootstrap
}

cmd_dag_status() {
  G dag-status
}

cmd_dag_node() {
  local id="${1:-}"
  [ -z "$id" ] && { red "usage: cc -dag-node <node_id>" >&2; exit 1; }
  G dag-node-get "$id"
}

cmd_dag_chain() {
  local id="${1:-}"
  [ -z "$id" ] && { red "usage: cc -dag-chain <chain_id>" >&2; exit 1; }
  G dag-chain-hit "$id" >/dev/null
  G dag-chain-get "$id"
}

cmd_dag_build() {
  local script="$CC_INSTALL_ROOT/lib/dag_builder.py"
  if [ ! -f "$script" ]; then
    red "dag_builder.py not found at $script" >&2; echo >&2
    exit 1
  fi
  agent_update "dag-build $*"
  CC_DB="$CC_GLOBAL_DB" python3 "$script" work "$@"
}

cmd_dag_enqueue() {
  local script="$CC_INSTALL_ROOT/lib/dag_builder.py"
  if [ ! -f "$script" ]; then
    red "dag_builder.py not found at $script" >&2; echo >&2
    exit 1
  fi
  CC_DB="$CC_GLOBAL_DB" python3 "$script" enqueue "$@"
}

# ---- DAG runtime lookups (zero-compute) -------------------------------

cmd_dag_successors() {
  local op="${1:-}"
  [ -z "$op" ] && { red "usage: cc -dag-successors <opcode> [top]" >&2; exit 1; }
  shift
  G dag-successors "$op" "${1:-5}"
}

cmd_dag_chains_from() {
  local op="${1:-}"
  [ -z "$op" ] && { red "usage: cc -dag-chains-from <opcode> [top]" >&2; exit 1; }
  shift
  G dag-chains-from "$op" "${1:-10}"
}

cmd_dag_chains_pair() {
  local s="${1:-}" d="${2:-}"
  [ -z "$s" ] || [ -z "$d" ] && {
    red "usage: cc -dag-chains <src_mod> <dst_mod> [top]" >&2; exit 1; }
  shift 2 || true
  G dag-chains-pair "$s" "$d" "${1:-10}"
}

cmd_dag_invalidate() {
  local op="${1:-}"
  [ -z "$op" ] && { red "usage: cc -dag-invalidate <opcode>" >&2; exit 1; }
  local script="$CC_INSTALL_ROOT/lib/dag_builder.py"
  if [ ! -f "$script" ]; then
    red "dag_builder.py not found at $script" >&2; echo >&2
    exit 1
  fi
  CC_DB="$CC_GLOBAL_DB" python3 "$script" invalidate "$op"
}

# ─── Studio (DAG canvas + Wardrobe + YouTube cutter) ─────────────────────────
# The studio is a sibling tree to core/ at the repo root, OR ships into
# $HOME/.cc/studio on installed systems. Resolve both.
_resolve_studio_dir() {
  if [ -n "${MYSPACE_STUDIO_DIR:-}" ] && [ -d "$MYSPACE_STUDIO_DIR" ]; then
    echo "$MYSPACE_STUDIO_DIR"; return 0
  fi
  for candidate in \
    "$CC_INSTALL_ROOT/../studio" \
    "$CC_INSTALL_ROOT/studio" \
    "$CC_HOME/studio" \
    "/data/Projects/MySpace++/studio" ; do
    if [ -d "$candidate" ] && [ -f "$candidate/app.py" ]; then
      (cd "$candidate" && pwd); return 0
    fi
  done
  return 1
}

cmd_dag_studio() {
  # Launch the DAG canvas Streamlit app (port 8501+).
  # Distinct from `cc studio` (positional) which launches the CC admin dashboard.
  local dir
  if ! dir="$(_resolve_studio_dir)"; then
    red "studio/ not found. Looked under \$MYSPACE_STUDIO_DIR, \$CC_INSTALL_ROOT/../studio, \$CC_HOME/studio." >&2
    exit 1
  fi
  exec "$dir/run.sh" "$@"
}

cmd_wardrobe() {
  # Launch the Wardrobe Studio Streamlit app (port 8510+).
  local dir
  if ! dir="$(_resolve_studio_dir)"; then
    red "studio/ not found. Looked under \$MYSPACE_STUDIO_DIR, \$CC_INSTALL_ROOT/../studio, \$CC_HOME/studio." >&2
    exit 1
  fi
  exec "$dir/run-wardrobe.sh" "$@"
}

cmd_yt_cut() {
  # Launch the YouTube time-slider cutter (port 8511+).
  local dir
  if ! dir="$(_resolve_studio_dir)"; then
    red "studio/ not found." >&2; exit 1
  fi
  exec "$dir/run_yt_cutter.sh" "$@"
}

cmd_social() {
  # Launch the Social Studio Streamlit app (port 8515+).
  local dir
  if ! dir="$(_resolve_studio_dir)"; then
    red "studio/ not found." >&2; exit 1
  fi
  exec "$dir/run-social.sh" "$@"
}

cmd_social_upload() {
  # CLI batch upload: cc -social-upload <file> --to youtube,telegram,facebook
  local file="${1:-}"
  local targets="${2:-youtube,telegram,facebook}"
  if [ -z "$file" ]; then
    red "usage: cc -social-upload <file> [--to <platforms>]" >&2
    exit 2
  fi
  local dir
  if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 -c "
import sys
sys.path.insert(0, '$dir')
from social.client import UploadClient
c = UploadClient()
results = c.upload('$file', platforms=[p.strip() for p in '$targets'.split(',')])
for r in results:
    status = 'OK' if r.success else 'FAIL'
    print(f'[{status}] {r.platform:12s} → {r.url or r.error or \"-\"}')
" || exit $?
}

cmd_social_dev() {
  # Social platform dev CLI dispatcher: cc -social-dev <platform> <cmd> [args...]
  # Platforms: discord, telegram, facebook, snapchat, livepeer, games
  local plat="${1:-}"
  shift || true
  local dir
  if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  local cli_dir="$dir/social/cli"
  export PYTHONPATH="$dir"
  export PATH="$dir/.bin:$PATH"
  case "$plat" in
    discord)    exec python3 "$cli_dir/discord-cli.py" "$@" ;;
    telegram)   exec python3 "$cli_dir/telegram-cli.py" "$@" ;;
    facebook)   exec python3 "$cli_dir/facebook-cli.py" "$@" ;;
    snapchat)   exec python3 "$cli_dir/snapchat-cli.py" "$@" ;;
    livepeer)   exec python3 "$cli_dir/livepeer-cli.py" "$@" ;;
    x|twitter)  exec python3 "$cli_dir/x-cli.py" "$@" ;;
    games)      exec python3 "$cli_dir/games-cli.py" "$@" ;;
    install)
      bash "$cli_dir/install-clis.sh" "$@"
      ;;
    *)
      red "usage: cc -social-dev <platform> <command> [args...]" >&2
      yellow "Platforms: discord, telegram, facebook, snapchat, livepeer, x (twitter), games" >&2
      yellow "Install binaries: cc -social-dev install [all|livepeer|butler|steamcmd|godot]" >&2
      exit 2
      ;;
  esac
}

cmd_social_oauth() {
  # OAuth 2.0 helper: cc -social-oauth <action> [platform]
  # Actions: start <platform>, status, refresh <platform>, revoke <platform>
  local action="${1:-}"
  local plat="${2:-}"
  local dir
  if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  local bridge_url="${MYSPACE_BRIDGE_URL:-http://localhost:8765}"
  case "$action" in
    start)
      [ -z "$plat" ] && { red "usage: cc -social-oauth start <platform>" >&2; exit 2; }
      curl -s "$bridge_url/oauth/start/$plat" | python3 -m json.tool
      ;;
    status)
      curl -s "$bridge_url/oauth/status" | python3 -m json.tool
      ;;
    refresh)
      [ -z "$plat" ] && { red "usage: cc -social-oauth refresh <platform>" >&2; exit 2; }
      curl -s -X POST "$bridge_url/oauth/refresh/$plat" | python3 -m json.tool
      ;;
    revoke)
      [ -z "$plat" ] && { red "usage: cc -social-oauth revoke <platform>" >&2; exit 2; }
      curl -s -X POST "$bridge_url/oauth/revoke/$plat" | python3 -m json.tool
      ;;
    *)
      red "usage: cc -social-oauth <start|status|refresh|revoke> [platform]" >&2
      yellow "Platforms: google, x, facebook, discord, twitch, tiktok" >&2
      exit 2
      ;;
  esac
}

# ─── Pump.fun dual-GPU ML pipeline ──────────────────────────────────────────

_pump_resolve_dir() {
  local dir
  if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; return 1; fi
  echo "$dir/solana"
}

cmd_pump_feed() {
  # REST polling feed: cc -pump-feed [--rpc URL] [--out PATH] [--poll N]
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  python3 "$dir/pump_feed.py" "$@"
}

cmd_pump_feed_ws() {
  # WebSocket real-time feed: cc -pump-feed-ws [--rpc wss://...]
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  python3 "$dir/pump_ws_feed.py" "$@"
}

cmd_pump_train() {
  # GPU training worker: cc -pump-train [--gpu-train 1] [--data PATH]
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  local gpu="${1:-1}"
  shift || true
  CUDA_VISIBLE_DEVICES="$gpu" python3 "$dir/gpu_trainer.py" --mode train "$@"
}

cmd_pump_infer() {
  # GPU inference worker: cc -pump-infer [--gpu-infer 0] [--checkpoint PATH]
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  local gpu="${1:-0}"
  shift || true
  CUDA_VISIBLE_DEVICES="$gpu" python3 "$dir/gpu_trainer.py" --mode infer "$@"
}

cmd_pump_both() {
  # Run both training + inference: cc -pump-both
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  python3 "$dir/gpu_trainer.py" --mode both "$@"
}

cmd_bot_forensics() {
  # Run bot forensics on collected Pump.fun data: cc -bot-forensics
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  python3 "$dir/bot_forensics.py" \
    --feed "$dir/feed/live_features.jsonl" \
    --report "$dir/feed/bots.jsonl" \
    --summary "$dir/feed/bot_summary.json" \
    "$@"
}

cmd_sui_feed() {
  # Run Sui DEX REST polling feed: cc -sui-feed
  local dir; dir="$(_resolve_studio_dir)" || exit 1
  python3 "$dir/sui/sui_feed.py" \
    --rpc "${SUI_RPC:-${TATUMT_SUI:-https://sui-mainnet-grpc.gateway.tatum.io}}" \
    --out "$dir/sui/feed/live_features.jsonl" \
    "$@"
}

cmd_sui_feed_ws() {
  # Run Sui DEX WebSocket feed: cc -sui-feed-ws
  local dir; dir="$(_resolve_studio_dir)" || exit 1
  python3 "$dir/sui/sui_ws_feed.py" \
    --rpc "${SUI_WS:-${TATUMT_SUI_WS:-wss://sui-mainnet-grpc.gateway.tatum.io}}" \
    --out "$dir/sui/feed/live_features.jsonl" \
    "$@"
}

cmd_sui_train() {
  # Run Sui DEX training on GPU 1: cc -sui-train
  local dir; dir="$(_resolve_studio_dir)" || exit 1
  python3 "$dir/sui/gpu_trainer.py" --mode train \
    --data "$dir/sui/feed/live_features.jsonl" \
    --checkpoint "$dir/sui/models/latest.pt" \
    "$@"
}

cmd_sui_infer() {
  # Run Sui DEX inference on GPU 0: cc -sui-infer
  local dir; dir="$(_resolve_studio_dir)" || exit 1
  python3 "$dir/sui/gpu_trainer.py" --mode infer \
    --checkpoint "$dir/sui/models/latest.pt" \
    "$@"
}

cmd_sui_both() {
  # Run both Sui DEX training + inference: cc -sui-both
  local dir; dir="$(_resolve_studio_dir)" || exit 1
  python3 "$dir/sui/gpu_trainer.py" --mode both \
    --data "$dir/sui/feed/live_features.jsonl" \
    --checkpoint "$dir/sui/models/latest.pt" \
    "$@"
}

cmd_orchestration_map() {
  # Map recursive smart-contract activation patterns: cc -orchestration-map
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  python3 "$dir/orchestration_mapper.py" \
    --feed "$dir/feed/live_features.jsonl" \
    --report "$dir/feed/orchestration.jsonl" \
    --summary "$dir/feed/orchestration_summary.json" \
    "$@"
}

cmd_wallet_grid() {
  # Map the multidimensional wallet activation grid: cc -wallet-grid
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  python3 "$dir/wallet_grid_mapper.py" \
    --feed "$dir/feed/live_features.jsonl" \
    --report "$dir/feed/grid.jsonl" \
    --summary "$dir/feed/grid_summary.json" \
    "$@"
}

cmd_pattern_train() {
  # Train pure-Python MLP on orchestration patterns: cc -pattern-train
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  python3 "$dir/pattern_trainer.py" "$@"
}

cmd_pattern_predict() {
  # Real-time inference on orchestration patterns: cc -pattern-predict
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  python3 "$dir/pattern_predictor.py" "$@"
}

cmd_pattern_dashboard() {
  # Launch Pattern Intelligence Dashboard HTTP server: cc -pattern-dashboard
  local dir; dir="$(_pump_resolve_dir)" || exit 1
  python3 "$dir/dashboard_server.py" "$@"
}

# ─── Studio auth (friend-scoped access control) ─────────────────────────────
cmd_auth_seed() {
  # Generate / refresh permissions.jsonl from the friend list seed.
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  python3 "$dir/auth/seed_permissions.py" "$@"
}

cmd_auth_list() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  python3 "$dir/auth/seed_permissions.py" --list
}

cmd_auth_revoke() {
  local who="${1:-}"
  [ -z "$who" ] && { red "usage: cc -auth-revoke <user>" >&2; exit 2; }
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  python3 "$dir/auth/seed_permissions.py" --reset "$who"
  yellow "Also revoke SSH:  $dir/auth/ssh_friend_setup.sh revoke $who" >&2
}

cmd_auth_grant() {
  # Add a new friend interactively. Appends a seed-style row + re-runs seed.
  local who="${1:-}"
  local pw="${2:-passwd}"
  local em="${3:-friends@Tmail.com}"
  if [ -z "$who" ]; then
    red "usage: cc -auth-grant <user> [passwd] [email]" >&2
    yellow "       defaults: passwd=passwd, email=friends@Tmail.com" >&2
    exit 2
  fi
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  python3 - <<PY
import json, hashlib, os, sys
from pathlib import Path
here = Path("$dir/auth")
sys.path.insert(0, str(here))
import seed_permissions as sp
existing = sp.load_existing()
# Has this user already?
for r in existing:
    if r.get("user") == "$who":
        print("$who already in permissions store — no-op.")
        sys.exit(0)
new = {"user": "$who", "permission": True,
       "passwd_hash": sp.passwd_hash("$pw"),
       "email": "$em", "solo": False, "loopback_only": False,
       "ip_bound": None, "bind_hash": None,
       "first_seen": None, "last_seen": None}
existing.append(new)
sp.write(existing)
print(f"granted: $who (passwd hashed, email=$em, IP unbound)")
PY
  echo
  yellow "Friend's SSH key still needs to be added separately:"
  yellow "  $dir/auth/ssh_friend_setup.sh add $who /path/to/their.pub"
}

cmd_auth_status() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  python3 - <<PY
import json, sys
from pathlib import Path
p = Path("$dir/auth/permissions.jsonl")
if not p.exists():
    print("(no permissions.jsonl yet — run: cc -auth-seed)")
    sys.exit(0)
rows = []
for ln in p.read_text().splitlines():
    ln = ln.strip()
    if not ln or ln.startswith("#"): continue
    try: rows.append(json.loads(ln))
    except Exception: pass
total = len(rows)
bound = sum(1 for r in rows if r.get("ip_bound"))
solo = sum(1 for r in rows if r.get("solo"))
loop = sum(1 for r in rows if r.get("loopback_only"))
print(f"rows: {total}  bound: {bound}  unbound: {total - bound}  solo: {solo}  loopback-only: {loop}")
PY
}

cmd_auth_ssh() {
  # Pass-through to ssh_friend_setup.sh.
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  exec "$dir/auth/ssh_friend_setup.sh" "$@"
}

# ─── Media intake (classify + bg-remove + auto-organize) ────────────────────
cmd_intake() {
  # Classify + place a file under studio/media/<category>. Pass-through to
  # process.py. Usage:
  #   cc -intake <file>              — classify (just prints dest dir)
  #   cc -intake -mv <file>          — classify + move into the dest dir
  #   cc -intake -bgremove <file>    — strip bg, write *_nobg.png
  #   cc -intake -mask <file>        — write binary mask
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  local tool="$dir/media/.tools/process.py"
  [ -f "$tool" ] || { red "process.py not found at $tool" >&2; exit 1; }

  local mode="classify"
  case "${1:-}" in
    -mv)        mode="mv";       shift ;;
    -bgremove)  mode="bgremove"; shift ;;
    -mask)      mode="mask";     shift ;;
  esac
  local file="${1:-}"
  [ -z "$file" ] && { red "usage: cc -intake [-mv|-bgremove|-mask] <file>" >&2; exit 2; }

  if [ "$mode" = "mv" ]; then
    local dest
    dest="$(python3 "$tool" classify "$file")"
    local target_dir="$dir/media/$dest"
    mkdir -p "$target_dir"
    local base; base="$(basename "$file")"
    mv -n "$file" "$target_dir/$base"
    yellow "→ $target_dir/$base" >&2
  elif [ "$mode" = "bgremove" ]; then
    local out="${file%.*}_nobg.png"
    python3 "$tool" bgremove "$file" "$out"
    yellow "→ $out" >&2
  elif [ "$mode" = "mask" ]; then
    local out="${file%.*}_mask.png"
    python3 "$tool" mask "$file" "$out"
    yellow "→ $out" >&2
  else
    python3 "$tool" classify "$file"
  fi
}

cmd_fetch_url() {
  # Pass-through to fetch-url.sh — download, classify, bg-remove.
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  local sh="$dir/media/.tools/fetch-url.sh"
  [ -f "$sh" ] || { red "fetch-url.sh not found at $sh" >&2; exit 1; }
  exec "$sh" "$@"
}

# ─── Salted API-key distribution (claude_guest / pinterest / client) ────────
cmd_keys_distribute() {
  local user="${1:-}" kind="${2:-claude}"
  if [ -z "$user" ]; then
    red "usage: cc -keys-distribute <user> [claude|pinterest|client]" >&2
    exit 2
  fi
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  # Cap claude tokens via the proxy module helper.
  if [ "$kind" = "claude" ]; then
    PYTHONPATH="$dir" python3 -c "
import sys
try:
    from proxy.claude_proxy import assert_distribute_within_cap
    assert_distribute_within_cap('$user')
except RuntimeError as e:
    print(str(e), file=sys.stderr); sys.exit(3)
except ImportError:
    pass  # fastapi not installed — distribute anyway, cap check is best-effort
" || exit $?
  fi
  PYTHONPATH="$dir" python3 -m auth.keys distribute "$user" "$kind"
  yellow "→ share this token with $user ONCE. It cannot be recovered." >&2
}

cmd_keys_list() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 -m auth.keys list "$@"
}

cmd_keys_status() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 -m auth.keys status
}

cmd_keys_revoke() {
  local tid="${1:-}"
  [ -z "$tid" ] && { red "usage: cc -keys-revoke <token-id>" >&2; exit 2; }
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 -m auth.keys revoke "$tid"
}

cmd_keys_verify() {
  local tok="${1:-}"
  [ -z "$tok" ] && { red "usage: cc -keys-verify <token>" >&2; exit 2; }
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 -m auth.keys verify "$tok"
}


# ─── Passes (filetype DAG + import-time inference + pieces index) ───────────
cmd_passes_list() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/passes/registry.py"
}

cmd_passes_dag() {
  # Regenerate studio/docs/PASSES_DAG.md and print its path.
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 -c "
import sys; sys.path.insert(0, '$dir')
from passes import filetype_dag
print(filetype_dag.write_doc())
"
}

cmd_passes_run() {
  local file="${1:-}"
  [ -z "$file" ] && { red "usage: cc -passes-run <file> [--reprocess] [-v]" >&2; exit 2; }
  shift || true
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/media/.tools/import_pipeline.py" "$file" "$@"
}

cmd_passes_search() {
  local q="${1:-}"
  [ -z "$q" ] && { red "usage: cc -passes-search <query> [--kind KIND] [--limit N]" >&2; exit 2; }
  shift || true
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/passes/pieces_index.py" search "$q" "$@"
}

cmd_passes_stats() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/passes/pieces_index.py" stats
}

cmd_passes_timing() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/passes/timing.py"
}

cmd_passes_backfill() {
  # Pass-through to backfill_passes.py — supports --rate, --only, --dry-run, etc.
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/media/.tools/backfill_passes.py" "$@"
}

# ─── Tesseract Renderer (meta-DAG + agent walker) ────────────────────────────
cmd_tesseract_build() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/tesseract/svg.py"
}

cmd_tesseract_status() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/tesseract/walker.py" status
}

cmd_tesseract_walk() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/tesseract/walker.py" next
}

cmd_tesseract_identify() {
  local uid="${1:-}"
  [ -z "$uid" ] && { red "usage: cc -tesseract-identify <uid> --neighbors '[...]' --subjects '{...}'" >&2; exit 2; }
  shift
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/tesseract/walker.py" identify "$uid" "$@"
}

cmd_tesseract_reset() {
  local uid="${1:-}"
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  if [ -z "$uid" ]; then
    yellow "Resetting ALL walk state (no --uid given)…" >&2
    PYTHONPATH="$dir" python3 "$dir/tesseract/walker.py" reset
  else
    PYTHONPATH="$dir" python3 "$dir/tesseract/walker.py" reset --uid "$uid"
  fi
}

cmd_tesseract_project() {
  local pt="${1:-}"
  [ -z "$pt" ] && { red "usage: cc -tesseract-project <project-type>" >&2; exit 2; }
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/tesseract/projects.py" "$pt"
}

cmd_tesseract_plan() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/tesseract/plan.py" "${1:-list}" "${@:2}"
}

cmd_tesseract_plan_seed() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/tesseract/plan.py" seed
}

cmd_tesseract_open() {
  # Open the SVG in the platform-default viewer.
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  local svg="$dir/docs/Tesseract.svg"
  [ -f "$svg" ] || { yellow "no SVG yet — run: cc -tesseract-build" >&2; exit 1; }
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$svg"
  elif command -v open >/dev/null 2>&1; then open "$svg"
  else echo "$svg"; fi
}

# ─── WEAVE — cross-device compute fabric ─────────────────────────────────────
cmd_weave_seed() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/weave/topology.py" seed
  PYTHONPATH="$dir" python3 "$dir/weave/plans.py" seed
}

cmd_weave_status() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 -c "
import importlib, json
top = importlib.import_module('weave.topology')
print(json.dumps(top.snapshot()['totals'], indent=2))
"
}

cmd_weave_devices() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/weave/topology.py" online
}

cmd_weave_plans() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/weave/plans.py" list
}

cmd_weave_route() {
  # cc -weave-route <pass-id> [cost-class] [--import-time]
  local pass_id="${1:-mask}"; shift || true
  local cost_class="${1:-HEAVY}"; shift || true
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 "$dir/weave/routing.py" \
    --pass-id "$pass_id" --cost-class "$cost_class" "$@"
}

cmd_weave_jobs() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 -c "
import sqlite3, json, importlib
plans = importlib.import_module('weave.plans')
db = sqlite3.connect(plans.DB_PATH)
rows = db.execute(
    'SELECT ts, pass_id, file_kind, plan_id, decision FROM plan_evaluations '
    'WHERE fired=1 ORDER BY eval_id DESC LIMIT 20'
).fetchall()
db.close()
print(f'{\"ts\":<22} {\"pass_id\":<14} {\"ext\":<5} {\"plan_id\":<26} dev')
print('-' * 96)
for ts, pid, fk, plan_id, decision in rows:
    try: d = json.loads(decision or '{}')
    except Exception: d = {}
    dev = d.get('device_name') or '(deferred)'
    print(f'{ts:<22} {pid or \"-\":<14} {fk or \"-\":<5} {plan_id or \"-\":<26} {dev}')
"
}

cmd_weave_server_start() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  local port="${PORT:-8540}"
  if [ ! -x "$dir/.venv/bin/uvicorn" ]; then
    yellow "Studio venv missing uvicorn — bootstrapping…" >&2
    [ -d "$dir/.venv" ] || python3 -m venv "$dir/.venv"
    "$dir/.venv/bin/pip" install --disable-pip-version-check \
      fastapi 'uvicorn[standard]' >&2
  fi
  yellow "WEAVE relay → http://0.0.0.0:$port (worker page at /, WS at /worker/ws)" >&2
  cd "$dir" && PYTHONPATH="$dir" exec "$dir/.venv/bin/uvicorn" \
    weave.weave_server:app --host 0.0.0.0 --port "$port"
}

cmd_weave_reset() {
  # Drop the topology table — fresh start for testing.
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  PYTHONPATH="$dir" python3 -c "
import sqlite3, importlib
top = importlib.import_module('weave.topology')
with sqlite3.connect(top.DB_PATH) as c:
    c.execute('DELETE FROM devices')
    c.execute('DELETE FROM webgpu_adapters')
print('weave topology cleared')
"
}

cmd_proxy_start() {
  # Launch the Claude guest-pass proxy on port 8520 (overridable via PORT).
  local dir; if ! dir="$(_resolve_studio_dir)"; then red "studio/ not found." >&2; exit 1; fi
  local port="${PORT:-8520}"
  if [ ! -x "$dir/.venv/bin/uvicorn" ]; then
    yellow "Studio venv missing uvicorn — bootstrapping…" >&2
    [ -d "$dir/.venv" ] || python3 -m venv "$dir/.venv"
    "$dir/.venv/bin/pip" install --disable-pip-version-check -r "$dir/proxy/requirements.txt" >&2
  fi
  yellow "Claude guest-pass proxy → http://0.0.0.0:$port" >&2
  cd "$dir" && exec "$dir/.venv/bin/uvicorn" \
    proxy.claude_proxy:app --host 0.0.0.0 --port "$port"
}

cmd_template_walk() {
  # Dry-run walk of a workflow template — shows per-step GUI prediction,
  # bind validation, HITL gates, branch logic. NO model calls, NO cost.
  local name="${1:-}"
  local script="$CC_INSTALL_ROOT/lib/template_walker.py"
  if [ ! -f "$script" ]; then
    red "template_walker.py not found at $script" >&2; echo >&2
    exit 1
  fi
  if [ -z "$name" ]; then
    CC_DB="$CC_GLOBAL_DB" python3 "$script"
    return
  fi
  CC_DB="$CC_GLOBAL_DB" python3 "$script" "$name"
}

cmd_templates() {
  G template-list
}

cmd_template_show() {
  local name="${1:-}"
  [ -z "$name" ] && { red "usage: cc -template-show <name>" >&2; exit 1; }
  G template-show "$name"
}

cmd_template_delete() {
  local name="${1:-}"
  [ -z "$name" ] && { red "usage: cc -template-delete <name>" >&2; exit 1; }
  G template-delete "$name"
  green "deleted template: $name" >&2; echo >&2
}

cmd_claude_import() {
  require_local
  local proj; proj="$(resolve_project)"
  # encode cwd: every / -> -
  local encoded; encoded="${PWD//\//-}"
  local src_dir="$HOME/.claude/projects/$encoded"
  if [ ! -d "$src_dir" ]; then
    yellow "no Claude sessions at $src_dir" >&2; echo >&2
    return 0
  fi

  local imported=0 skipped=0 errors=0
  # Scope nullglob to this loop only — restore prior state afterwards so
  # nothing else in the script trips over a sticky shell option.
  local _prev_nullglob=0
  shopt -q nullglob && _prev_nullglob=1
  shopt -s nullglob
  for jsonl in "$src_dir"/*.jsonl; do
    [ -f "$jsonl" ] || continue
    local session_id content_hash
    session_id="$(basename "$jsonl" .jsonl)"
    content_hash="$(sha256sum "$jsonl" | awk '{print $1}')"

    if [ -n "$(G chat-exists-by-hash "$content_hash")" ]; then
      skipped=$((skipped+1))
      continue
    fi

    # Parse jsonl metadata via jq — robust to empty/malformed lines.
    local started finished branch forked msg_count
    started="$(head -1 "$jsonl" | jq -r '.timestamp // ""' 2>/dev/null)"
    finished="$(tail -1 "$jsonl" | jq -r '.timestamp // ""' 2>/dev/null)"
    branch="$(head -1 "$jsonl" | jq -r '.gitBranch // ""' 2>/dev/null)"
    forked="$(head -1 "$jsonl" | jq -r '.forkedFrom // ""' 2>/dev/null)"
    msg_count="$(grep -c '"type":"user"\|"type":"assistant"' "$jsonl" || echo 0)"

    local new_id
    new_id="$(G chat-add "$proj" "$PWD" "$session_id" "import" \
              "" "$started" "$finished" "$msg_count" "$jsonl" \
              "$branch" "$forked" "$content_hash")"
    if [ -n "$new_id" ]; then
      imported=$((imported+1))
      echo "  + #$new_id  $session_id  msgs=$msg_count  ($started)"
    else
      errors=$((errors+1))
    fi
  done
  [ "$_prev_nullglob" = "0" ] && shopt -u nullglob
  green "imported $imported, skipped $skipped, errors $errors" >&2; echo >&2
}

cmd_chat() {
  require_local
  agent_update "chat $*"
  local proj; proj="$(resolve_project)"
  local mode="full"
  local tier_override=""

  while [ $# -gt 0 ]; do
    case "$1" in
      --route-only)   mode="route";   shift ;;
      --enhance-only) mode="enhance"; shift ;;
      --chain-only)   mode="chain";   shift ;;
      --godot)        mode="godot";   shift ;;
      --master)       mode="master";  shift ;;
      --slice)        mode="slice";   shift ;;
      --tier)         tier_override="$2"; shift 2 ;;
      --tier=*)       tier_override="${1#*=}"; shift ;;
      *) break ;;
    esac
  done

  local prompt="$*"
  if [ -z "$prompt" ]; then
    yellow "reading prompt from stdin (Ctrl-D to finish)…" >&2; echo >&2
    prompt="$(cat)"
  fi
  [ -z "$prompt" ] && { red "usage: cc chat [--route-only|--enhance-only|--chain-only|--godot|--master|--slice] [prompt...]" >&2; exit 1; }

  # Ensure the keyword indices exist once.
  local chat_lib="$CC_INSTALL_ROOT/lib/chat.py"
  if [ ! -f "$chat_lib" ]; then
    red "missing $chat_lib — chat subsystem not installed" >&2; exit 1
  fi

  local chat_env="$CC_CACHE/chat_env"
  mkdir -p "$chat_env"
  export CC_TIMESTAMP="$(date -Iseconds)"
  export CC_CHAT_TIER="$tier_override"

  yellow "cc chat ($mode) → routing + enhancing…" >&2; echo >&2

  case "$mode" in
    enhance)
      python3 "$chat_lib" enhance "$prompt"
      ;;
    route)
      python3 "$chat_lib" route "$prompt"
      ;;
    chain)
      python3 "$chat_lib" chain "$prompt"
      ;;
    godot)
      python3 "$chat_lib" godot "$prompt"
      ;;
    master)
      python3 "$chat_lib" chain "$prompt"
      ;;
    slice)
      python3 "$chat_lib" chain "$prompt"
      ;;
    full)
      local result
      result="$(python3 "$chat_lib" full "$prompt")"
      printf '%s\n' "$result"

      # Log to local DB
      local tier model tokens
      tier="$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["route"]["tier"])')"
      model="$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["route"]["model"])')"
      tokens="$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tokens"])')"

      L run-add "chat-$mode" "cc chat: tier=$tier model=$model tokens=$tokens" "0" "$result" "" "$CC_AGENT_UUID"
      G log-action "$proj" "$(pwd)" "chat" "tier=$tier model=$model tokens=$tokens"
      ;;
  esac
}

# ---- inference crystal chain ---------------------------------------------

cmd_inference_chain() {
  local n="${1:-20}"
  python3 "$CC_INSTALL_ROOT/lib/inference_logger.py" chain -n "$n"
}

cmd_inference_verify() {
  python3 "$CC_INSTALL_ROOT/lib/inference_logger.py" verify
}

cmd_inference_search() {
  local query="$*"
  [ -z "$query" ] && { red "usage: cc inference-search <query>" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/inference_logger.py" search "$query"
}

cmd_inference_get() {
  local cid="${1:-}"
  [ -z "$cid" ] && { red "usage: cc inference-get <crystal_id>" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/inference_logger.py" get "$cid"
}

# ---- workflow_card generator (renamed to avoid kimi's cmd_workflow) ----

cmd_workflow_card() {
  local sub="${1:-}"
  [ -z "$sub" ] && { red "usage: cc workflow-card {generate|crystal|list|show} ..." >&2; exit 1; }
  shift

  local workflows_dir="$CC_INSTALL_ROOT/../studio/assets/_workflows"
  # Try both packaged + repo-relative layouts
  [ -d "$workflows_dir" ] || workflows_dir="/data/Projects/MySpace++/studio/assets/_workflows"

  case "$sub" in
    list)
      yellow "workflow cards in $workflows_dir:" >&2; echo >&2
      find "$workflows_dir" -maxdepth 1 -name '*.json' -type f 2>/dev/null | sort | while read -r f; do
        python3 -c "
import json
d = json.load(open('$f'))
print(f\"  {d.get('name','?'):<32} {d.get('category','?'):<14} {d.get('state','?'):<8} {d.get('version','?')}\")
" 2>/dev/null
      done
      ;;
    show)
      local nm="${1:-}"; [ -z "$nm" ] && { red "usage: cc workflow show <name>" >&2; exit 1; }
      local match
      match="$(find "$workflows_dir" -maxdepth 1 -name "*.${nm}.*.json" -o -name "*${nm}*.json" 2>/dev/null | head -1)"
      [ -z "$match" ] && { red "no card matching '$nm'" >&2; exit 1; }
      python3 -c "import json,sys; print(json.dumps(json.load(open('$match')), indent=2))"
      ;;
    crystal)
      local card="${1:-}"; [ -z "$card" ] && { red "usage: cc workflow crystal <card_path>" >&2; exit 1; }
      [ ! -f "$card" ] && card="$workflows_dir/$card"
      python3 "$CC_INSTALL_ROOT/lib/workflow_generator.py" crystal "$card"
      ;;
    generate)
      local card="${1:-}"; [ -z "$card" ] && { red "usage: cc workflow generate <card_path> [--target ...]" >&2; exit 1; }
      shift
      [ ! -f "$card" ] && card="$workflows_dir/$card"
      [ ! -f "$card" ] && { red "card not found: $card" >&2; exit 1; }
      python3 "$CC_INSTALL_ROOT/lib/workflow_generator.py" generate "$card" "$@"
      ;;
    *)
      red "unknown workflow subcommand: $sub" >&2; exit 1
      ;;
  esac
}

# ---- queue / GPU / cache --------------------------------------------------

cmd_queue_status() {
  python3 -c "
import asyncio, json, sys
sys.path.insert(0, '$CC_INSTALL_ROOT/lib')
from task_queue import TaskQueue
async def run():
    q = TaskQueue()
    print(json.dumps(q.status(), indent=2))
asyncio.run(run())
"
}

cmd_gpu_status() {
  python3 "$CC_INSTALL_ROOT/lib/gpu_scheduler.py" status
  yellow "---nvidia-smi reality check:---" >&2
  python3 "$CC_INSTALL_ROOT/lib/gpu_scheduler.py" verify 2>/dev/null || yellow "(nvidia-smi unavailable)" >&2
}

cmd_cache_stats() {
  python3 "$CC_INSTALL_ROOT/lib/result_cache.py" stats
}

# ---- indexers (drive the bash scanners) ----------------------------------

cmd_comfy_index() {
  local target="${1:-/data/Projects/ComfyUI}"
  yellow "indexing ComfyUI at $target → ~/.cc/comfy_dag.jsonl" >&2
  bash "$CC_INSTALL_ROOT/scripts/comfy_dag.sh" "$target" > "$HOME/.cc/comfy_dag.jsonl"
  green "comfy_dag.jsonl: $(wc -l < "$HOME/.cc/comfy_dag.jsonl") lines" >&2
}

cmd_models_index() {
  yellow "indexing models → ~/.cc/model_index.jsonl" >&2
  bash "$CC_INSTALL_ROOT/scripts/model_index.sh" "$@" > "$HOME/.cc/model_index.jsonl"
  green "model_index.jsonl: $(wc -l < "$HOME/.cc/model_index.jsonl") lines" >&2
}

cmd_datasets_index() {
  yellow "indexing datasets → ~/.cc/datasets_index.jsonl" >&2
  bash "$CC_INSTALL_ROOT/scripts/datasets_index.sh" "$@" > "$HOME/.cc/datasets_index.jsonl"
  green "datasets_index.jsonl: $(wc -l < "$HOME/.cc/datasets_index.jsonl") lines" >&2
}

cmd_scan_projects() {
  [ $# -eq 0 ] && { red "usage: cc scan-projects <root1> [root2 ...]" >&2; exit 1; }
  yellow "scanning projects → ~/.cc/project_scan_chain.jsonl" >&2
  bash "$CC_INSTALL_ROOT/scripts/scan_chain.sh" "$@" > "$HOME/.cc/project_scan_chain.jsonl"
  green "project_scan_chain.jsonl: $(wc -l < "$HOME/.cc/project_scan_chain.jsonl") lines" >&2
}

cmd_ops_dag() {
  local sub="${1:-summary}"
  shift || true
  python3 "$CC_INSTALL_ROOT/lib/ops_dag.py" "$sub" "$@"
}

cmd_studio_run() {
  local card="${1:-}"
  shift || true
  [ -z "$card" ] && { red "usage: cc studio-run <card_name> [--dry-run] [--json]" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/studio_runtime.py" run "$card" "$@"
}

cmd_studio_list() {
  python3 "$CC_INSTALL_ROOT/lib/studio_runtime.py" list
}

cmd_dialectic_walk() {
  local sub="${1:-summary}"
  shift || true
  python3 "$CC_INSTALL_ROOT/lib/dialectic_walker.py" "$sub" "$@"
}

# ---- HuggingFace Hub + 19 Inference Providers --------------------------

cmd_hf_search() {
  local query="$*"
  [ -z "$query" ] && { red "usage: cc hf-search <query> [--limit N] [--task <tag>]" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/hf_hub.py" search-models "$query"
}

cmd_hf_card() {
  local model="${1:-}"
  [ -z "$model" ] && { red "usage: cc hf-card <org/model_id>" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/hf_hub.py" model-card "$model"
}

cmd_hf_datasets() {
  python3 "$CC_INSTALL_ROOT/lib/hf_hub.py" list-datasets "$@"
}

cmd_hf_infer() {
  local model="${1:-}"
  shift || true
  local prompt="${1:-}"
  shift || true
  [ -z "$model" ] || [ -z "$prompt" ] && { red "usage: cc hf-infer <org/model> <prompt> [--provider groq] [--max-tokens N]" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/hf_hub.py" infer "$model" "$prompt" "$@"
}

cmd_hf_stream() {
  local ds="${1:-}"
  shift || true
  [ -z "$ds" ] && { red "usage: cc hf-stream <dataset_id> [--split train] [--limit N]" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/hf_hub.py" stream-dataset "$ds" "$@"
}

cmd_hf_providers() {
  python3 "$CC_INSTALL_ROOT/lib/hf_hub.py" providers
}

# ---- model installer (HF + Ollama unified) -----------------------------

cmd_model_search() {
  local query="$*"
  [ -z "$query" ] && { red "usage: cc model-search <query>" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/model_installer.py" search "$query"
}

cmd_model_install() {
  local source="" model_id="" category="" subtype="" display_name="" tags=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --hf)       source="hf"; model_id="$2"; shift 2 ;;
      --ollama)   source="ollama"; model_id="$2"; shift 2 ;;
      --category) category="$2"; shift 2 ;;
      --subtype)  subtype="$2"; shift 2 ;;
      --display-name) display_name="$2"; shift 2 ;;
      --tags)     tags="$2"; shift 2 ;;
      *) break ;;
    esac
  done
  [ -z "$source" ] && { red "usage: cc model-install --hf <repo> | --ollama <name> --category <cat> --subtype <sub>" >&2; exit 1; }
  [ -z "$category" ] && { red "usage: cc model-install ... --category <cat>" >&2; exit 1; }
  [ -z "$subtype" ] && { red "usage: cc model-install ... --subtype <sub>" >&2; exit 1; }

  local extra_args=()
  [ -n "$display_name" ] && extra_args+=("--display-name" "$display_name")
  [ -n "$tags" ] && extra_args+=("--tags" "$tags")

  if [ "$source" = "hf" ]; then
    python3 "$CC_INSTALL_ROOT/lib/model_installer.py" install \
      --hf "$model_id" --category "$category" --subtype "$subtype" "${extra_args[@]}"
  else
    python3 "$CC_INSTALL_ROOT/lib/model_installer.py" install \
      --ollama "$model_id" --category "$category" --subtype "$subtype" "${extra_args[@]}"
  fi
}

cmd_model_list() {
  local brand="" category="" subtype=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --brand)    brand="$2"; shift 2 ;;
      --category) category="$2"; shift 2 ;;
      --subtype)  subtype="$2"; shift 2 ;;
      *) break ;;
    esac
  done
  local args=()
  [ -n "$brand" ] && args+=("--brand" "$brand")
  [ -n "$category" ] && args+=("--category" "$category")
  [ -n "$subtype" ] && args+=("--subtype" "$subtype")
  python3 "$CC_INSTALL_ROOT/lib/model_installer.py" list "${args[@]}"
}

cmd_model_taxonomy() {
  python3 "$CC_INSTALL_ROOT/lib/model_installer.py" taxonomy
}

cmd_model_sync() {
  python3 "$CC_INSTALL_ROOT/lib/model_installer.py" sync-registry
}

# deck — pointer-first HF model deck (clone stubs fast, stage LFS pulls). See ATLAS/bin/deck.
cmd_deck() {
  "${ATLAS_DECK_BIN:-/data/Projects/ATLAS/bin/deck}" "$@"
}

# ---- third_party management -----------------------------------------------

cmd_third_party_connect() {
  python3 "$CC_INSTALL_ROOT/lib/third_party_cli.py" connect "$@"
}

cmd_third_party_send() {
  python3 "$CC_INSTALL_ROOT/lib/third_party_cli.py" send "$@"
}

cmd_third_party_list() {
  python3 "$CC_INSTALL_ROOT/lib/third_party_cli.py" list "$@"
}

cmd_third_party_status() {
  python3 "$CC_INSTALL_ROOT/lib/third_party_cli.py" status "$@"
}

cmd_third_party_archive() {
  python3 "$CC_INSTALL_ROOT/lib/third_party_cli.py" archive "$@"
}

# ---- endpoints (inbound) ----------------------------------------------------

cmd_endpoint_start() {
  python3 "$CC_INSTALL_ROOT/lib/endpoints_cli.py" start "$@"
}

cmd_endpoint_stop() {
  python3 "$CC_INSTALL_ROOT/lib/endpoints_cli.py" stop "$@"
}

cmd_endpoint_list() {
  python3 "$CC_INSTALL_ROOT/lib/endpoints_cli.py" list "$@"
}

cmd_endpoint_status() {
  python3 "$CC_INSTALL_ROOT/lib/endpoints_cli.py" status "$@"
}

cmd_endpoint_sync() {
  python3 "$CC_INSTALL_ROOT/lib/endpoints_cli.py" sync "$@"
}

# ---- routing operator ------------------------------------------------------

cmd_route_add() {
  python3 "$CC_INSTALL_ROOT/lib/endpoints_cli.py" route-add "$@"
}

cmd_route_list() {
  python3 "$CC_INSTALL_ROOT/lib/endpoints_cli.py" route-list "$@"
}

cmd_route_test() {
  python3 "$CC_INSTALL_ROOT/lib/endpoints_cli.py" route-test "$@"
}

cmd_route_archive() {
  python3 "$CC_INSTALL_ROOT/lib/endpoints_cli.py" route-archive "$@"
}

# --- agent helpers --------------------------------------------------------

# Render an agent's prompt template against a vars-json. Echo the rendered
# prompt on stdout, along with the resolved model on stderr (one line "MODEL=…").
agent_render() {
  local agent_name="$1" vars_json="$2"
  CC_DB="$CC_GLOBAL_DB" python3 - "$agent_name" "$vars_json" <<'PY'
import os, sys, sqlite3, json, re
from pathlib import Path
db = Path(os.environ['CC_DB'])
agent_name = sys.argv[1]
vars_obj = json.loads(sys.argv[2]) if sys.argv[2] else {}
c = sqlite3.connect(str(db))
r = c.execute(
    "SELECT model, prompt_template FROM agent_defs WHERE name=?",
    (agent_name,),
).fetchone()
if not r:
    sys.exit(f"no agent: {agent_name}")
model, tmpl = r
for k, v in vars_obj.items():
    tmpl = re.sub(r'\$\{' + re.escape(k) + r'\}', str(v), tmpl)
    tmpl = re.sub(r'\$' + re.escape(k) + r'(?!\w)', str(v), tmpl)
sys.stderr.write(f"MODEL={model}\n")
sys.stdout.write(tmpl)
PY
}

# Build a JSON object from -var key=value pairs the user passed in.
vars_to_json() {
  python3 -c '
import sys, json
out = {}
for a in sys.argv[1:]:
    if "=" in a:
        k, v = a.split("=", 1)
        out[k] = v
print(json.dumps(out))
' "$@"
}

# Merge new key/value into existing vars-json.
vars_merge() {
  local vars_json="$1" key="$2" value="$3"
  python3 -c '
import sys, json
vj, k, v = sys.argv[1], sys.argv[2], sys.argv[3]
obj = json.loads(vj) if vj else {}
obj[k] = v
print(json.dumps(obj))
' "$vars_json" "$key" "$value"
}

cmd_agent() {
  local sub="${1:-}"; shift || true
  case "$sub" in
    define)
      local name="${1:-}"; shift || true
      local model="$CC_TINY_MODEL"
      local desc=""
      while [ $# -gt 0 ]; do
        case "$1" in
          -model) shift; model="${1:-$CC_TINY_MODEL}"; shift ;;
          --)     shift; desc="$*"; break ;;
          *)      desc="$*"; break ;;
        esac
      done
      [ -z "$name" ] && { red "usage: cc agent define <name> [-model <m>] [-- <description>] <stdin: prompt template>" >&2; exit 1; }
      local tmpl; tmpl="$(cat)"
      [ -z "$tmpl" ] && { red "no prompt template on stdin" >&2; exit 1; }
      G agent-def "$name" "$model" "$tmpl" "$desc"
      green "agent '$name' defined (model=$model)" >&2; echo >&2
      ;;
    list)   G agent-def-list ;;
    show)
      local name="${1:-}"
      [ -z "$name" ] && { red "usage: cc agent show <name>" >&2; exit 1; }
      G agent-def-get "$name"
      ;;
    delete)
      local name="${1:-}"
      [ -z "$name" ] && { red "usage: cc agent delete <name>" >&2; exit 1; }
      G agent-def-delete "$name"
      green "agent '$name' deleted" >&2; echo >&2
      ;;
    run)
      local name="${1:-}"; shift || true
      [ -z "$name" ] && { red "usage: cc agent run <name> [-var k=v ...]" >&2; exit 1; }
      local -a kvargs=()
      while [ $# -gt 0 ]; do
        case "$1" in
          -var) shift; kvargs+=("$1"); shift ;;
          *) break ;;
        esac
      done
      local vars_json; vars_json="$(vars_to_json "${kvargs[@]}")"
      local rendered model model_flag
      model_flag="$(_cc_tmp)" || exit 1
      rendered="$(agent_render "$name" "$vars_json" 2>"$model_flag")"
      model="$(awk -F= '/^MODEL=/{print $2}' "$model_flag")"
      rm -f "$model_flag"
      [ -z "$model" ] && { red "no model resolved for agent $name" >&2; exit 1; }
      agent_update "agent run: $name"
      model_call "$model" "$rendered"
      local rc=$?
      echo
      exit "$rc"
      ;;
    "")    red "usage: cc agent <define|list|show|delete|run>" >&2; echo >&2; exit 1 ;;
    *)     red "unknown agent subcommand: $sub" >&2; echo >&2; exit 1 ;;
  esac
}

cmd_swarm() {
  local sub="${1:-}"; shift || true
  case "$sub" in
    define)
      local name="${1:-}"; shift || true
      local loop_until="" max_iters=10
      while [ $# -gt 0 ]; do
        case "$1" in
          -loop-until) shift; loop_until="${1:-}"; shift ;;
          -max-iters)  shift; max_iters="${1:-10}"; shift ;;
          --)          shift; break ;;
          *)           break ;;
        esac
      done
      local desc="$*"
      [ -z "$name" ] && { red "usage: cc swarm define <name> [-loop-until TOK] [-max-iters N] [-- <desc>] <stdin: steps JSON>" >&2; exit 1; }
      local steps_json; steps_json="$(cat)"
      [ -z "$steps_json" ] && { red "no steps JSON on stdin" >&2; exit 1; }
      printf '%s' "$steps_json" | jq . >/dev/null 2>&1 || { red "invalid steps JSON" >&2; exit 1; }
      G swarm-def "$name" "$desc" "$steps_json" "$loop_until" "$max_iters"
      green "swarm '$name' defined (max_iters=$max_iters loop_until='${loop_until}')" >&2; echo >&2
      ;;
    list)  G swarm-def-list ;;
    show)
      local name="${1:-}"
      [ -z "$name" ] && { red "usage: cc swarm show <name>" >&2; exit 1; }
      G swarm-def-get "$name" | jq .
      ;;
    last) G swarm-run-last ;;
    show-run)
      local rid="${1:-}"
      [ -z "$rid" ] && { red "usage: cc swarm show-run <id>" >&2; exit 1; }
      G swarm-run-show "$rid"
      ;;
    run)
      local name="${1:-}"; shift || true
      [ -z "$name" ] && { red "usage: cc swarm run <name> [-var k=v ...]" >&2; exit 1; }
      local -a kvargs=()
      while [ $# -gt 0 ]; do
        case "$1" in
          -var) shift; kvargs+=("$1"); shift ;;
          *) break ;;
        esac
      done
      local vars_json; vars_json="$(vars_to_json "${kvargs[@]}")"

      # fetch swarm def as JSON
      local raw; raw="$(G swarm-def-get "$name")" || exit 1
      local desc steps_json loop_until max_iters
      desc="$(printf '%s' "$raw" | jq -r '.description')"
      steps_json="$(printf '%s' "$raw" | jq -c '.steps')"
      loop_until="$(printf '%s' "$raw" | jq -r '.loop_until')"
      max_iters="$(printf '%s' "$raw" | jq -r '.max_iters')"

      yellow "swarm: $name  ($desc)  loop_until='$loop_until' max_iters=$max_iters" >&2; echo >&2

      local run_id
      run_id="$(G swarm-run-start "$name" "$vars_json" "$CC_AGENT_UUID")"
      agent_update "swarm $name run #$run_id"

      local iter=0 status="done"
      while [ "$iter" -lt "$max_iters" ]; do
        iter=$((iter+1))
        yellow "--- iteration $iter ---" >&2; echo >&2
        local n_steps
        n_steps="$(printf '%s' "$steps_json" | jq 'length')"
        local last_output=""
        for i in $(seq 0 $((n_steps-1))); do
          local step agent_name binds out_key
          step="$(printf '%s' "$steps_json" | jq -c ".[$i]")"
          agent_name="$(printf '%s' "$step" | jq -r '.agent')"
          binds="$(printf '%s' "$step" | jq -c '.binds // {}')"
          out_key="$(printf '%s' "$step" | jq -r ".out // \"step_${i}_out\"")"

          # Resolve binds: a binding value starting with '$X' is replaced by vars[X].
          local resolved_binds
          resolved_binds="$(python3 -c '
import json, sys
binds = json.loads(sys.argv[1])
vars_ = json.loads(sys.argv[2])
out = {}
for k, v in binds.items():
    if isinstance(v, str) and v.startswith("$"):
        out[k] = vars_.get(v[1:], "")
    else:
        out[k] = v
print(json.dumps(out))
' "$binds" "$vars_json")"

          local rendered model rc model_flag
          model_flag="$(_cc_tmp)" || { status="failed"; break 2; }
          rendered="$(agent_render "$agent_name" "$resolved_binds" 2>"$model_flag")"
          model="$(awk -F= '/^MODEL=/{print $2}' "$model_flag")"
          rm -f "$model_flag"
          [ -z "$model" ] && { red "step $i: no model for agent $agent_name" >&2; status="failed"; break 2; }
          cyan "  [iter $iter step $i] $agent_name (model=$model)" >&2; echo >&2

          local output
          output="$(model_call "$model" "$rendered")"; rc=$?
          local done_seen=0
          if [ "$rc" -eq 0 ]; then done_seen=1; fi
          [ "$rc" -eq 2 ] && rc=0

          # echo a short preview
          echo "    -> $(printf '%s' "$output" | head -c 200)"

          G swarm-run-step-add "$run_id" "$iter" "$i" "$agent_name" \
            "$resolved_binds" "$output" "$done_seen"

          # update vars_json with this step's output
          vars_json="$(vars_merge "$vars_json" "$out_key" "$output")"
          last_output="$output"
        done

        if [ -z "$loop_until" ]; then
          # no loop sentinel set — run exactly one iteration
          break
        fi
        if printf '%s' "$last_output" | grep -Fq "$loop_until"; then
          green "loop_until sentinel '$loop_until' seen — stopping" >&2; echo >&2
          break
        fi
      done

      G swarm-run-end "$run_id" "$status" "$iter"
      green "swarm run #$run_id complete (status=$status iterations=$iter)" >&2; echo >&2
      echo "run_id=$run_id"
      ;;
    "")   red "usage: cc swarm <define|list|show|run|last|show-run>" >&2; echo >&2; exit 1 ;;
    *)    red "unknown swarm subcommand: $sub" >&2; echo >&2; exit 1 ;;
  esac
}

cmd_tool() {
  local sub="${1:-}"; shift || true
  case "$sub" in
    define)
      # cc tool define <name> -in '<json>' -out '<json>' -kind bash|python|streamlit -exec '<cmd or import>' [-tags "a,b"] [-- desc]
      local name="${1:-}"; shift || true
      local input_schema='{}' output_schema='{}' kind="bash" exec="" tags="" desc=""
      while [ $# -gt 0 ]; do
        case "$1" in
          -in)    shift; input_schema="${1:-}"; [ -z "$input_schema" ] && input_schema='{}'; shift ;;
          -out)   shift; output_schema="${1:-}"; [ -z "$output_schema" ] && output_schema='{}'; shift ;;
          -kind)  shift; kind="${1:-bash}"; shift ;;
          -exec)  shift; exec="${1:-}"; shift ;;
          -tags)  shift; tags="${1:-}"; shift ;;
          --)     shift; desc="$*"; break ;;
          *)      desc="$*"; break ;;
        esac
      done
      [ -z "$name" ] && { red "usage: cc tool define <name> -in <json> -out <json> -kind <bash|python|streamlit> -exec <...> [-tags ...] [-- desc]" >&2; exit 1; }
      [ -z "$exec" ] && { red "missing -exec" >&2; exit 1; }
      G tool-def "$name" "$desc" "$input_schema" "$output_schema" "$kind" "$exec" "$tags"
      green "tool '$name' defined ($kind)" >&2; echo >&2
      ;;
    list) G tool-list ;;
    show)
      local name="${1:-}"
      [ -z "$name" ] && { red "usage: cc tool show <name>" >&2; exit 1; }
      G tool-get "$name" | jq .
      ;;
    delete)
      local name="${1:-}"
      [ -z "$name" ] && { red "usage: cc tool delete <name>" >&2; exit 1; }
      G tool-delete "$name"
      green "tool '$name' deleted" >&2; echo >&2
      ;;
    run)
      local name="${1:-}"; shift || true
      [ -z "$name" ] && { red "usage: cc tool run <name> [-var k=v ...]" >&2; exit 1; }
      local -a kvargs=()
      while [ $# -gt 0 ]; do
        case "$1" in
          -var) shift; kvargs+=("$1"); shift ;;
          *) break ;;
        esac
      done
      local vars_json; vars_json="$(vars_to_json "${kvargs[@]}")"
      local def_json; def_json="$(G tool-get "$name")"
      local kind exec_template
      kind="$(printf '%s' "$def_json" | jq -r '.executor_kind')"
      exec_template="$(printf '%s' "$def_json" | jq -r '.executor')"
      if [ "$kind" != "bash" ]; then
        red "cc tool run only supports kind=bash from the CLI (kind=$kind). Use cc studio for streamlit/python tools." >&2; echo >&2
        exit 1
      fi
      # Substitute $var in the exec template
      local rendered
      rendered="$(python3 -c "
import sys, json, re, os
t = os.environ['T']
v = json.loads(os.environ['V'])
for k, val in v.items():
    t = re.sub(r'\\\$\\{' + re.escape(k) + r'\\}', str(val), t)
    t = re.sub(r'\\\$' + re.escape(k) + r'(?!\\w)', str(val), t)
print(t)
" T="$exec_template" V="$vars_json")"
      yellow "tool: $name" >&2; echo >&2
      yellow "exec: $rendered" >&2; echo >&2
      agent_update "tool $name"
      bash -c "$rendered"
      ;;
    "") red "usage: cc tool <define|list|show|delete|run>" >&2; echo >&2; exit 1 ;;
    *)  red "unknown tool subcommand: $sub" >&2; echo >&2; exit 1 ;;
  esac
}

cmd_workflow() {
  local sub="${1:-}"; shift || true
  case "$sub" in
    define)
      # cc workflow define <name> [-- desc]   (reads steps JSON from stdin)
      local name="${1:-}"; shift || true
      local desc=""
      if [ "${1:-}" = "--" ]; then shift; desc="$*"; fi
      [ -z "$name" ] && { red "usage: cc workflow define <name> [-- desc] <stdin: steps JSON>" >&2; exit 1; }
      local steps; steps="$(cat)"
      printf '%s' "$steps" | jq . >/dev/null 2>&1 || { red "invalid steps JSON" >&2; exit 1; }
      G workflow-def "$name" "$desc" "$steps"
      green "workflow '$name' defined" >&2; echo >&2
      ;;
    list) G workflow-list ;;
    show)
      local name="${1:-}"
      [ -z "$name" ] && { red "usage: cc workflow show <name>" >&2; exit 1; }
      G workflow-get "$name" | jq .
      ;;
    search)
      local q="$*"
      G workflow-search "$q" | jq -r '.[] | "\(.score)\t\(.use_count)\t\(.name)\t\(.description)"' | head -20
      ;;
    run)
      local name="${1:-}"; shift || true
      [ -z "$name" ] && { red "usage: cc workflow run <name> [-var k=v ...]" >&2; exit 1; }
      local -a kvargs=()
      while [ $# -gt 0 ]; do
        case "$1" in
          -var) shift; kvargs+=("$1"); shift ;;
          *) break ;;
        esac
      done
      local vars_json; vars_json="$(vars_to_json "${kvargs[@]}")"
      local raw; raw="$(G workflow-get "$name")"
      local steps_json; steps_json="$(printf '%s' "$raw" | jq -c '.steps')"
      G workflow-used "$name" >/dev/null
      yellow "workflow: $name" >&2; echo >&2

      local n_steps; n_steps="$(printf '%s' "$steps_json" | jq 'length')"
      for i in $(seq 0 $((n_steps-1))); do
        local step tool_name binds out_key
        step="$(printf '%s' "$steps_json" | jq -c ".[$i]")"
        tool_name="$(printf '%s' "$step" | jq -r '.tool')"
        binds="$(printf '%s' "$step" | jq -c '.binds // {}')"
        out_key="$(printf '%s' "$step" | jq -r ".out // \"step_${i}_out\"")"

        # Resolve $var references in binds against accumulated vars_json
        local resolved
        resolved="$(python3 -c "
import json, os, sys, re
binds = json.loads(os.environ['B'])
vars_ = json.loads(os.environ['V'])
out = {}
for k, val in binds.items():
    if isinstance(val, str) and val.startswith('\$'):
        out[k] = vars_.get(val[1:], '')
    else:
        out[k] = val
print(json.dumps(out))
" B="$binds" V="$vars_json")"

        cyan "  [step $i] tool=$tool_name binds=$resolved" >&2; echo >&2

        # Get the tool's exec
        local def_json; def_json="$(G tool-get "$tool_name")"
        local kind; kind="$(printf '%s' "$def_json" | jq -r '.executor_kind')"
        if [ "$kind" != "bash" ]; then
          yellow "skipping non-bash tool '$tool_name' (kind=$kind) — use cc studio" >&2; echo >&2
          continue
        fi
        local exec_template; exec_template="$(printf '%s' "$def_json" | jq -r '.executor')"
        local rendered
        rendered="$(python3 -c "
import sys, json, re, os
t = os.environ['T']
v = json.loads(os.environ['V'])
for k, val in v.items():
    t = re.sub(r'\\\$\\{' + re.escape(k) + r'\\}', str(val), t)
    t = re.sub(r'\\\$' + re.escape(k) + r'(?!\\w)', str(val), t)
print(t)
" T="$exec_template" V="$resolved")"

        local output
        output="$(bash -c "$rendered" 2>&1)"
        echo "    -> $(printf '%s' "$output" | head -c 200)"
        vars_json="$(vars_merge "$vars_json" "$out_key" "$output")"
      done
      green "workflow '$name' done" >&2; echo >&2
      ;;
    "") red "usage: cc workflow <define|list|show|search|run>" >&2; echo >&2; exit 1 ;;
    *)  red "unknown workflow subcommand: $sub" >&2; echo >&2; exit 1 ;;
  esac
}

cmd_studio() {
  # Studio runs against CC_STUDIO_HOME, NOT whatever cwd you launched from.
  # Make sure the workspace exists.
  mkdir -p "$CC_STUDIO_HOME/projects" \
           "$CC_STUDIO_HOME/models" \
           "$CC_STUDIO_HOME/datasets" \
           "$CC_STUDIO_HOME/workflows"

  # Find streamlit: prefer the studio's own venv, then any project venv on PATH,
  # then global.
  local st_bin=""
  if [ -x "$CC_STUDIO_HOME/.venv/bin/streamlit" ]; then
    st_bin="$CC_STUDIO_HOME/.venv/bin/streamlit"
  elif [ -n "${CC_LOCAL_ROOT:-}" ] && [ -x "$CC_LOCAL_ROOT/.venv/bin/streamlit" ]; then
    st_bin="$CC_LOCAL_ROOT/.venv/bin/streamlit"
  elif command -v streamlit >/dev/null 2>&1; then
    st_bin="$(command -v streamlit)"
  else
    red "streamlit not found. Run: $CC_INSTALL_ROOT/setup/setup.sh  (creates a studio venv)" >&2
    echo >&2; exit 1
  fi
  yellow "launching cc studio via $st_bin" >&2
  yellow "CC_STUDIO_HOME=$CC_STUDIO_HOME" >&2; echo >&2

  # Studio is HOME by default — strip cwd-derived scope env so the dashboard
  # doesn't auto-scope into whatever folder you invoked cc from.
  export CC_STUDIO_HOME
  unset CC_SCOPE_GLOBAL_PROJECT CC_SCOPE_LOCAL_PROJECT \
        CC_SCOPE_LOCAL_ROOT CC_SCOPE_LOCAL_DB

  # exec replaces this shell — the EXIT trap won't fire, so release the
  # agent slot and clean up tracked tmpfiles explicitly.
  agent_release
  _cc_cleanup
  exec "$st_bin" run "$CC_INSTALL_ROOT/lib/studio.py" "$@"
}

cmd_phase() {
  local sub="${1:-}"; shift || true
  local proj; proj="$(resolve_project)"
  case "$sub" in
    start)
      local name="$*"
      [ -z "$name" ] && { red "usage: cc phase start <name>" >&2; exit 1; }
      [ -z "$proj" ] && { red "no project — run 'cc -setup' or '-set-project' first" >&2; exit 1; }
      local pid
      pid="$(G phase-start "$proj" "$name")"
      green "phase #$pid started: $name" >&2; echo >&2
      ;;
    step)
      local target="ollama" model="$CC_MODEL"
      while [ $# -gt 0 ]; do
        case "$1" in
          -model)   shift; model="${1:-$CC_MODEL}"; shift ;;
          -tiny)    target="ollama"; model="$CC_TINY_MODEL"; shift ;;
          -claude)  target="claude"; shift ;;
          *) break ;;
        esac
      done
      local step_prompt="$*"
      [ -z "$step_prompt" ] && { red "usage: cc phase step [-model <m>|-tiny|-claude] <prompt>" >&2; exit 1; }
      local active; active="$(G phase-active "$proj")"
      [ -z "$active" ] && { red "no active phase — run 'cc phase start <name>'" >&2; exit 1; }
      local phase_id="${active%%	*}"
      local phase_name="${active##*	}"
      agent_update "phase #$phase_id step ($target $model)"

      # Build prompt with context pulled from db (the tween-level holds context).
      local ctx
      ctx="$(G phase-context "$phase_id" 8)"
      local full_prompt
      if [ -n "$ctx" ]; then
        full_prompt="$ctx

# Next step
$step_prompt"
      else
        full_prompt="$step_prompt"
      fi

      yellow "phase #$phase_id ($phase_name) — step via $target:$model" >&2; echo >&2
      local response done_seen=0 rc=0
      if [ "$target" = "claude" ]; then
        if ! command -v claude >/dev/null 2>&1; then
          red "claude not on PATH" >&2; echo >&2; exit 1
        fi
        local sys_directive
        sys_directive="$(claude_system_directive)
You are step inside cc phase #$phase_id. When you finish, end your response with the literal line: DONE"
        response="$(claude -p --append-system-prompt "$sys_directive" "$full_prompt" 2>&1)" || rc=$?
        if printf '%s' "$response" | tail -n 8 | grep -Eq '^[[:space:]]*DONE[[:space:]]*$'; then
          done_seen=1
          response="$(printf '%s' "$response" | sed -E '/^[[:space:]]*DONE[[:space:]]*$/d')"
        else
          yellow "WARNING: claude did not signal DONE for this step" >&2; echo >&2
        fi
      else
        # model_call enforces DONE itself
        response="$(model_call "$model" "$full_prompt")"; rc=$?
        if [ "$rc" -eq 0 ]; then done_seen=1; else done_seen=0; fi
        # rc=2 means partial; we still record but flag
        [ "$rc" -eq 2 ] && rc=0
      fi

      local idx
      idx="$(G phase-step-add "$phase_id" "$target:$model" "$step_prompt" "$response" "$done_seen" "$CC_AGENT_UUID")"
      printf '%s\n' "$response"
      echo >&2
      if [ "$done_seen" = "1" ]; then
        green "step $idx recorded (DONE)" >&2
      else
        yellow "step $idx recorded (PARTIAL — no DONE)" >&2
      fi
      echo >&2
      exit "$rc"
      ;;
    log)
      local active; active="$(G phase-active "$proj")"
      [ -z "$active" ] && { yellow "no active phase" >&2; echo >&2; exit 0; }
      G phase-show "${active%%	*}"
      ;;
    show)
      local id="${1:-}"
      [ -z "$id" ] && { red "usage: cc phase show <id>" >&2; exit 1; }
      G phase-show "$id"
      ;;
    list)
      G phase-list "$proj"
      ;;
    end)
      local summary=""
      if [ "${1:-}" = "-summary" ]; then shift; summary="$*"; fi
      local active; active="$(G phase-active "$proj")"
      [ -z "$active" ] && { yellow "no active phase to end" >&2; echo >&2; exit 0; }
      local phase_id="${active%%	*}"
      G phase-end "$phase_id" "$summary"
      green "phase #$phase_id closed" >&2; echo >&2
      ;;
    "")
      red "usage: cc phase <start|step|log|show|list|end> …" >&2; echo >&2; exit 1 ;;
    *)
      red "unknown phase subcommand: $sub" >&2; echo >&2; exit 1 ;;
  esac
}

cmd_chats() {
  G chat-list "$(resolve_project)" 50
}

cmd_chat_show() {
  local cid="${1:-}"
  [ -z "$cid" ] && { red "usage: cc chat-show <id>" >&2; exit 1; }
  G chat-show "$cid"
}

build_claude_preamble() {
  # Rich, markdown-formatted context dump that Claude can parse + act on.
  local proj; proj="$(resolve_project)"
  cat <<EOF
# cc context for project: $proj

You are being invoked by \`cc\` (a terminal manager that tracks projects, scripts,
todos, runs, and active agents). The state below is the source of truth; honor it.

- cwd:        $(pwd)
- local_root: ${CC_LOCAL_ROOT:-(none)}
- repo:       $(L meta-get repo 2>/dev/null)
- venv:       $(L meta-get venv 2>/dev/null)
- agent:      $CC_AGENT_UUID

## Entrypoints (this project)
$(L entry-list 2>/dev/null || echo "(none)")

## Pending todos (global, active project)
$(G list-todos 2>/dev/null | grep '^\[ \]' || echo "(none)")

## Recent runs (this project)
$(L run-list 5 2>/dev/null || echo "(none)")

## Registered bash scripts (global)
$(G list-scripts 2>/dev/null || echo "(none)")

## Recent global directory log
$(G show-log 8 2>/dev/null || echo "(none)")

## Available local helper
\`cc tiny <prompt>\` — calls a small deterministic local model ($CC_TINY_MODEL).
- Free (no API tokens). Cached. Same input → same output.
- Use it BEFORE doing these yourself: classification, structured extraction,
  short summarization, regex/grammar checks, traceback diagnosis, JSON parsing.
- Variants: \`cc tiny -debug "<cmd>\n<stderr>"\`, \`cc tiny -summarize "<text>"\`.
EOF
}

# Hard directive appended to Claude's system prompt so it actually uses cc tiny.
claude_system_directive() {
cat <<'EOF'
You are operating inside the cc terminal manager. Before performing any of the
following tasks yourself, you MUST first try the local helper `cc tiny`:
  - classifying / labelling text
  - parsing or extracting structured data
  - summarizing long output
  - diagnosing a failed command (use `cc tiny -debug "<cmd>\n<stderr>"`)
  - generating tiny boilerplate (regex, small JSON, short bash one-liners)

Only fall back to your own capabilities if `cc tiny` returns empty, errors, or
produces a clearly wrong answer. Run `cc tiny` via your Bash tool. Save your
deeper reasoning for tasks the small model can't handle.
EOF
}

# System prompt governing EVERY `cc bash` call. Read from $CC_BASH_PROMPT if it
# exists (user-editable), else fall back to a built-in default. Emitted as a
# guard banner + exported into the script's env as $CC_BASH_SYSTEM_PROMPT.
bash_system_directive() {
  if [ -f "$CC_BASH_PROMPT" ]; then
    cat "$CC_BASH_PROMPT"
    return
  fi
  cat <<'EOF'
You are executing a bash command inside the cc terminal manager. Stay within
$CC_LOCAL_ROOT and below. No destructive op (rm -rf, force-push, history
rewrite, mass mv, db drop) runs blind — if it's irreversible and unrequested,
stop and surface it. Never send file contents/keys/tokens to a 3rd-party API.
Try `cc tiny` first for classify/extract/summarize/regex/debug. cc auto-logs
every run (append-only) — do not delete run rows. Hashes are immutable once
written. Be terse; exit non-zero on real failure.
EOF
}

cmd_claude() {
  require_local
  agent_update "claude $*"
  if ! command -v claude >/dev/null 2>&1; then
    red "claude CLI not found on PATH" >&2; echo >&2; exit 1
  fi

  local mode="print"
  case "${1:-}" in
    -i|--interactive) mode="interactive"; shift ;;
    -last)            mode="last";        shift ;;
    -plan)            mode="plan";        shift ;;
  esac
  local instruction="$*"
  local proj; proj="$(resolve_project)"

  if [ "$mode" = "last" ]; then
    python3 - "$CC_LOCAL_DB" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
r = c.execute(
  "SELECT id, command, rc, stdout_tail, started_at FROM runs "
  "WHERE kind LIKE 'claude%' ORDER BY id DESC LIMIT 1"
).fetchone()
if not r:
  print("(no claude runs yet)")
else:
  rid, cmd, rc, out, started = r
  print(f"#{rid}  {started}  rc={rc}  {cmd}")
  print("---")
  print(out or "")
PY
    return
  fi

  if [ -z "$instruction" ] && [ "$mode" != "interactive" ]; then
    red "usage: cc claude [-plan|-i] <instruction...>" >&2; echo >&2; exit 1
  fi

  local preamble
  preamble="$(build_claude_preamble)"

  local trans_dir="$CC_LOCAL_ROOT/.cc/transcripts"
  mkdir -p "$trans_dir"
  local ts; ts="$(date +%Y%m%d-%H%M%S)"
  local trans_file="$trans_dir/${ts}-${CC_AGENT_UUID:0:8}.md"

  case "$mode" in
    print)
      local prompt="$preamble

## Request from user
$instruction

(Respond as Claude Code: use Read/Edit/Write/Bash tools as needed. Keep the
response focused on the request. Avoid chatty preamble. When done, summarize
in 1-3 lines.)"

      yellow "claude (one-shot) →" >&2; echo >&2
      local out rc=0
      local sys_directive; sys_directive="$(claude_system_directive)"
      out="$(claude -p --append-system-prompt "$sys_directive" "$prompt" 2>&1)" || rc=$?
      printf '%s\n' "$out"

      {
        echo "# cc claude transcript"
        echo "agent: $CC_AGENT_UUID"
        echo "rc:    $rc"
        echo "when:  $ts"
        echo
        echo "## prompt"
        echo
        printf '%s\n' "$prompt"
        echo
        echo "## response"
        echo
        printf '%s\n' "$out"
      } > "$trans_file"

      L run-add "claude" "claude -p ($instruction)" "$rc" \
        "$(printf '%s' "$out" | tail -c 4000)" "transcript=$trans_file" "$CC_AGENT_UUID"
      G log-action "$proj" "$(pwd)" "claude" "rc=$rc -- $instruction (transcript=$trans_file)"

      # Register the transcript as a chat row.
      local trans_hash
      trans_hash="$(sha256sum "$trans_file" | awk '{print $1}')"
      G chat-add "$proj" "$PWD" "cc-claude-$(date +%s)" "cc-claude-p" \
        "$CC_AGENT_UUID" "$ts" "$ts" 2 "$trans_file" "" "" "$trans_hash" >/dev/null
      exit "$rc"
      ;;

    interactive)
      local ctx_file="$CC_LOCAL_ROOT/.cc/CC_CONTEXT.md"
      printf '%s\n' "$preamble" > "$ctx_file"
      yellow "wrote $ctx_file (Claude can Read it for cc state)" >&2; echo >&2
      L run-add "claude-interactive-start" "claude -i" "0" "ctx=$ctx_file" "" "$CC_AGENT_UUID"
      G log-action "$proj" "$(pwd)" "claude-interactive-start" "ctx=$ctx_file"
      local rc=0
      if [ -n "$instruction" ]; then
        claude "$preamble

## Initial request
$instruction" || rc=$?
      else
        claude || rc=$?
      fi
      L run-add "claude-interactive-end" "claude -i" "$rc" "" "" "$CC_AGENT_UUID"
      G log-action "$proj" "$(pwd)" "claude-interactive-end" "rc=$rc"
      exit "$rc"
      ;;

    plan)
      local prompt="$preamble

## Planning request

Decompose the following instruction into concrete, actionable todos for project '$proj'.

Output format — EXACTLY:

1. <todo text>
2. <todo text>
...

No prose before or after. No markdown. No empty lines. Each todo must be
specific enough to execute.

Instruction:
$instruction"

      yellow "claude (planning) →" >&2; echo >&2
      local raw rc=0
      local sys_directive; sys_directive="$(claude_system_directive)"
      raw="$(claude -p --append-system-prompt "$sys_directive" "$prompt" 2>&1)" || rc=$?
      local added=0
      while IFS= read -r line; do
        # Only accept "N. ..." lines — filters out chatter, stderr logs, etc.
        [[ "$line" =~ ^[[:space:]]*[0-9]+\.[[:space:]]+ ]] || continue
        local task
        task="$(printf '%s' "$line" | sed -E 's/^[[:space:]]*[0-9]+\.[[:space:]]+//' | sed -E 's/[[:space:]]+$//')"
        [ -z "$task" ] && continue
        G add-todo "$proj" "$task" >/dev/null
        added=$((added+1))
        echo "  + $task"
      done <<< "$raw"

      {
        echo "# cc claude -plan transcript"
        echo "agent: $CC_AGENT_UUID"
        echo "rc:    $rc  (added $added todos)"
        echo
        echo "## raw response"
        echo
        printf '%s\n' "$raw"
      } > "$trans_file"

      L run-add "claude-plan" "claude -p (plan: $instruction)" "$rc" \
        "$(printf '%s' "$raw" | tail -c 4000)" "added=$added transcript=$trans_file" "$CC_AGENT_UUID"
      G log-action "$proj" "$(pwd)" "claude-plan" "added $added todos -- $instruction"
      green "added $added todo(s) to $proj" >&2; echo >&2
      ;;
  esac
}

cmd_bash() {
  require_local
  agent_update "bash $*"
  local target="${1:-}"
  [ -z "$target" ] && { red "usage: cc bash <script-or-name> [args...]" >&2; exit 1; }
  shift || true

  # If it's a path that exists, run it. Otherwise look up in registered scripts.
  local script
  if [ -f "$target" ]; then
    script="$target"
  else
    script="$(G list-scripts | awk -v n="$target" '$2==n {print $3; exit}')"
    if [ -z "$script" ]; then
      red "no script found: $target" >&2; echo >&2
      exit 1
    fi
  fi

  # Apply the cc bash system prompt to this call: banner to stderr + export into
  # the script's env so any downstream model/tool sees the standing directive.
  local CC_BASH_SYSTEM_PROMPT; CC_BASH_SYSTEM_PROMPT="$(bash_system_directive)"
  export CC_BASH_SYSTEM_PROMPT
  dim "── cc bash system prompt active ($CC_BASH_PROMPT) ──" >&2; echo >&2

  yellow "running: bash $script $*" >&2; echo >&2
  local tmp_stdout tmp_stderr rc=0
  tmp_stdout="$(_cc_tmp)" || exit 1
  tmp_stderr="$(_cc_tmp)" || exit 1
  bash "$script" "$@" >"$tmp_stdout" 2>"$tmp_stderr" || rc=$?
  cat "$tmp_stdout"
  cat "$tmp_stderr" >&2
  L run-add "bash" "bash $script $*" "$rc" \
    "$(tail -c 4000 "$tmp_stdout")" "$(tail -c 4000 "$tmp_stderr")" "$CC_AGENT_UUID"
  local proj; proj="$(resolve_project)"
  G log-action "$proj" "$(pwd)" "bash" "rc=$rc $script $*"
  rm -f "$tmp_stdout" "$tmp_stderr"
  exit "$rc"
}

# ---- operator stack (op front door + go popup) ---------------------------

cmd_op() {
  # native cc subcommand: pass through to the operator front door.
  local op="/home/tom/bin/op"
  [ -x "$op" ] || { red "operator not installed: $op (run install_operator.sh)" >&2; exit 1; }
  local rc=0
  "$op" "$@" || rc=$?
  local proj; proj="$(resolve_project 2>/dev/null || echo '?')"
  G log-action "$proj" "$(pwd)" "op" "rc=$rc $*" 2>/dev/null || true
  exit "$rc"
}

cmd_go() {
  # one entry to everything: start the operator dashboard + open the click popup.
  local port="${CC_GO_PORT:-8787}"
  local url="http://127.0.0.1:$port/go"
  local pybin="/home/tom/miniconda3/envs/trade-blob/bin/python3"
  local server="/data/Projects/trade-blob/dashboard/server.py"
  if ! curl -sf "$url" >/dev/null 2>&1; then
    yellow "cc go: starting operator dashboard on :$port …" >&2
    nohup "$pybin" "$server" --port "$port" >/tmp/cc_go.log 2>&1 &
    disown 2>/dev/null || true
    local i; for i in $(seq 1 24); do curl -sf "$url" >/dev/null 2>&1 && break; sleep 0.5; done
  fi
  if curl -sf "$url" >/dev/null 2>&1; then
    green "cc go: control panel → $url" >&2
    (xdg-open "$url" >/dev/null 2>&1 &) 2>/dev/null || true
    echo "$url"
  else
    red "cc go: dashboard did not come up — see /tmp/cc_go.log" >&2; exit 1
  fi
}

# ---- existing global subcommands (kept) ----------------------------------

cmd_set_project() {
  local name="${1:-}"
  [ -z "$name" ] && { red "usage: cc -set-project <name>" >&2; exit 1; }
  G set-project "$name"
  G log-action "$name" "$(pwd)" "set-project" "switched to $name"
  echo "active global project: $(green "$name")"
}

cmd_list_projects() { G list-projects; }

cmd_add_bash() {
  local name="${1:-}"; shift || true
  local desc="${*:-}"
  [ -z "$name" ] && { red "usage: cc -add-bash <name> [description...]" >&2; exit 1; }
  local project; project="$(require_project_global)"

  local out_dir="$CC_SCRIPTS/$project"
  mkdir -p "$out_dir"
  local out_path="$out_dir/$name.sh"
  if [ -e "$out_path" ]; then
    red "script already exists: $out_path" >&2; echo >&2; exit 1
  fi

  agent_update "add-bash $name"
  local prompt
  prompt="You are generating a single self-contained bash script.

Project: $project
Script name: $name
Description: ${desc:-(none provided)}

Rules:
- Output ONLY the bash script body. No prose, no markdown fences.
- Start with: #!/usr/bin/env bash
- Use set -euo pipefail.
- Keep operations scoped to the caller's cwd and below unless the description
  explicitly requires otherwise.
- Prefer clarity over cleverness."

  yellow "drafting $name.sh with $CC_MODEL …" >&2; echo >&2
  local body
  body="$(model_call "$CC_MODEL" "$prompt")"
  if [ -z "$body" ]; then
    red "model returned nothing" >&2; echo >&2; exit 1
  fi
  printf '%s\n' "$body" > "$out_path"
  chmod +x "$out_path"
  G add-script "$project" "$name" "$out_path" "$desc"
  G log-action "$project" "$(pwd)" "add-bash" "$name -> $out_path"
  green "wrote $out_path" >&2; echo >&2
  echo "$out_path"
}

cmd_list_bash() { G list-scripts; }

cmd_plan() {
  local model="$CC_MODEL"
  if [ "${1:-}" = "-model" ]; then
    shift; model="${1:-}"; shift || true
  fi
  local instruction="$*"
  [ -z "$instruction" ] && { red "usage: cc -plan [-model <m>] <instruction...>" >&2; exit 1; }
  local project; project="$(require_project_global)"

  agent_update "plan"
  local prompt
  prompt="Decompose the following instruction into a numbered list of concrete,
actionable todos for project '$project'. One todo per line, format exactly:

1. <todo text>
2. <todo text>
...

No prose before or after. No markdown. No empty lines.

Instruction:
$instruction"

  yellow "planning with $model …" >&2; echo >&2
  local raw
  raw="$(model_call "$model" "$prompt")"
  if [ -z "$raw" ]; then
    red "model returned nothing" >&2; echo >&2; exit 1
  fi

  local added=0
  while IFS= read -r line; do
    [[ "$line" =~ ^[[:space:]]*[0-9]+\.[[:space:]]+ ]] || continue
    local task
    task="$(printf '%s' "$line" | sed -E 's/^[[:space:]]*[0-9]+\.[[:space:]]+//' | sed -E 's/[[:space:]]+$//')"
    [ -z "$task" ] && continue
    G add-todo "$project" "$task" >/dev/null
    added=$((added+1))
    echo "  + $task"
  done <<< "$raw"

  G log-action "$project" "$(pwd)" "plan" "added $added todos from: $instruction"
  green "added $added todo(s) to project $project" >&2; echo >&2
}

cmd_todos()         { G list-todos; }
cmd_done()          { G done "$1"; }
cmd_edit_todo()     { local id="$1"; shift; G edit-todo "$id" "$@"; }
cmd_current()       { G current-show; }
cmd_current_set()   { local p; p="$(require_project_global)"; G current-set "$p" "$1"; }
cmd_current_clear() { G current-clear; }
cmd_queue()         { G queue-list; }

cmd_run() {
  local qid="${1:-}"
  [ -z "$qid" ] && { red "usage: cc -run <queue-id>" >&2; exit 1; }
  local project; project="$(G active)"
  local cmdline
  cmdline="$(G queue-pop "$qid")" || exit 1
  yellow "queue #$qid running: $cmdline" >&2; echo >&2
  agent_update "run-queue $qid"
  local rc=0
  bash -c "$cmdline" || rc=$?
  G queue-done "$qid"
  G log-action "$project" "$(pwd)" "run-queue" "qid=$qid rc=$rc -- $cmdline"
  exit "$rc"
}

cmd_log() {
  local n=20
  if [ "${1:-}" = "-n" ]; then shift; n="${1:-20}"; fi
  G show-log "$n"
}

cmd_clear_cache() {
  rm -rf "$CC_CACHE"
  mkdir -p "$CC_CACHE"
  green "cleared $CC_CACHE" >&2; echo >&2
}

cmd_freeform() {
  local cs="$CC_INSTALL_ROOT/lib/cell_store.py"
  # cc {task} --loop  → run the full autoregressive outer transformer on the task.
  local use_loop=0 instruction=""
  for a in "$@"; do
    if [ "$a" = "--loop" ]; then use_loop=1; else instruction="${instruction:+$instruction }$a"; fi
  done
  if [ "$use_loop" = "1" ]; then
    [ -z "$instruction" ] && { red "usage: cc <task> --loop" >&2; exit 1; }
    local loop_lib="$CC_INSTALL_ROOT/lib/loop.py"
    CC_BIN="$CC_INSTALL_ROOT/cc" python3 "$loop_lib" run --intent freeform --trust-bash "$instruction"
    return $?
  fi

  [ -z "$instruction" ] && { usage >&2; exit 1; }
  agent_update "freeform: $instruction"
  local project; project="$(resolve_project)"
  local proj_for_log="${project:-(none)}"

  local prompt
  prompt="Propose a SINGLE bash command (no explanation) that accomplishes
the user's request, scoped strictly to the current working directory and below.

Working directory: $(pwd)
Project: $proj_for_log

Output rules:
- Exactly one line.
- No markdown, no prose, no fences, no quotes around the whole command.
- Must be safe to execute with: bash -c '<your output>'.
- Prefer read-only / dry-run forms if the request is ambiguous.

Request:
$instruction"

  # ── transposition-table lookup: identical task → replay cached proposal,
  #    ZERO model calls. The recipe keys on the full proposal prompt + model.
  local prop_recipe out_cid cmdline cached=0
  prop_recipe="$(python3 "$cs" recipe-hash "$prompt" "freeform" "model" "$CC_MODEL" 2>/dev/null || echo "")"
  out_cid="$(python3 "$cs" recipe-get "$prop_recipe" 2>/dev/null || echo "")"
  if [ -n "$out_cid" ]; then
    cmdline="$(python3 "$cs" cell-content "$out_cid" 2>/dev/null || echo "")"
    python3 "$cs" recipe-hit "$prop_recipe" >/dev/null 2>&1 || true
    cached=1
    yellow "cached proposal (recipe hit — no model call)" >&2; echo >&2
  else
    yellow "asking $CC_MODEL …" >&2; echo >&2
    cmdline="$(model_call "$CC_MODEL" "$prompt" | sed -E 's/^[[:space:]]*```[a-z]*//; s/```[[:space:]]*$//' | grep -v '^[[:space:]]*$' | head -n 1)"
    if [ -z "$cmdline" ]; then
      red "model returned nothing" >&2; echo >&2; exit 1
    fi
    # store the proposed command as a response cell + recipe (dedup by cid)
    out_cid="$(python3 "$cs" add response "$cmdline" "" freeform "$proj_for_log" 2>/dev/null || echo "")"
    [ -n "$prop_recipe" ] && [ -n "$out_cid" ] && \
      python3 "$cs" recipe-add "$prop_recipe" "$out_cid" model freeform "" "$CC_MODEL" 0 >/dev/null 2>&1 || true
  fi

  echo >&2
  yellow "proposed:" >&2; echo " $cmdline" >&2
  if [ ! -r /dev/tty ]; then
    red "no tty available — refusing to auto-run model-proposed command" >&2; echo >&2
    yellow "to run anyway: bash -c '$cmdline'" >&2; echo >&2
    G log-action "$proj_for_log" "$(pwd)" "freeform-no-tty" "$cmdline"
    exit 1
  fi
  printf '%s' "execute? [y/N] " >&2
  read -r ans </dev/tty || ans=""
  case "$ans" in
    y|Y|yes|YES)
      local rc=0 result_text
      # Capture stdout to store as a cell, while still showing it to the user.
      result_text="$(bash -c "$cmdline" 2>&1)" || rc=$?
      printf '%s\n' "$result_text"
      G log-action "$proj_for_log" "$(pwd)" "freeform${cached:+-cached}" "rc=$rc -- $cmdline"
      # store the result as a bashout cell + lineage edge proposal → result
      if [ -n "$out_cid" ] && [ -n "$result_text" ]; then
        local res_cid
        res_cid="$(python3 "$cs" add bashout "$result_text" "" freeform "$proj_for_log" 2>/dev/null || echo "")"
        [ -n "$res_cid" ] && python3 "$cs" edge-add "$out_cid" "$res_cid" produced 2>/dev/null || true
      fi
      exit "$rc"
      ;;
    *)
      G log-action "$proj_for_log" "$(pwd)" "freeform-skipped" "$cmdline"
      yellow "skipped" >&2; echo >&2
      exit 0
      ;;
  esac
}

# ---- consolidation batch 2026-05-28 ----
# Each function is a thin wrapper around python3 <module> <subcmd> "$@".
# Modules that may not yet exist (dapp/server.py, harvest_loop.sh) are
# guarded with `[ -f "$PATH" ]` and graceful red() skip.

# Sui on-chain connector (balance / mint / lend)
cmd_sui_balance() {
  local addr="${1:-}"; shift || true
  local coin_type="${1:-0x2::sui::SUI}"; shift || true
  [ -z "$addr" ] && { red "usage: cc sui-balance <addr> [coin_type]" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/third_party/sui_mcp.py" balance \
    --addr "$addr" --coin-type "$coin_type" "$@"
}

cmd_sui_mint() {
  local attrs_json="${1:-}"; shift || true
  [ -z "$attrs_json" ] && { red "usage: cc sui-mint <attrs_json> [--confirm]" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/third_party/sui_mcp.py" mint --attrs "$attrs_json" "$@"
}

cmd_sui_lend() {
  local pool_id="${1:-}"; shift || true
  [ -z "$pool_id" ] && { red "usage: cc sui-lend <pool_id> --amount N [--dry]" >&2; exit 1; }
  local defi="$CC_INSTALL_ROOT/lib/defi_loop.py"
  if [ -f "$defi" ]; then
    python3 "$defi" lend --pool-id "$pool_id" "$@"
  else
    # fall back to sui_mcp lend_pool_deposit via a future subcommand
    yellow "defi_loop.py not built yet — falling back to sui_mcp (limited)" >&2
    python3 "$CC_INSTALL_ROOT/lib/third_party/sui_mcp.py" providers
    red "sui-lend:  defi_loop.py not built yet (use TaskCreate to track)" >&2
    exit 0
  fi
}

# TensorChain L1 connector (NFT mint / status)
cmd_tc_mint() {
  local metadata_uri="${1:-}"; shift || true
  [ -z "$metadata_uri" ] && { red "usage: cc tc-mint <metadata_uri> [--royalty N]" >&2; exit 1; }
  local royalty_bps=500
  while [ $# -gt 0 ]; do
    case "$1" in
      --royalty|--royalty-bps) royalty_bps="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  python3 "$CC_INSTALL_ROOT/lib/third_party/tensorchain_mcp.py" mint \
    --metadata-uri "$metadata_uri" --royalty-bps "$royalty_bps"
}

cmd_tc_status() {
  python3 "$CC_INSTALL_ROOT/lib/third_party/tensorchain_mcp.py" connect "$@"
}

# ComfyUI HTTP connector
cmd_comfy_submit() {
  local template="${1:-}"; shift || true
  [ -z "$template" ] && { red "usage: cc comfy-submit <template> --inputs <json>" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/third_party/comfyui_mcp.py" submit "$template" "$@"
}

cmd_comfy_status() {
  python3 "$CC_INSTALL_ROOT/lib/third_party/comfyui_mcp.py" stats "$@"
}

# TopstepX futures connector (DRY-RUN by default)
cmd_topstep_status() {
  python3 "$CC_INSTALL_ROOT/lib/third_party/topstep_mcp.py" account-status "$@"
}

cmd_topstep_positions() {
  python3 "$CC_INSTALL_ROOT/lib/third_party/topstep_mcp.py" positions "$@"
}

cmd_topstep_order() {
  local side="${1:-}"; local symbol="${2:-}"; local qty="${3:-}"
  shift 3 2>/dev/null || true
  if [ -z "$side" ] || [ -z "$symbol" ] || [ -z "$qty" ]; then
    red "usage: cc topstep-order <BUY|SELL> <SYMBOL> <QTY> [--confirm]" >&2; exit 1
  fi
  python3 "$CC_INSTALL_ROOT/lib/third_party/topstep_mcp.py" order-market \
    --side "$side" --symbol "$symbol" --qty "$qty" "$@"
}

# HuggingFace Inference Endpoints (paid/dedicated)
cmd_hf_endpoint_list() {
  python3 "$CC_INSTALL_ROOT/lib/hf_endpoints.py" list "$@"
}

cmd_hf_endpoint_deploy() {
  local model_id="${1:-}"; shift || true
  [ -z "$model_id" ] && { red "usage: cc hf-endpoint-deploy <model_id> [--confirm]" >&2; exit 1; }
  # use the canonical deploy path so we don't need --namespace/--name fuss
  python3 "$CC_INSTALL_ROOT/lib/hf_endpoints.py" deploy-canonical \
    --model-id "$model_id" "$@"
}

# generative_mcp — meta-connector across text/code/card/app providers
cmd_generative_text() {
  local prompt="${1:-}"; shift || true
  [ -z "$prompt" ] && { red "usage: cc generative-text \"<prompt>\"" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/third_party/generative_mcp.py" text "$prompt" "$@"
}

cmd_generative_code() {
  local prompt="${1:-}"; shift || true
  [ -z "$prompt" ] && { red "usage: cc generative-code \"<prompt>\" [--lang python]" >&2; exit 1; }
  # accept --lang as alias for --language
  local language="python"
  local rest=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --lang|--language) language="$2"; shift 2 ;;
      *) rest+=("$1"); shift ;;
    esac
  done
  python3 "$CC_INSTALL_ROOT/lib/third_party/generative_mcp.py" code "$prompt" \
    --language "$language" "${rest[@]}"
}

cmd_generative_app() {
  local card_slug="${1:-}"; shift || true
  [ -z "$card_slug" ] && { red "usage: cc generative-app <card_slug>" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/third_party/generative_mcp.py" app "$card_slug" "$@"
}

cmd_generative_card() {
  local prompt="${1:-}"; shift || true
  [ -z "$prompt" ] && { red "usage: cc generative-card \"<prompt>\" [--kind workflow]" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/third_party/generative_mcp.py" card "$prompt" "$@"
}

# Generic HTML → CursorNode JSONL parser
cmd_doc_parse() {
  local adapter="" html_path=""
  local rest=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --adapter) adapter="$2"; shift 2 ;;
      --html)    html_path="$2"; shift 2 ;;
      *) rest+=("$1"); shift ;;
    esac
  done
  if [ -z "$adapter" ] || [ -z "$html_path" ]; then
    red "usage: cc doc-parse --adapter <name> --html <path>" >&2; exit 1
  fi
  python3 "$CC_INSTALL_ROOT/lib/doc_parser.py" parse-file "$adapter" "$html_path" "${rest[@]}"
}

# Noun Project icon harvest
cmd_noun_harvest() {
  local query="${1:-}"; shift || true
  [ -z "$query" ] && { red "usage: cc noun-harvest \"<query>\" [--limit N]" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/third_party/noun_project.py" harvest \
    --query "$query" "$@"
}

# Multi-layer hex envelope packer
cmd_multi_layer_hex() {
  local sub="${1:-}"; shift || true
  [ -z "$sub" ] && { red "usage: cc multi-layer-hex {pack|unpack|distance|layout} ..." >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/multi_layer_hex.py" "$sub" "$@"
}

# Unified gated model API HTTP server
cmd_model_api_serve() {
  python3 "$CC_INSTALL_ROOT/lib/model_api.py" serve "$@"
}

# dApp HTTP front-end (may not be built yet)
cmd_dapp_serve() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then
    red "dapp-serve:  studio/ not found." >&2; exit 1
  fi
  local script="$dir/dapp/server.py"
  if [ ! -f "$script" ]; then
    red "dapp-serve:  not built yet (use TaskCreate to track)" >&2
    exit 0
  fi
  python3 "$script" "$@"
}

# Asset harvest loop daemon (may not be built yet)
cmd_harvest_loop() {
  local sub="${1:-status}"; shift || true
  local script="$CC_INSTALL_ROOT/scripts/harvest_loop.sh"
  if [ ! -f "$script" ]; then
    red "harvest-loop:  not built yet (use TaskCreate to track)" >&2
    exit 0
  fi
  bash "$script" "$sub" "$@"
}

# Free-tier token issuance / verification
cmd_freetier_issue() {
  python3 "$CC_INSTALL_ROOT/lib/freetier_gate.py" issue "$@"
}

cmd_freetier_verify() {
  local token="${1:-}"; shift || true
  [ -z "$token" ] && { red "usage: cc freetier-verify <token>" >&2; exit 1; }
  python3 "$CC_INSTALL_ROOT/lib/freetier_gate.py" verify "$token" "$@"
}

# Free-tier callback HTTP server (GentlyOS.io / trollz.fun terms-policy bouncer)
cmd_callback_serve() {
  local dir; if ! dir="$(_resolve_studio_dir)"; then
    red "callback-serve:  studio/ not found." >&2; exit 1
  fi
  local script="$dir/endpoints/freetier_callback/server.py"
  if [ ! -f "$script" ]; then
    red "callback-serve:  not built yet (use TaskCreate to track)" >&2
    exit 0
  fi
  python3 "$script" "$@"
}

# ---- pump surf dispatchers (2026-05-28) ----
# Thin wrappers around core/lib/pump_*.py CLIs. Each module is guarded; missing
# pieces (pump_wave_build / pump_wave_preview) report "not built yet" and exit
# cleanly so the dispatch table stays reachable.

# cc pump-ingest [--duration N] [--max-events N]
cmd_pump_ingest() {
  local script="$CC_INSTALL_ROOT/lib/pump_stream_ingest.py"
  if [ ! -f "$script" ]; then
    red "pump-ingest:  core/lib/pump_stream_ingest.py not built yet" >&2
    exit 0
  fi
  python3 "$script" ingest "$@"
}

# cc pump-features <jsonl> [--window N]
cmd_pump_features() {
  local jsonl="${1:-}"; shift || true
  [ -z "$jsonl" ] && { red "usage: cc pump-features <jsonl> [--window N] [--min-events N] [--out CSV]" >&2; exit 1; }
  local script="$CC_INSTALL_ROOT/lib/pump_feature_extractor.py"
  if [ ! -f "$script" ]; then
    red "pump-features:  core/lib/pump_feature_extractor.py not built yet" >&2
    exit 0
  fi
  python3 "$script" extract --jsonl "$jsonl" "$@"
}

# cc pump-train-gmm <features.csv>
cmd_pump_train_gmm() {
  local features="${1:-}"; shift || true
  [ -z "$features" ] && { red "usage: cc pump-train-gmm <features.csv> [--out PKL]" >&2; exit 1; }
  local script="$CC_INSTALL_ROOT/lib/pump_gmm_classifier.py"
  if [ ! -f "$script" ]; then
    red "pump-train-gmm:  core/lib/pump_gmm_classifier.py not built yet" >&2
    exit 0
  fi
  python3 "$script" train "$features" "$@"
}

# cc pump-train-xgb <features.csv> <labels.csv>
cmd_pump_train_xgb() {
  local features="${1:-}"; shift || true
  local labels="${1:-}"; shift || true
  if [ -z "$features" ] || [ -z "$labels" ]; then
    red "usage: cc pump-train-xgb <features.csv> <labels.csv> [--out JSON] [--cpu]" >&2; exit 1
  fi
  local script="$CC_INSTALL_ROOT/lib/pump_xgboost_gate.py"
  if [ ! -f "$script" ]; then
    red "pump-train-xgb:  core/lib/pump_xgboost_gate.py not built yet" >&2
    exit 0
  fi
  python3 "$script" train "$features" "$labels" "$@"
}

# cc pump-gate <wallet> --features '<json>' --human-inflow <float>
cmd_pump_gate() {
  local wallet="${1:-}"; shift || true
  [ -z "$wallet" ] && { red "usage: cc pump-gate <wallet> --features '<json>' --human-inflow <float>" >&2; exit 1; }
  local script="$CC_INSTALL_ROOT/lib/pump_xgboost_gate.py"
  if [ ! -f "$script" ]; then
    red "pump-gate:  core/lib/pump_xgboost_gate.py not built yet" >&2
    exit 0
  fi
  python3 "$script" gate "$wallet" "$@"
}

# cc pump-surf-status
cmd_pump_surf_status() {
  local script="$CC_INSTALL_ROOT/lib/pump_surf_executor.py"
  if [ ! -f "$script" ]; then
    red "pump-surf-status:  core/lib/pump_surf_executor.py not built yet" >&2
    exit 0
  fi
  python3 "$script" status "$@"
}

# cc programs-registry-<seed|list|add|verify|watch>
cmd_programs_registry() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/program_registry.py"
  if [ ! -f "$script" ]; then
    red "programs-registry:  core/lib/program_registry.py not built yet" >&2
    exit 0
  fi
  python3 "$script" "$sub" "$@"
}

# cc programs-monitor-<watchset|start|status>
cmd_programs_monitor() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/program_monitor.py"
  if [ ! -f "$script" ]; then
    red "programs-monitor:  core/lib/program_monitor.py not built yet" >&2
    exit 0
  fi
  python3 "$script" "$sub" "$@"
}

# cc programs-correlate [--window 5] [--synth N] [--persist]
cmd_programs_correlate() {
  local script="$CC_INSTALL_ROOT/lib/program_correlator.py"
  if [ ! -f "$script" ]; then
    red "programs-correlate:  core/lib/program_correlator.py not built yet" >&2
    exit 0
  fi
  python3 "$script" run "$@"
}

# cc programs-correlate-stats
cmd_programs_correlate_stats() {
  local script="$CC_INSTALL_ROOT/lib/program_correlator.py"
  if [ ! -f "$script" ]; then
    red "programs-correlate-stats:  core/lib/program_correlator.py not built yet" >&2
    exit 0
  fi
  python3 "$script" stats "$@"
}

# cc programs-correlate-clear  (removes today's correlation jsonl)
cmd_programs_correlate_clear() {
  local script="$CC_INSTALL_ROOT/lib/program_correlator.py"
  if [ ! -f "$script" ]; then
    red "programs-correlate-clear:  core/lib/program_correlator.py not built yet" >&2
    exit 0
  fi
  python3 "$script" clear "$@"
}

# cc wallet-map-<scan|stats|render|serve|clear>
#   scan <mint> [--since TS] [--max-sigs N] [--rpc URL] [--delay S]
#       hydrate monitored signatures for <mint> into signer wallets
#   stats                     node/edge/source counts on disk
#   render [--out FILE] [--token MINT]   static SVG of the graph
#   serve                     ensure dapp_server (8520) is up; print map URL
#   clear                     wipe the wallet_map store
cmd_wallet_map() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/token_wallet_mapper.py"
  if [ ! -f "$script" ]; then
    red "wallet-map:  core/lib/token_wallet_mapper.py not built yet" >&2
    exit 0
  fi
  case "$sub" in
    scan)   python3 "$script" scan "$@" ;;
    stats)  python3 "$script" stats ;;
    render) python3 "$script" svg "$@" ;;
    clear)  python3 "$script" clear ;;
    serve)  cmd_wallet_map_serve "$@" ;;
    *) echo "usage: cc wallet-map-<scan|stats|render|serve|clear>" >&2; exit 2 ;;
  esac
}

# ensure the dapp_server (serves /dapp/wallet-map + /dapp/api/solscan-ingest)
# is running on its port, starting it detached if not.
cmd_wallet_map_serve() {
  local port="${MSPC_DAPP_PORT:-8520}"
  local srv="$CC_INSTALL_ROOT/../studio/dapp/server.py"
  if curl -fsS "http://127.0.0.1:${port}/dapp/healthz" >/dev/null 2>&1; then
    echo "dapp_server already up on :${port}"
  elif [ ! -f "$srv" ]; then
    red "wallet-map-serve:  studio/dapp/server.py not found at $srv" >&2
    exit 1
  else
    echo "starting dapp_server on :${port} ..."
    MSPC_DAPP_PORT="$port" MSPC_DAPP_LOG=quiet \
      nohup python3 "$srv" >/tmp/mspc_dapp.log 2>&1 &
    sleep 2
    curl -fsS "http://127.0.0.1:${port}/dapp/healthz" >/dev/null 2>&1 \
      && echo "started." || { red "failed to start; see /tmp/mspc_dapp.log" >&2; exit 1; }
  fi
  echo "wallet map  → http://127.0.0.1:${port}/dapp/wallet-map"
  echo "ingest POST → http://127.0.0.1:${port}/dapp/api/solscan-ingest"
  echo "extension   → studio/extensions/solscan-map/ (load unpacked)"
}

# cc loom-serve — ensure the dapp_server (8520) is up, then print the Loom URL.
#   The Loom shell is the first shippable face: empty workspace + left icon
#   tool-shelf; "+" opens a codebase-aware chat; CONFIRM bakes a minted SCOPE
#   icon. Mirrors cmd_wallet_map_serve (same server, different surface).
cmd_loom_serve() {
  local port="${MSPC_DAPP_PORT:-8520}"
  local srv="$CC_INSTALL_ROOT/../studio/dapp/server.py"
  if curl -fsS "http://127.0.0.1:${port}/dapp/healthz" >/dev/null 2>&1; then
    echo "dapp_server already up on :${port}"
  elif [ ! -f "$srv" ]; then
    red "loom-serve:  studio/dapp/server.py not found at $srv" >&2
    exit 1
  else
    echo "starting dapp_server on :${port} ..."
    MSPC_DAPP_PORT="$port" MSPC_DAPP_LOG=quiet \
      nohup python3 "$srv" >/tmp/mspc_dapp.log 2>&1 &
    sleep 2
    curl -fsS "http://127.0.0.1:${port}/dapp/healthz" >/dev/null 2>&1 \
      && echo "started." || { red "failed to start; see /tmp/mspc_dapp.log" >&2; exit 1; }
  fi
  echo "loom shell  → http://127.0.0.1:${port}/dapp/loom"
}

# cc loom-clone <tenant> ["label"]  — launch an isolated clone (self-building
#   node builder; inherits the engine, NOT your state). cc loom-tenants — list.
cmd_loom() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/loom.py"
  if [ ! -f "$script" ]; then red "loom: core/lib/loom.py not built yet" >&2; exit 0; fi
  python3 "$script" "$sub" "$@"
}

# cc morph <build|dag|decompose|prompt|objects|crystallize|fetch> ...
#   the crystallized DAG-of-DAGs (wheels): build a modality-transform chain,
#   decompose to HF-Spaces level, crystallize onto the chain, render to prompt
#   or to OO objects. e.g. cc morph build "text->image->video"
cmd_morph() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/morph_chain.py"
  if [ ! -f "$script" ]; then red "morph: core/lib/morph_chain.py not built yet" >&2; exit 0; fi
  python3 "$script" "$sub" "$@"
}

# cc app-gen <slug> [...] | cc deploy <slug> [--apply] | cc app-list
#   generate a full app locally → plan/apply rsync→droplet. DRY-RUN by default.
cmd_deploy() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/deploy.py"
  if [ ! -f "$script" ]; then red "deploy: core/lib/deploy.py not built yet" >&2; exit 0; fi
  python3 "$script" "$sub" "$@"
}

# cc blender-mcp '<tool>' '<json-args>' — drive the headless Blender MCP server
#   directly (scene.clear/mesh.create/material.set/render.image/mesh.export_gltf).
#   With no args, runs a self-test (clear→monkey→material→export).
cmd_blender_mcp() {
  local wrapper="$CC_INSTALL_ROOT/../studio/blender/blender-mcp"
  if [ ! -x "$wrapper" ]; then red "blender-mcp: wrapper not found at $wrapper" >&2; exit 1; fi
  python3 -c "
import sys, json; sys.path.insert(0,'$CC_INSTALL_ROOT/lib')
from third_party.base import ConnectionConfig
from third_party.blender_mcp import BlenderMCPConnector
c=BlenderMCPConnector(ConnectionConfig(service='blender_mcp',auth={'endpoint':'stdio://$wrapper'}))
c.connect()
args=sys.argv[1:]
if args:
    r=c.send(args[0], args[1] if len(args)>1 else '{}')
    print(json.dumps({'ok':r.success,'meta':r.metadata,'err':r.error},indent=2))
else:
    for tool,a in [('scene.clear',{}),('mesh.create',{'primitive':'monkey','name':'T'}),
                   ('material.set',{'object':'T','base_color':[0.2,0.6,1,1]}),
                   ('mesh.export_gltf',{'filepath':'/tmp/cc_blender_selftest.glb'})]:
        r=c.send(tool,json.dumps(a)); print(tool,'->',r.success, r.metadata or r.error)
" "$@"
}

# cc hf-endpoint-plan — print the per-modality HF endpoints that WOULD deploy
#   (free/offline; deploy itself stays behind confirm=True — hourly billing).
cmd_hf_endpoint_plan() {
  python3 -c "import sys; sys.path.insert(0,'$CC_INSTALL_ROOT/lib'); import json; import hf_endpoints as h; print(json.dumps(h.plan_per_modality(), indent=2))"
}

# cc gpu-status — both RTX 3090 Ti devices: reservations + live nvidia-smi used/free.
cmd_gpu_status() {
  local script="$CC_INSTALL_ROOT/lib/gpu_scheduler.py"
  if [ ! -f "$script" ]; then
    red "gpu-status:  core/lib/gpu_scheduler.py not found" >&2; exit 0
  fi
  python3 "$script" status --live
}

# cc up [--dry-run] [--only a,b] | cc up-status [--json] | cc down [--only a,b]
#   bring up every local service + report all connector (Sui/Telegram/Discord/
#   Facebook/Snap/Stripe/X/TensorChain) readiness. Idempotent; never destructive.
cmd_up() {
  local sub="${1:-up}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/service_supervisor.py"
  if [ ! -f "$script" ]; then
    red "up:  core/lib/service_supervisor.py not built yet" >&2; exit 0
  fi
  python3 "$script" "$sub" "$@"
}

# cc audio-chroma <audio.wav> [--buckets N]
#   colourise a sound wave: each bucket → amplitude → rgba + #hex (+ frame60).
#   Writes ~/.cc/chroma/<stem>.{jsonl,svg}. WAV works without ffmpeg.
cmd_audio_chroma() {
  local script="$CC_INSTALL_ROOT/lib/audio_chromatize.py"
  if [ ! -f "$script" ]; then
    red "audio-chroma:  core/lib/audio_chromatize.py not built yet" >&2
    exit 0
  fi
  python3 "$script" file "$@"
}

# cc stream-list — recorded livestreams + which token/wallets they map to.
cmd_stream_list() {
  local port="${MSPC_DAPP_PORT:-8520}"
  curl -fsS "http://127.0.0.1:${port}/dapp/api/streams" 2>/dev/null \
    | python3 -m json.tool 2>/dev/null \
    || echo "no streams (start the server: cc wallet-map-serve)"
}

# cc chain-render-<one|tail|prompt|sample>
cmd_chain_render() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/chain_event_render.py"
  if [ ! -f "$script" ]; then
    red "chain-render:  core/lib/chain_event_render.py not built yet" >&2
    exit 0
  fi
  python3 "$script" "$sub" "$@"
}

# cc godot-ssot-serve [--port 8766] [--bind 127.0.0.1]
cmd_godot_ssot_serve() {
  local script="$CC_INSTALL_ROOT/lib/godot_ssot_proxy.py"
  if [ ! -f "$script" ]; then
    red "godot-ssot-serve:  core/lib/godot_ssot_proxy.py not found" >&2; exit 0
  fi
  python3 "$script" serve --port "${1:-8766}" --bind "${2:-127.0.0.1}"
}

# cc encoder-<run|stats|reset-lock|one>
cmd_encoder() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/stream_encoder.py"
  if [ ! -f "$script" ]; then red "stream_encoder.py not built yet" >&2; exit 0; fi
  local py="/data/Projects/ComfyUI/.venv/bin/python"
  [ ! -x "$py" ] && py="python3"
  "$py" "$script" "$sub" "$@"
}

# cc loom-serve [port]  ·  static-serve studio/loom/ on the given port (default 8526)
cmd_loom_serve() {
  local port="${1:-8526}"
  local studio_dir
  if ! studio_dir="$(_resolve_studio_dir)"; then
    red "loom-serve: studio/ not found" >&2; exit 1
  fi
  local loom_dir="$studio_dir/loom"
  if [ ! -d "$loom_dir" ]; then
    red "loom-serve: $loom_dir does not exist" >&2; exit 1
  fi
  echo "[loom] serving $loom_dir on http://localhost:$port"
  echo "[loom] cards:"
  ls "$loom_dir"/*.html 2>/dev/null | sed 's|.*/|  |'
  cd "$loom_dir" && python3 -m http.server "$port"
}

# cc blob-to-unreal <png_path> [--live]  ·  run the 5-pass pipeline
cmd_blob_to_unreal() {
  local script="$CC_INSTALL_ROOT/lib/blob_to_unreal.py"
  if [ ! -f "$script" ]; then red "blob_to_unreal.py not built yet" >&2; exit 0; fi
  if [ -z "${1:-}" ]; then
    echo "[blob-to-unreal] usage: cc blob-to-unreal <png_path> [--duration N] [--fps N] [--live]"
    echo "[blob-to-unreal] (live UDP requires --live AND MSPC_UNREAL_LIVE=1 in env)"
    python3 "$script" test
    return 0
  fi
  python3 "$script" run "$@"
}

# cc unreal-live-link <send|synth> [args]  ·  stream MocapFrames to UE5
cmd_unreal_live_link() {
  local sub="${1:-synth}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/third_party/unreal_live_link.py"
  if [ ! -f "$script" ]; then red "unreal_live_link.py not built yet" >&2; exit 0; fi
  python3 "$script" "$sub" "$@"
}

# cc loom-list  ·  list Loom cards that have been minted into studio/loom
cmd_loom_list() {
  local studio_dir
  if ! studio_dir="$(_resolve_studio_dir)"; then
    red "loom-list: studio/ not found" >&2; exit 1
  fi
  local loom_dir="$studio_dir/loom"
  if [ ! -d "$loom_dir" ]; then
    echo "[loom] no cards yet — $loom_dir does not exist"
    return 0
  fi
  echo "[loom] cards in $loom_dir:"
  for f in "$loom_dir"/*.html; do
    [ -f "$f" ] || continue
    echo "  $(basename "$f")  ($(wc -c < "$f") bytes)"
  done
}

# cc swap-<routes|quote|execute>
# routes  — read-only, lists 6 supported pairs
# quote   — read-only, hits Jupiter/Cetus/Wormhole quote APIs
# execute — DRY-RUN by default; live requires both MSPC_SWAP_LIVE=1 env AND --confirm flag
cmd_swap() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/swap_router.py"
  if [ ! -f "$script" ]; then red "swap_router.py not built yet" >&2; exit 0; fi
  python3 "$script" "$sub" "$@"
}

# cc embed-<save|load|stats|query>
cmd_embed() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/embedding_index.py"
  if [ ! -f "$script" ]; then red "embedding_index.py not built yet" >&2; exit 0; fi
  local py="/data/Projects/ComfyUI/.venv/bin/python"
  [ ! -x "$py" ] && py="python3"
  "$py" "$script" "$sub" "$@"
}

# cc embed-ingest [path]
cmd_embed_ingest() {
  local script="$CC_INSTALL_ROOT/lib/embedding_index.py"
  if [ ! -f "$script" ]; then red "embedding_index.py not built yet" >&2; exit 0; fi
  local src="${1:-$HOME/.cc/embeddings/$(date -u +%Y-%m-%d).jsonl}"
  local py="/data/Projects/ComfyUI/.venv/bin/python"
  [ ! -x "$py" ] && py="python3"
  "$py" "$script" ingest --from "$src"
}

# cc godot-issue-dev-token  (writes a 30-day token to ~/.cc/godot_dev_token.txt)
cmd_godot_issue_dev_token() {
  local script="$CC_INSTALL_ROOT/lib/freetier_gate.py"
  if [ ! -f "$script" ]; then
    red "godot-issue-dev-token:  core/lib/freetier_gate.py not found" >&2; exit 0
  fi
  local tok
  tok="$(python3 "$script" issue --user-id godot_local --domain GentlyOS.io 2>&1 \
        | python3 -c "import sys, json; print(json.loads(sys.stdin.read())['token'])")"
  if [ -z "$tok" ]; then red "godot-issue-dev-token: failed to parse token" >&2; exit 1; fi
  printf '%s' "$tok" > "$HOME/.cc/godot_dev_token.txt"
  chmod 600 "$HOME/.cc/godot_dev_token.txt"
  echo "[godot] dev token written to ~/.cc/godot_dev_token.txt"
  echo "       Godot autoload will read it automatically; or pass via MSPC_GODOT_BEARER env."
}

# cc godot-chain-smoke  (curl the new /chain/* endpoints; needs proxy up)
cmd_godot_chain_smoke() {
  local base="${MSPC_GODOT_SSOT_BASE:-http://127.0.0.1:8766}"
  local tok="${MSPC_GODOT_BEARER:-$(cat "$HOME/.cc/godot_dev_token.txt" 2>/dev/null || echo "")}"
  if [ -z "$tok" ]; then
    red "godot-chain-smoke:  no bearer token. Run: cc godot-issue-dev-token" >&2; exit 1
  fi
  echo "[smoke] GET $base/healthz"
  curl -s -m 5 "$base/healthz" | python3 -m json.tool
  echo "[smoke] GET $base/chain/programs/watchset"
  curl -s -m 5 -H "Authorization: Bearer $tok" "$base/chain/programs/watchset" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(f'  watchset count={d.get(\"count\",0)}; first={d.get(\"watchset\",[{}])[0].get(\"name\",\"\") if d.get(\"watchset\") else \"-\"}')"
  echo "[smoke] GET $base/chain/renders/recent?n=5"
  curl -s -m 5 -H "Authorization: Bearer $tok" "$base/chain/renders/recent?n=5" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(f'  renders count={d.get(\"count\",0)}'); [print(f'    {r[\"crystal_short\"]:18s} {r[\"category\"]:18s} img={r[\"image_status\"]}') for r in d.get('renders',[])]"
  echo "[smoke] GET $base/chain/events/recent?n=3"
  curl -s -m 5 -H "Authorization: Bearer $tok" "$base/chain/events/recent?n=3" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(f'  events count={d.get(\"count\",0)}'); [print(f'    {e.get(\"program_short\",\"-\")[:12]:14s} {e.get(\"action\",\"-\")}') for e in d.get('events',[])]"
}

# Launch a downloaded (FHS) Godot binary. On NixOS the standalone build can't
# resolve libX11/libfontconfig/libwayland/libGL from FHS paths; steam-run gives
# it an FHS sandbox where those libs exist. Set CC_GODOT_NO_WRAP=1 to bypass.
_godot_exec() {
  if [ -z "${CC_GODOT_NO_WRAP:-}" ] && command -v steam-run >/dev/null 2>&1 \
     && { [ -e /etc/NIXOS ] || command -v nixos-version >/dev/null 2>&1; }; then
    echo "[godot] NixOS detected — launching via steam-run (FHS libs)" >&2
    steam-run "$@"
  else
    "$@"
  fi
}

# cc godot-chain-wall  (open the wall scene in the Godot editor or headless)
cmd_godot_chain_wall() {
  local godot_bin=""
  for cand in godot godot4; do
    if command -v "$cand" >/dev/null 2>&1; then godot_bin="$cand"; break; fi
  done
  if [ -z "$godot_bin" ]; then
    for cand in \
      "/data/Projects/MySpace++/Godot_v4.6.3-stable_linux.x86_64" \
      "$HOME/Projects/MySpace++/Godot_v4.6.3-stable_linux.x86_64" \
      "/data/Projects/Godot_v4.6.3-stable_linux.x86_64" \
      "$HOME/Datasets/3d/Godot_v4.6.3-stable_linux.x86_64"; do
      if [ -x "$cand" ]; then godot_bin="$cand"; break; fi
    done
  fi
  if [ -z "$godot_bin" ]; then
    red "godot-chain-wall:  Godot binary not found" >&2
    echo "       Tried PATH (godot, godot4) and standard locations" >&2
    echo "       Install: cp /tmp/godot_extracted/Godot_v4.6.3-stable_linux.x86_64 /data/Projects/MySpace++/" >&2
    exit 1
  fi
  local studio_dir
  if ! studio_dir="$(_resolve_studio_dir)"; then
    red "godot-chain-wall:  studio/ not found" >&2; exit 1
  fi
  local proj="$studio_dir/godot/project"
  echo "[godot] launching wall scene"
  _godot_exec "$godot_bin" --path "$proj" "res://scenes/chain_render_wall.tscn" "$@"
}

# cc asset-gallery — open the 3D gallery that runtime-loads every generated GLB
#   (generate_3d output) and arranges them in 3D. Needs the dApp up (cc up).
cmd_asset_gallery() {
  local godot_bin=""
  for cand in godot godot4; do
    if command -v "$cand" >/dev/null 2>&1; then godot_bin="$cand"; break; fi
  done
  if [ -z "$godot_bin" ]; then
    for cand in \
      "/data/Projects/MySpace++/Godot_v4.6.3-stable_linux.x86_64" \
      "$HOME/Projects/MySpace++/Godot_v4.6.3-stable_linux.x86_64" \
      "/data/Projects/Godot_v4.6.3-stable_linux.x86_64"; do
      if [ -x "$cand" ]; then godot_bin="$cand"; break; fi
    done
  fi
  if [ -z "$godot_bin" ]; then red "asset-gallery: Godot binary not found" >&2; exit 1; fi
  local studio_dir
  if ! studio_dir="$(_resolve_studio_dir)"; then red "asset-gallery: studio/ not found" >&2; exit 1; fi
  echo "[godot] launching 3D asset gallery (runtime-loads ~/.cc/gen3d/*.glb)"
  _godot_exec "$godot_bin" --path "$studio_dir/godot/project" "res://scenes/asset_3d_gallery.tscn" "$@"
}

# cc hunyuan-<run|one|status|seed|reset-lock|workflow-preview>
cmd_hunyuan() {
  local sub="${1:-}"; shift || true
  local script="$CC_INSTALL_ROOT/lib/hunyuan_video_worker.py"
  if [ ! -f "$script" ]; then
    red "hunyuan:  core/lib/hunyuan_video_worker.py not built yet" >&2
    exit 0
  fi
  python3 "$script" "$sub" "$@"
}

# cc solana-webhook-<serve|test>
cmd_solana_webhook() {
  local sub="${1:-}"; shift || true
  local studio_dir
  if ! studio_dir="$(_resolve_studio_dir)"; then
    red "solana-webhook:  studio/ not found" >&2; exit 1
  fi
  local script="$studio_dir/endpoints/webhook/solana_webhook.py"
  if [ ! -f "$script" ]; then
    red "solana-webhook:  $script not built yet" >&2; exit 0
  fi
  python3 "$script" "$sub" "$@"
}

# cc pump-surf-buy --mint <X> --sol <amount> --target-wallet <Y> [--confirm]
cmd_pump_surf_buy() {
  local script="$CC_INSTALL_ROOT/lib/pump_surf_executor.py"
  if [ ! -f "$script" ]; then
    red "pump-surf-buy:  core/lib/pump_surf_executor.py not built yet" >&2
    exit 0
  fi
  python3 "$script" buy "$@"
}

# cc pump-surf-orders [-n 20]
cmd_pump_surf_orders() {
  local script="$CC_INSTALL_ROOT/lib/pump_surf_executor.py"
  if [ ! -f "$script" ]; then
    red "pump-surf-orders:  core/lib/pump_surf_executor.py not built yet" >&2
    exit 0
  fi
  python3 "$script" order-log "$@"
}

# cc pump-wave-build <events.jsonl> [--out wave.json]
cmd_pump_wave_build() {
  local events="${1:-}"; shift || true
  [ -z "$events" ] && { red "usage: cc pump-wave-build <events.jsonl> [--out wave.json]" >&2; exit 1; }
  local script="$CC_INSTALL_ROOT/lib/pump_wave_build.py"
  if [ ! -f "$script" ]; then
    red "pump-wave-build:  core/lib/pump_wave_build.py not built yet (use TaskCreate to track)" >&2
    exit 0
  fi
  python3 "$script" build --events "$events" "$@"
}

# cc pump-wave-preview <wave.json> [--out preview.svg]
cmd_pump_wave_preview() {
  local wave="${1:-}"; shift || true
  [ -z "$wave" ] && { red "usage: cc pump-wave-preview <wave.json> [--out preview.svg]" >&2; exit 1; }
  local script="$CC_INSTALL_ROOT/lib/pump_wave_preview.py"
  if [ ! -f "$script" ]; then
    red "pump-wave-preview:  core/lib/pump_wave_preview.py not built yet (use TaskCreate to track)" >&2
    exit 0
  fi
  python3 "$script" preview --wave "$wave" "$@"
}

# cc surf-run — alias for `cc studio-run pump_surf_pipeline`
cmd_surf_run() {
  cmd_studio_run pump_surf_pipeline "$@"
}

# ---- dispatch ------------------------------------------------------------

scope_log

if [ $# -eq 0 ]; then usage; exit 0; fi

# Claim an agent slot up-front so every cc invocation is visible to peers.
# Per-subcommand handlers may refine the action via agent_update.
agent_claim "$*"

case "$1" in
  -help|--help|-h)        shift; usage ;;
  -setup)                 shift; cmd_setup "$@" ;;
  -context)               shift; cmd_context ;;
  -scope|scope)           shift; cmd_scope ;;
  h)                      shift; cmd_help ;;
  help)                   shift; cmd_help ;;
  tui)                    shift; agent_release; _cc_cleanup; exec python3 "$CC_INSTALL_ROOT/lib/tui.py" ;;
  -agents)                shift; cmd_agents ;;
  -runs)                  shift; cmd_runs "$@" ;;
  py)                     shift; cmd_py "$@" ;;
  bash)                   shift; cmd_bash "$@" ;;
  op)                     shift; cmd_op "$@" ;;
  go)                     shift; cmd_go "$@" ;;
  claude)                 shift; cmd_claude "$@" ;;
  claude-import)          shift; cmd_claude_import "$@" ;;
  chat)                   shift; cmd_chat "$@" ;;
  inference-chain)        shift; cmd_inference_chain "$@" ;;
  inference-verify)       shift; cmd_inference_verify ;;
  inference-search)       shift; cmd_inference_search "$@" ;;
  inference-get)           shift; cmd_inference_get "$@" ;;
  workflow-card)          shift; cmd_workflow_card "$@" ;;
  queue-status)           shift; cmd_queue_status ;;
  gpu-status)             shift; cmd_gpu_status ;;
  cache-stats)            shift; cmd_cache_stats ;;
  comfy-index)            shift; cmd_comfy_index "$@" ;;
  models-index)           shift; cmd_models_index "$@" ;;
  datasets-index)         shift; cmd_datasets_index "$@" ;;
  scan-projects)          shift; cmd_scan_projects "$@" ;;
  ops-dag)                shift; cmd_ops_dag "$@" ;;
  studio-run)             shift; cmd_studio_run "$@" ;;
  studio-list)            shift; cmd_studio_list ;;
  dialectic-walk)         shift; cmd_dialectic_walk "$@" ;;
  hf-search)              shift; cmd_hf_search "$@" ;;
  hf-card)                shift; cmd_hf_card "$@" ;;
  hf-datasets)            shift; cmd_hf_datasets "$@" ;;
  hf-infer)               shift; cmd_hf_infer "$@" ;;
  hf-stream)              shift; cmd_hf_stream "$@" ;;
  hf-providers)           shift; cmd_hf_providers ;;
  model-search)            shift; cmd_model_search "$@" ;;
  model-install)           shift; cmd_model_install "$@" ;;
  model-list)              shift; cmd_model_list "$@" ;;
  model-taxonomy)          shift; cmd_model_taxonomy ;;
  model-sync)              shift; cmd_model_sync ;;
  deck)                    shift; cmd_deck "$@" ;;
  third_party-connect)    shift; cmd_third_party_connect "$@" ;;
  third_party-send)       shift; cmd_third_party_send "$@" ;;
  third_party-list)       shift; cmd_third_party_list "$@" ;;
  third_party-status)     shift; cmd_third_party_status "$@" ;;
  third_party-archive)    shift; cmd_third_party_archive "$@" ;;
  endpoint-start)         shift; cmd_endpoint_start "$@" ;;
  endpoint-stop)          shift; cmd_endpoint_stop "$@" ;;
  endpoint-list)          shift; cmd_endpoint_list "$@" ;;
  endpoint-status)        shift; cmd_endpoint_status "$@" ;;
  endpoint-sync)          shift; cmd_endpoint_sync "$@" ;;
  route-add)              shift; cmd_route_add "$@" ;;
  route-list)             shift; cmd_route_list "$@" ;;
  route-test)             shift; cmd_route_test "$@" ;;
  route-archive)           shift; cmd_route_archive "$@" ;;
  chats)                  shift; cmd_chats ;;
  chat-show)              shift; cmd_chat_show "$@" ;;
  tiny)                   shift; cmd_tiny "$@" ;;
  -chain)                 shift; cmd_chain "$@" ;;
  -chain-last)            shift; cmd_chain_last ;;
  -chain-show)            shift; cmd_chain_show "$@" ;;
  -chain-list)            shift; cmd_chain_list "$@" ;;
  -cards)                 shift; cmd_cards ;;
  -card-show)             shift; cmd_card_show "$@" ;;
  -card-delete)           shift; cmd_card_delete "$@" ;;
  -author-cards)          shift; cmd_author_cards "$@" ;;
  -gui-cards)             shift; cmd_gui_cards ;;
  -gui-show)              shift; cmd_gui_show "$@" ;;
  -gui-delete)            shift; cmd_gui_delete "$@" ;;
  -author-gui-cards)      shift; cmd_author_gui_cards "$@" ;;
  -templates)             shift; cmd_templates ;;
  -template-show)         shift; cmd_template_show "$@" ;;
  -template-delete)       shift; cmd_template_delete "$@" ;;
  -authorize-templates)   shift; cmd_authorize_templates "$@" ;;
  -jobs)                  shift; cmd_jobs "$@" ;;
  -job-show)              shift; cmd_job_show "$@" ;;
  -job-last)              shift; cmd_job_last ;;
  -dag-bootstrap)         shift; cmd_dag_bootstrap ;;
  -dag-status)            shift; cmd_dag_status ;;
  -dag-node)              shift; cmd_dag_node "$@" ;;
  -dag-chain)             shift; cmd_dag_chain "$@" ;;
  -dag-build)             shift; cmd_dag_build "$@" ;;
  -dag-enqueue)           shift; cmd_dag_enqueue "$@" ;;
  -dag-successors)        shift; cmd_dag_successors "$@" ;;
  -dag-chains-from)       shift; cmd_dag_chains_from "$@" ;;
  -dag-chains)            shift; cmd_dag_chains_pair "$@" ;;
  -dag-invalidate)        shift; cmd_dag_invalidate "$@" ;;
  -template-walk)         shift; cmd_template_walk "$@" ;;
  phase)                  shift; cmd_phase "$@" ;;
  agent)                  shift; cmd_agent "$@" ;;
  swarm)                  shift; cmd_swarm "$@" ;;
  tool)                   shift; cmd_tool "$@" ;;
  workflow)               shift; cmd_workflow "$@" ;;
  studio)                 shift; cmd_studio "$@" ;;
  -set-project)           shift; cmd_set_project "$@" ;;
  -list-projects)         shift; cmd_list_projects ;;
  -add-bash)              shift; cmd_add_bash "$@" ;;
  -list-bash)             shift; cmd_list_bash ;;
  -plan)                  shift; cmd_plan "$@" ;;
  -todos)                 shift; cmd_todos ;;
  -done)                  shift; cmd_done "$@" ;;
  -edit-todo)             shift; cmd_edit_todo "$@" ;;
  -current)               shift; cmd_current ;;
  -current-set)           shift; cmd_current_set "$@" ;;
  -current-clear)         shift; cmd_current_clear ;;
  -queue)                 shift; cmd_queue ;;
  -run)                   shift; cmd_run "$@" ;;
  -log)                   shift; cmd_log "$@" ;;
  -clear-cache)           shift; cmd_clear_cache ;;
  -studio|-dag-studio)    shift; cmd_dag_studio "$@" ;;
  -wardrobe)              shift; cmd_wardrobe "$@" ;;
  -yt-cut)                shift; cmd_yt_cut "$@" ;;
  -social)                shift; cmd_social "$@" ;;
  -social-upload)         shift; cmd_social_upload "$@" ;;
  -social-dev)            shift; cmd_social_dev "$@" ;;
  -social-oauth)          shift; cmd_social_oauth "$@" ;;
  -pump-feed)             shift; cmd_pump_feed "$@" ;;
  -pump-feed-ws)          shift; cmd_pump_feed_ws "$@" ;;
  -pump-train)            shift; cmd_pump_train "$@" ;;
  -pump-infer)            shift; cmd_pump_infer "$@" ;;
  -pump-both)             shift; cmd_pump_both "$@" ;;
  -bot-forensics)         shift; cmd_bot_forensics "$@" ;;
  -sui-feed)              shift; cmd_sui_feed "$@" ;;
  -sui-feed-ws)           shift; cmd_sui_feed_ws "$@" ;;
  -sui-train)             shift; cmd_sui_train "$@" ;;
  -sui-infer)             shift; cmd_sui_infer "$@" ;;
  -sui-both)              shift; cmd_sui_both "$@" ;;
  -orchestration-map)     shift; cmd_orchestration_map "$@" ;;
  -wallet-grid)           shift; cmd_wallet_grid "$@" ;;
  -pattern-train)         shift; cmd_pattern_train "$@" ;;
  -pattern-predict)       shift; cmd_pattern_predict "$@" ;;
  -pattern-dashboard)     shift; cmd_pattern_dashboard "$@" ;;
  -auth-seed)             shift; cmd_auth_seed "$@" ;;
  -auth-list)             shift; cmd_auth_list ;;
  -auth-revoke)           shift; cmd_auth_revoke "$@" ;;
  -auth-grant)            shift; cmd_auth_grant "$@" ;;
  -auth-status)           shift; cmd_auth_status ;;
  -auth-ssh)              shift; cmd_auth_ssh "$@" ;;
  -intake)                shift; cmd_intake "$@" ;;
  -fetch-url)             shift; cmd_fetch_url "$@" ;;
  -keys-distribute)       shift; cmd_keys_distribute "$@" ;;
  -keys-list)             shift; cmd_keys_list "$@" ;;
  -keys-status)           shift; cmd_keys_status ;;
  -keys-revoke)           shift; cmd_keys_revoke "$@" ;;
  -keys-verify)           shift; cmd_keys_verify "$@" ;;
  -proxy-start)           shift; cmd_proxy_start "$@" ;;
  -passes-list)           shift; cmd_passes_list ;;
  -passes-dag)            shift; cmd_passes_dag ;;
  -passes-run)            shift; cmd_passes_run "$@" ;;
  -passes-search)         shift; cmd_passes_search "$@" ;;
  -passes-stats)          shift; cmd_passes_stats ;;
  -passes-timing)         shift; cmd_passes_timing ;;
  -passes-backfill)       shift; cmd_passes_backfill "$@" ;;
  -tesseract-build)       shift; cmd_tesseract_build ;;
  -tesseract-status)      shift; cmd_tesseract_status ;;
  -tesseract-walk)        shift; cmd_tesseract_walk ;;
  -tesseract-identify)    shift; cmd_tesseract_identify "$@" ;;
  -tesseract-reset)       shift; cmd_tesseract_reset "$@" ;;
  -tesseract-project)     shift; cmd_tesseract_project "$@" ;;
  -tesseract-plan)        shift; cmd_tesseract_plan "$@" ;;
  -tesseract-plan-seed)   shift; cmd_tesseract_plan_seed ;;
  -tesseract-open)        shift; cmd_tesseract_open ;;
  -weave-seed)            shift; cmd_weave_seed ;;
  -weave-status)          shift; cmd_weave_status ;;
  -weave-devices)         shift; cmd_weave_devices ;;
  -weave-plans)           shift; cmd_weave_plans ;;
  -weave-route)           shift; cmd_weave_route "$@" ;;
  -weave-jobs)            shift; cmd_weave_jobs ;;
  -weave-server-start)    shift; cmd_weave_server_start ;;
  -weave-reset)           shift; cmd_weave_reset ;;
  # ---- consolidation batch 2026-05-28 ----
  sui-balance)            shift; cmd_sui_balance "$@" ;;
  sui-mint)               shift; cmd_sui_mint "$@" ;;
  sui-lend)               shift; cmd_sui_lend "$@" ;;
  tc-mint)                shift; cmd_tc_mint "$@" ;;
  tc-status)              shift; cmd_tc_status "$@" ;;
  comfy-submit)           shift; cmd_comfy_submit "$@" ;;
  comfy-status)           shift; cmd_comfy_status "$@" ;;
  topstep-status)         shift; cmd_topstep_status "$@" ;;
  topstep-positions)      shift; cmd_topstep_positions "$@" ;;
  topstep-order)          shift; cmd_topstep_order "$@" ;;
  hf-endpoint-list)       shift; cmd_hf_endpoint_list "$@" ;;
  hf-endpoint-deploy)     shift; cmd_hf_endpoint_deploy "$@" ;;
  generative-text)        shift; cmd_generative_text "$@" ;;
  generative-code)        shift; cmd_generative_code "$@" ;;
  generative-app)         shift; cmd_generative_app "$@" ;;
  generative-card)        shift; cmd_generative_card "$@" ;;
  doc-parse)              shift; cmd_doc_parse "$@" ;;
  noun-harvest)           shift; cmd_noun_harvest "$@" ;;
  multi-layer-hex)        shift; cmd_multi_layer_hex "$@" ;;
  model-api-serve)        shift; cmd_model_api_serve "$@" ;;
  dapp-serve)             shift; cmd_dapp_serve "$@" ;;
  harvest-loop)           shift; cmd_harvest_loop "$@" ;;
  freetier-issue)         shift; cmd_freetier_issue "$@" ;;
  freetier-verify)        shift; cmd_freetier_verify "$@" ;;
  callback-serve)         shift; cmd_callback_serve "$@" ;;
  # ---- pump surf dispatchers (2026-05-28) ----
  pump-ingest)            shift; cmd_pump_ingest "$@" ;;
  pump-features)          shift; cmd_pump_features "$@" ;;
  pump-train-gmm)         shift; cmd_pump_train_gmm "$@" ;;
  pump-train-xgb)         shift; cmd_pump_train_xgb "$@" ;;
  pump-gate)              shift; cmd_pump_gate "$@" ;;
  pump-surf-status)       shift; cmd_pump_surf_status "$@" ;;
  pump-surf-buy)          shift; cmd_pump_surf_buy "$@" ;;
  pump-surf-orders)       shift; cmd_pump_surf_orders "$@" ;;
  pump-wave-build)        shift; cmd_pump_wave_build "$@" ;;
  pump-wave-preview)      shift; cmd_pump_wave_preview "$@" ;;
  surf-run)               shift; cmd_surf_run "$@" ;;
  # ---- program monitor (other web3 apps' program IDs, oracle data) ----
  programs-registry-seed)    shift; cmd_programs_registry seed "$@" ;;
  programs-registry-list)    shift; cmd_programs_registry list "$@" ;;
  programs-registry-add)     shift; cmd_programs_registry add "$@" ;;
  programs-registry-verify)  shift; cmd_programs_registry verify "$@" ;;
  programs-registry-verify-live) shift; cmd_programs_registry verify-live "$@" ;;
  programs-registry-watch)   shift; cmd_programs_registry set-watch "$@" ;;
  programs-watchset)         shift; cmd_programs_monitor watchset "$@" ;;
  programs-monitor-start)    shift; cmd_programs_monitor start "$@" ;;
  programs-monitor-status)   shift; cmd_programs_monitor status "$@" ;;
  programs-correlate)        shift; cmd_programs_correlate "$@" ;;
  programs-correlate-stats)  shift; cmd_programs_correlate_stats "$@" ;;
  programs-correlate-clear)  shift; cmd_programs_correlate_clear "$@" ;;
  # ---- wallet map (all-wallets capture + solscan extension + live graph) ----
  wallet-map-scan)           shift; cmd_wallet_map scan "$@" ;;
  wallet-map-stats)          shift; cmd_wallet_map stats "$@" ;;
  wallet-map-render)         shift; cmd_wallet_map render "$@" ;;
  wallet-map-serve)          shift; cmd_wallet_map serve "$@" ;;
  loom-serve)                shift; cmd_loom_serve "$@" ;;
  loom-clone)                shift; cmd_loom clone "$@" ;;
  loom-tenants)              shift; cmd_loom tenants ;;
  wallet-map-clear)          shift; cmd_wallet_map clear "$@" ;;
  # ---- bring everything up (local services + connector status) ----
  hf-endpoint-plan)          shift; cmd_hf_endpoint_plan ;;
  blender-mcp)               shift; cmd_blender_mcp "$@" ;;
  morph)                     shift; cmd_morph "$@" ;;
  app-gen)                   shift; cmd_deploy generate "$@" ;;
  deploy)                    shift; cmd_deploy deploy "$@" ;;
  app-list)                  shift; cmd_deploy list ;;
  gpu-status)                shift; cmd_gpu_status ;;
  up)                        shift; cmd_up up "$@" ;;
  up-status|status-all)      shift; cmd_up status "$@" ;;
  down)                      shift; cmd_up down "$@" ;;
  # ---- audio chromatize + recorded livestreams ----
  audio-chroma)              shift; cmd_audio_chroma "$@" ;;
  stream-list)               shift; cmd_stream_list "$@" ;;
  # ---- chain event → image/video render + webhook receiver ----
  chain-render-one)          shift; cmd_chain_render one "$@" ;;
  chain-render-tail)         shift; cmd_chain_render tail "$@" ;;
  chain-render-prompt)       shift; cmd_chain_render prompt "$@" ;;
  chain-render-sample)       shift; cmd_chain_render sample "$@" ;;
  solana-webhook-serve)      shift; cmd_solana_webhook serve "$@" ;;
  solana-webhook-test)       shift; cmd_solana_webhook test "$@" ;;
  # ---- HunyuanVideo worker (chain event → MP4 via MediaLab ComfyUI) ----
  hunyuan-run)               shift; cmd_hunyuan run "$@" ;;
  hunyuan-one)               shift; cmd_hunyuan one "$@" ;;
  hunyuan-status)            shift; cmd_hunyuan status "$@" ;;
  hunyuan-seed)              shift; cmd_hunyuan seed "$@" ;;
  hunyuan-reset-lock)        shift; cmd_hunyuan reset-lock "$@" ;;
  hunyuan-workflow-preview)  shift; cmd_hunyuan workflow-preview "$@" ;;
  # ---- godot chain feed (proxy → Godot autoload + wall scene) ----
  godot-chain-smoke)         shift; cmd_godot_chain_smoke "$@" ;;
  godot-chain-wall)          shift; cmd_godot_chain_wall "$@" ;;
  asset-gallery)             shift; cmd_asset_gallery "$@" ;;
  godot-issue-dev-token)     shift; cmd_godot_issue_dev_token "$@" ;;
  godot-ssot-serve)          shift; cmd_godot_ssot_serve "$@" ;;
  # ---- stream_encoder + embedding_index (continuous CLIP daemon) ----
  encoder-run)               shift; cmd_encoder run "$@" ;;
  encoder-stats)             shift; cmd_encoder stats "$@" ;;
  encoder-reset-lock)        shift; cmd_encoder reset-lock "$@" ;;
  encoder-one)               shift; cmd_encoder one "$@" ;;
  embed-ingest)              shift; cmd_embed_ingest "$@" ;;
  embed-save)                shift; cmd_embed save "$@" ;;
  embed-load)                shift; cmd_embed load "$@" ;;
  embed-stats)               shift; cmd_embed stats "$@" ;;
  embed-query)               shift; cmd_embed query-by-sentence "$@" ;;
  # ---- swap router (USDC↔SOL + USDC↔SUI + SOL↔SUI, 6 routes; live-gated) ----
  swap-routes)               shift; cmd_swap routes "$@" ;;
  swap-quote)                shift; cmd_swap quote "$@" ;;
  swap-execute)              shift; cmd_swap execute "$@" ;;
  # ---- the Loom (cc IS the Loom; this serves Loom cards as standalone HTML) ----
  loom-serve)                shift; cmd_loom_serve "$@" ;;
  loom-list)                 shift; cmd_loom_list "$@" ;;
  blob-to-unreal)            shift; cmd_blob_to_unreal "$@" ;;
  unreal-live-link)          shift; cmd_unreal_live_link "$@" ;;
  -*)                     red "unknown flag: $1" >&2; echo >&2; usage >&2; exit 1 ;;
  cells)                     shift; cmd_cells "$@" ;;
  recipes)                   shift; cmd_recipes "$@" ;;
  loop)                      shift; cmd_loop "$@" ;;
  *)                      cmd_freeform "$@" ;;
esac
