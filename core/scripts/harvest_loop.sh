#!/usr/bin/env bash
# ============================================================================
# harvest_loop.sh — long-running harvest daemon (Phase 2.3)
#
# Cycles through harvest activities on EPOCH-modulo cron-style intervals,
# invoking the EXISTING tools (pinterest connector, noun_project, doc_parser,
# dag_loop, recursive_workflows). Never duplicates their logic — just
# orchestrates the cadence.
#
# Schedule (sleep N s per tick; default N=60):
#   EPOCH % 300    →  noun_project random query x10           (every  5 min)
#   EPOCH % 900    →  pinterest re-fetch curated category     (every 15 min)
#   EPOCH % 1800   →  pop next URL from _doc_queue            (every 30 min)
#   EPOCH % 3600   →  dag_loop cycle + recursive_workflows    (every 60 min)
#   EPOCH % 604800 →  prune icons older than 30 days          (weekly)
#
# Defensive:
#   - Connectivity-gated (no API key → skip silently with one log line)
#   - Every python invocation wrapped in `timeout` so a stuck call can't
#     block the loop forever
#   - PID tracked at ~/.cc/harvest_loop.pid so start/stop/status are clean
#   - HARVEST_FORCE_ALL=1 forces every schedule to fire (smoke test)
#   - MYSPACE_ROOT lets the daemon survive cwd changes
#
# CLI:
#   bash harvest_loop.sh start [--interval N]
#   bash harvest_loop.sh stop
#   bash harvest_loop.sh status
#   bash harvest_loop.sh tick
# ============================================================================
set -u
# Note: intentionally NOT `set -e` — a single harvest failure must not kill
# the daemon. Each step is wrapped + logged + we keep going.

MYSPACE_ROOT="${MYSPACE_ROOT:-/data/Projects/MySpace++}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

CC_DIR="${HOME}/.cc"
LOG_FILE="${CC_DIR}/harvest_loop.log"
PID_FILE="${CC_DIR}/harvest_loop.pid"

DOC_QUEUE_DIR="${MYSPACE_ROOT}/studio/assets/_doc_queue"
SEED_QUERIES_FILE="${MYSPACE_ROOT}/studio/assets/_corpus/seed_queries.txt"
ICONS_DIR="${MYSPACE_ROOT}/studio/assets/_corpus/icons"

DEFAULT_SEED_QUERIES=("arrow" "settings" "menu" "save" "edit" "delete" "share" "upload" "download" "search")
PINTEREST_CATEGORIES=("blueprint" "furniture" "interior" "exterior" "lighting" "kitchen" "avatar_ref" "style_ref")

TIMEOUT_SHORT=30      # noun_project search, pinterest call
TIMEOUT_MEDIUM=120    # doc_parser parse-url
TIMEOUT_LONG=300      # dag_loop / recursive_workflows

# ---------------------------------------------------------------------------
# logging — one line per completed action, ISO-8601 UTC, sortable
# ---------------------------------------------------------------------------
mkdir -p "${CC_DIR}"

_iso_now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

log_line() {
    # log_line <kind> <message>
    local kind="$1"; shift
    local msg="$*"
    printf '%s %s %s\n' "$(_iso_now)" "${kind}" "${msg}" >> "${LOG_FILE}"
}

# ---------------------------------------------------------------------------
# connectivity gates — skip silently when env keys are absent
# ---------------------------------------------------------------------------
_load_dotenv_if_present() {
    local env_file="${MYSPACE_ROOT}/.env"
    if [[ -r "${env_file}" ]]; then
        # shellcheck disable=SC1090
        set -a; source "${env_file}" 2>/dev/null || true; set +a
    fi
}

_has_pinterest_key() {
    [[ -n "${PINTREST_API:-}" || -n "${PINTEREST_API:-}" ]]
}

_has_noun_project_key() {
    [[ -n "${NOUN_PROJECT_KEY:-}" \
        || -n "${NOUNPROJECT_API_KEY:-}" \
        || -n "${NOUN_PROJECT_SECRET:-}" \
        || -n "${NOUNPROJECT_SECRET_KEY:-}" ]]
}

# ---------------------------------------------------------------------------
# seed_queries.txt — bootstrap if missing
# ---------------------------------------------------------------------------
ensure_seed_queries() {
    if [[ ! -f "${SEED_QUERIES_FILE}" ]]; then
        mkdir -p "$(dirname "${SEED_QUERIES_FILE}")"
        printf '%s\n' "${DEFAULT_SEED_QUERIES[@]}" > "${SEED_QUERIES_FILE}"
        log_line "seed_queries" "bootstrapped default 10 queries at ${SEED_QUERIES_FILE}"
    fi
}

# ---------------------------------------------------------------------------
# HARVEST 1 — noun_project random query x N (every 5 min)
# ---------------------------------------------------------------------------
harvest_noun_project() {
    if ! _has_noun_project_key; then
        log_line "noun_project" "skipped — NOUN_PROJECT_KEY/NOUNPROJECT_API_KEY unset"
        return 0
    fi
    ensure_seed_queries
    if [[ ! -s "${SEED_QUERIES_FILE}" ]]; then
        log_line "noun_project" "skipped — seed_queries.txt empty"
        return 0
    fi
    local query
    query="$(shuf -n 1 "${SEED_QUERIES_FILE}" 2>/dev/null || head -n 1 "${SEED_QUERIES_FILE}")"
    if [[ -z "${query}" ]]; then
        log_line "noun_project" "skipped — could not pick a query"
        return 0
    fi
    local out
    out="$(timeout "${TIMEOUT_SHORT}" "${PYTHON_BIN}" \
                "${MYSPACE_ROOT}/core/lib/third_party/noun_project.py" \
                search --query "${query}" --limit 10 2>&1)" || {
        log_line "noun_project" "FAILED query=\"${query}\" — exit=$? out=$(printf '%s' "${out}" | tr '\n' ' ' | cut -c1-160)"
        return 0
    }
    # Best-effort parse: look for "success": true or count from preview
    local success_flag
    success_flag="$(printf '%s' "${out}" | grep -o '"success": *true' | head -n1)"
    if [[ -n "${success_flag}" ]]; then
        log_line "noun_project" "search \"${query}\" -> ok limit=10"
    else
        log_line "noun_project" "search \"${query}\" -> reply received (see connector log for crystal)"
    fi
}

# ---------------------------------------------------------------------------
# HARVEST 2 — pinterest curated re-fetch (every 15 min)
# Calls PinterestConnector.harvest_curated(category) via -c snippet, since
# pinterest.py has no CLI of its own.
# ---------------------------------------------------------------------------
harvest_pinterest() {
    if ! _has_pinterest_key; then
        log_line "pinterest" "skipped — PINTREST_API unset"
        return 0
    fi
    # Pick a random curated category
    local n="${#PINTEREST_CATEGORIES[@]}"
    local idx=$(( RANDOM % n ))
    local category="${PINTEREST_CATEGORIES[$idx]}"

    local snippet
    snippet="$(cat <<PYEOF
import json, sys, os
sys.path.insert(0, os.path.join("${MYSPACE_ROOT}", "core", "lib"))
try:
    from third_party.pinterest import PinterestConnector
    from third_party.base import ConnectionConfig
    cfg = ConnectionConfig(service="pinterest")
    c = PinterestConnector(cfg)
    res = c.harvest_curated("${category}", limit_per_query=5)
    total = sum(len(v or []) for v in (res or {}).values())
    print(json.dumps({"ok": True, "category": "${category}",
                      "queries": len(res or {}), "pins": total}))
except Exception as e:
    print(json.dumps({"ok": False, "category": "${category}",
                      "error": "%s: %s" % (type(e).__name__, e)}))
PYEOF
)"
    local out
    out="$(timeout "${TIMEOUT_MEDIUM}" "${PYTHON_BIN}" -c "${snippet}" 2>&1)" || {
        log_line "pinterest" "FAILED category=${category} — exit=$? out=$(printf '%s' "${out}" | tr '\n' ' ' | cut -c1-160)"
        return 0
    }
    # Pull last line (Python json print)
    local last
    last="$(printf '%s' "${out}" | tail -n 1)"
    log_line "pinterest" "harvest_curated category=${category} -> ${last}"
}

# ---------------------------------------------------------------------------
# HARVEST 3 — pop next URL from _doc_queue (every 30 min)
# *.url → mv to *.parsing → doc_parser → mv to *.done (or *.failed)
# ---------------------------------------------------------------------------
harvest_doc_queue() {
    mkdir -p "${DOC_QUEUE_DIR}"
    local job_file=""
    # Find oldest *.url
    while IFS= read -r f; do
        job_file="$f"
        break
    done < <(find "${DOC_QUEUE_DIR}" -maxdepth 1 -type f -name '*.url' -printf '%T@ %p\n' 2>/dev/null \
                | sort -n | awk '{ $1=""; sub(/^ /, ""); print }')

    if [[ -z "${job_file}" ]]; then
        log_line "doc_queue" "empty — no *.url to process"
        return 0
    fi

    local base="${job_file%.url}"
    local parsing="${base}.parsing"
    local done_file="${base}.done"
    local failed="${base}.failed"

    # Job-file format (first non-comment, non-empty line):
    #   <adapter> <url>
    # Lines starting with '#' are ignored. If only a URL is present, default
    # adapter = "godot" (most common in this session).
    local line
    line="$(grep -E -v '^[[:space:]]*(#|$)' "${job_file}" | head -n 1)"
    local adapter url
    adapter="$(awk '{print $1}' <<<"${line}")"
    url="$(awk '{$1=""; sub(/^ /, ""); print}' <<<"${line}")"
    if [[ -z "${url}" ]]; then
        # single-field line: treat whole line as URL, adapter=godot
        url="${adapter}"
        adapter="godot"
    fi
    if [[ -z "${url}" ]]; then
        mv -f "${job_file}" "${failed}" 2>/dev/null || true
        log_line "doc_queue" "FAILED ${job_file} — empty URL"
        return 0
    fi

    mv -f "${job_file}" "${parsing}" 2>/dev/null || {
        log_line "doc_queue" "FAILED rename ${job_file} -> ${parsing}"
        return 0
    }

    local out
    out="$(timeout "${TIMEOUT_MEDIUM}" "${PYTHON_BIN}" \
                "${MYSPACE_ROOT}/core/lib/doc_parser.py" \
                parse-url "${adapter}" "${url}" 2>&1)"
    local rc=$?
    if [[ $rc -eq 0 ]]; then
        mv -f "${parsing}" "${done_file}" 2>/dev/null || true
        local last; last="$(printf '%s' "${out}" | tail -n 1)"
        log_line "doc_parser" "parse-url adapter=${adapter} url=${url} -> ${last}"
    else
        mv -f "${parsing}" "${failed}" 2>/dev/null || true
        log_line "doc_parser" "FAILED adapter=${adapter} url=${url} exit=${rc} out=$(printf '%s' "${out}" | tr '\n' ' ' | cut -c1-160)"
    fi
}

# ---------------------------------------------------------------------------
# HARVEST 4 — dag_loop cycle + recursive_workflows all (every 60 min)
# Prefers `cc loop cycle` when the cc dispatcher exists, falls back to the
# raw python.
# ---------------------------------------------------------------------------
harvest_dag_loop() {
    local cc_bin="${MYSPACE_ROOT}/core/cc.sh"
    local out rc
    if [[ -x "${cc_bin}" ]]; then
        out="$(timeout "${TIMEOUT_LONG}" "${cc_bin}" loop cycle 2>&1)"; rc=$?
        if [[ $rc -ne 0 ]]; then
            # fall back to direct script
            out="$(timeout "${TIMEOUT_LONG}" "${PYTHON_BIN}" "${MYSPACE_ROOT}/core/lib/dag_loop.py" cycle 2>&1)"; rc=$?
        fi
    else
        out="$(timeout "${TIMEOUT_LONG}" "${PYTHON_BIN}" "${MYSPACE_ROOT}/core/lib/dag_loop.py" cycle 2>&1)"; rc=$?
    fi

    if [[ $rc -eq 0 ]]; then
        # extract crystal short-hash if visible
        local crystal
        crystal="$(printf '%s' "${out}" | grep -o '"crystal": *"[^"]*"' | head -n 1 | sed 's/.*"\([^"]*\)"$/\1/' | cut -c1-16)"
        log_line "dag_loop" "cycle ok crystal=${crystal:-unknown}"
    else
        log_line "dag_loop" "FAILED cycle exit=${rc} out=$(printf '%s' "${out}" | tr '\n' ' ' | cut -c1-160)"
    fi

    out="$(timeout "${TIMEOUT_LONG}" "${PYTHON_BIN}" "${MYSPACE_ROOT}/core/lib/recursive_workflows.py" all 2>&1)"; rc=$?
    if [[ $rc -eq 0 ]]; then
        local persisted
        persisted="$(printf '%s' "${out}" | grep -o '"persisted_to_disk": *[0-9]*' | head -n 1 | awk -F: '{print $2}' | tr -d ' ')"
        log_line "recursive_workflows" "all ok persisted=${persisted:-?}"
    else
        log_line "recursive_workflows" "FAILED all exit=${rc} out=$(printf '%s' "${out}" | tr '\n' ' ' | cut -c1-160)"
    fi
}

# ---------------------------------------------------------------------------
# HARVEST 5 — disk hygiene (weekly): prune icons older than 30 days
# ---------------------------------------------------------------------------
harvest_disk_hygiene() {
    if [[ ! -d "${ICONS_DIR}" ]]; then
        log_line "disk_hygiene" "skipped — icons dir absent: ${ICONS_DIR}"
        return 0
    fi
    local deleted
    deleted="$(find "${ICONS_DIR}" -mtime +30 -type f -print -delete 2>/dev/null | wc -l)"
    log_line "disk_hygiene" "pruned ${deleted} files older than 30d from icons/"
}

# ---------------------------------------------------------------------------
# tick() — one pass over all schedules
# ---------------------------------------------------------------------------
tick() {
    _load_dotenv_if_present
    local epoch
    epoch="$(date +%s)"
    local force="${HARVEST_FORCE_ALL:-0}"

    # noun_project — every 5 min
    if [[ "${force}" == "1" ]] || (( epoch % 300 == 0 )); then
        harvest_noun_project
    fi

    # pinterest — every 15 min
    if [[ "${force}" == "1" ]] || (( epoch % 900 == 0 )); then
        harvest_pinterest
    fi

    # doc_queue — every 30 min
    if [[ "${force}" == "1" ]] || (( epoch % 1800 == 0 )); then
        harvest_doc_queue
    fi

    # dag_loop + recursive_workflows — every 60 min
    if [[ "${force}" == "1" ]] || (( epoch % 3600 == 0 )); then
        harvest_dag_loop
    fi

    # disk hygiene — weekly (7d = 604800s)
    if [[ "${force}" == "1" ]] || (( epoch % 604800 == 0 )); then
        harvest_disk_hygiene
    fi
}

# ---------------------------------------------------------------------------
# daemon loop — runs forever, calls tick() every INTERVAL seconds
# ---------------------------------------------------------------------------
run_daemon() {
    local interval="${1:-60}"
    log_line "daemon" "start pid=$$ interval=${interval}s root=${MYSPACE_ROOT}"
    # write PID for stop/status
    printf '%s\n' "$$" > "${PID_FILE}"
    trap '_on_exit' EXIT INT TERM
    while true; do
        tick || true
        sleep "${interval}" || break
    done
}

_on_exit() {
    log_line "daemon" "stop pid=$$"
    rm -f "${PID_FILE}" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# CLI dispatcher
# ---------------------------------------------------------------------------
cmd_start() {
    local interval=60
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --interval) interval="$2"; shift 2 ;;
            *) shift ;;
        esac
    done
    # If a PID file exists and the process is alive, refuse
    if [[ -f "${PID_FILE}" ]]; then
        local old_pid; old_pid="$(cat "${PID_FILE}" 2>/dev/null || echo "")"
        if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
            printf 'already running pid=%s\n' "${old_pid}"
            return 0
        else
            rm -f "${PID_FILE}" 2>/dev/null || true
        fi
    fi
    run_daemon "${interval}"
}

cmd_stop() {
    if [[ ! -f "${PID_FILE}" ]]; then
        printf 'not running (no pidfile)\n'
        return 0
    fi
    local pid; pid="$(cat "${PID_FILE}" 2>/dev/null || echo "")"
    if [[ -z "${pid}" ]]; then
        rm -f "${PID_FILE}" 2>/dev/null || true
        printf 'not running (empty pidfile)\n'
        return 0
    fi
    if kill -0 "${pid}" 2>/dev/null; then
        kill -TERM "${pid}" 2>/dev/null || true
        # give it a moment to clean up its own pidfile
        local i=0
        while [[ $i -lt 20 ]] && kill -0 "${pid}" 2>/dev/null; do
            sleep 0.1
            i=$((i + 1))
        done
        if kill -0 "${pid}" 2>/dev/null; then
            kill -KILL "${pid}" 2>/dev/null || true
        fi
        log_line "daemon" "stop_requested pid=${pid}"
        printf 'stopped pid=%s\n' "${pid}"
    else
        printf 'stale pidfile pid=%s — removing\n' "${pid}"
    fi
    rm -f "${PID_FILE}" 2>/dev/null || true
}

cmd_status() {
    if [[ -f "${PID_FILE}" ]]; then
        local pid; pid="$(cat "${PID_FILE}" 2>/dev/null || echo "")"
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            printf 'running pid=%s\n' "${pid}"
            return 0
        fi
    fi
    printf 'stopped\n'
}

cmd_tick() {
    tick
    printf 'tick complete\n'
}

main() {
    local cmd="${1:-}"; shift || true
    case "${cmd}" in
        start)  cmd_start "$@" ;;
        stop)   cmd_stop ;;
        status) cmd_status ;;
        tick)   cmd_tick ;;
        ""|-h|--help|help)
            cat <<EOF
harvest_loop.sh — long-running harvest daemon (Phase 2.3)

usage:
  bash harvest_loop.sh start [--interval N]   # default N=60s
  bash harvest_loop.sh stop
  bash harvest_loop.sh status
  bash harvest_loop.sh tick                    # one pass + exit

env:
  MYSPACE_ROOT       (default: /data/Projects/MySpace++)
  HARVEST_FORCE_ALL  set to 1 to force every schedule to fire this tick
  PYTHON_BIN         (default: python3)

paths:
  log    ${LOG_FILE}
  pid    ${PID_FILE}
EOF
            ;;
        *)
            printf 'unknown command: %s\n' "${cmd}" >&2
            return 2
            ;;
    esac
}

main "$@"
