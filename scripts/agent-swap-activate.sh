#!/usr/bin/env bash
#
# agent-swap-activate.sh — Full swap activation for agent handoff
#
# Usage:
#   ./agent-swap-activate.sh mspc     # Full swap to MySpace++ role
#   ./agent-swap-activate.sh gently   # Full swap to GentlyOS role
#   ./agent-swap-activate.sh auto     # Auto-detect from ToDo-JobBoard.jsonl tail
#
# This script executes the complete 6-step swap protocol:
#   1. Save old role state
#   2. Activate new role
#   3. Source environment variables
#   4. Display verification
#   5. Remind to read comms file
#   6. Log swap in JSONL
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ROLE_STATE_FILE="/tmp/cc-agent-role.state"
JSONL_FILE="$PROJECT_ROOT/ToDo-JobBoard.jsonl"
MSPC_COMMS="/data/Projects/MySpace++/studio/docs/NOTES-FOR-INFERANCE.md"
GENTLY_COMMS="/data/Projects/gently/docs/NOTES-FOR-INFERENCE.md"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log_step() {
    echo -e "${CYAN}[STEP $1]${NC} $2"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

save_old_role() {
    if [[ -f "$ROLE_STATE_FILE" ]]; then
        cp "$ROLE_STATE_FILE" "${ROLE_STATE_FILE}.old"
    else
        echo "none" > "${ROLE_STATE_FILE}.old"
    fi
}

activate_role() {
    local role="$1"
    echo "$role" > "$ROLE_STATE_FILE"

    if [[ "$role" == "mspc" ]]; then
        export CC_SCOPE_LOCAL_ROOT="/data/Projects/MySpace++"
        export CC_AGENT_ROLE="mspc"
    elif [[ "$role" == "gently" ]]; then
        export CC_SCOPE_LOCAL_ROOT="/data/Projects/gently"
        export CC_AGENT_ROLE="gently"
    fi
}

get_comms_file() {
    local role="$1"
    if [[ "$role" == "mspc" ]]; then
        echo "$MSPC_COMMS"
    elif [[ "$role" == "gently" ]]; then
        echo "$GENTLY_COMMS"
    fi
}

log_swap_to_jsonl() {
    local to_role="$1"
    local from_role
    from_role=$(cat "${ROLE_STATE_FILE}.old" 2>/dev/null || echo "none")
    local ts
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    local unix
    unix=$(date +%s)
    local agent
    agent="$(whoami)-$(hostname)"

    # Append swap event to JSONL
    jq -c -n \
      --arg ts "$ts" \
      --arg unix "$unix" \
      --arg event "swap" \
      --arg from_role "$from_role" \
      --arg to_role "$to_role" \
      --arg agent "$agent" \
      '{ts: $ts, unix: $unix, event: $event, from_role: $from_role, to_role: $to_role, agent: $agent}' \
      >> "$JSONL_FILE"

    echo -e "${GREEN}[LOGGED]${NC} Swap event appended to $JSONL_FILE"
}

detect_role_from_jsonl() {
    # Read the latest task entry from JSONL and extract next_agent
    if [[ ! -f "$JSONL_FILE" ]]; then
        log_error "JSONL file not found: $JSONL_FILE"
        return 1
    fi

    local latest_agent
    latest_agent=$(tail -1 "$JSONL_FILE" | jq -r '.next_agent // empty' 2>/dev/null)

    if [[ -z "$latest_agent" ]]; then
        log_warn "No next_agent found in JSONL tail, checking Task Board..."
        # Fallback: parse the markdown table
        local board_agent
        board_agent=$(grep -E '^\| T-[0-9]+' "$PROJECT_ROOT/ToDo-JobBoard.md" | head -1 | awk -F'|' '{print $4}' | tr -d ' ')

        if [[ -z "$board_agent" ]]; then
            log_error "Could not detect role from Task Board"
            return 1
        fi

        latest_agent="$board_agent"
    fi

    # Map agent prefix to role
    if [[ "$latest_agent" == mspc-* ]] || [[ "$latest_agent" == "master" ]] || \
       [[ "$latest_agent" == dag-scanner ]] || [[ "$latest_agent" == svg-emitter ]] || \
       [[ "$latest_agent" == workflow-library ]] || [[ "$latest_agent" == tts-pipeline ]] || \
       [[ "$latest_agent" == audio-qa ]]; then
        echo "mspc"
    elif [[ "$latest_agent" == gently-* ]] || [[ "$latest_agent" == cross-link ]]; then
        echo "gently"
    else
        log_warn "Unknown agent prefix: $latest_agent, defaulting to mspc"
        echo "mspc"
    fi
}

run_swap_activation() {
    local target_role="$1"

    echo ""
    echo "=========================================="
    echo "     AGENT SWAP ACTIVATION"
    echo "=========================================="
    echo ""

    local old_role
    old_role=$(cat "${ROLE_STATE_FILE}.old" 2>/dev/null || echo "none")

    log_step "1" "Saving old role state: $old_role"
    save_old_role
    log_success "Old role saved to ${ROLE_STATE_FILE}.old"

    log_step "2" "Activating new role: $target_role"
    activate_role "$target_role"
    log_success "Role activated: $target_role"

    log_step "3" "Sourcing environment variables"
    echo "  CC_SCOPE_LOCAL_ROOT=$CC_SCOPE_LOCAL_ROOT"
    echo "  CC_AGENT_ROLE=$CC_AGENT_ROLE"
    log_success "Environment exported"

    log_step "4" "Verifying activation"
    local comms_file
    comms_file=$(get_comms_file "$target_role")

    echo ""
    echo "Current Role: $target_role"
    if [[ "$target_role" == "mspc" ]]; then
        echo "Scope:        /data/Projects/MySpace++/"
        echo "CLAUDE.md:    /data/Projects/MySpace++/CLAUDE.md"
    elif [[ "$target_role" == "gently" ]]; then
        echo "Scope:        /data/Projects/gently/"
        echo "CLAUDE.md:    /data/Projects/gently/CLAUDE.md"
    fi
    echo "Comms File:   $comms_file"

    if [[ -f "$comms_file" ]]; then
        echo -e "Comms Status: ${GREEN}EXISTS ($(wc -l < "$comms_file") lines)${NC}"
    else
        echo -e "Comms Status: ${RED}NOT FOUND${NC}"
    fi
    log_success "Verification complete"

    log_step "5" "Reading comms file (first 5 lines)"
    echo ""
    echo "--- Comms File Preview ---"
    head -5 "$comms_file" 2>/dev/null || log_warn "Could not read comms file"
    echo "--- End Preview ---"
    echo ""
    echo -e "${YELLOW}REMINDER:${NC} Read full comms file before proceeding:"
    if [[ "$target_role" == "mspc" ]]; then
        echo "  cat $MSPC_COMMS"
    else
        echo "  cat $GENTLY_COMMS"
        echo "  cat /data/Projects/gently/docs/SYNC-PROTOCOL.md"
    fi
    echo ""

    log_step "6" "Logging swap to JSONL"
    log_swap_to_jsonl "$target_role"

    echo ""
    echo "=========================================="
    echo "     SWAP ACTIVATION COMPLETE"
    echo "=========================================="
    echo ""
    echo "Ready to execute tasks as: $target_role"
    echo ""
    echo "Next steps:"
    echo "  - Run: cc -context"
    echo "  - Read project CLAUDE.md"
    echo "  - Check ToDo-JobBoard.md for active task"
    echo ""
}

# Main
main() {
    local cmd="${1:-}"

    if [[ -z "$cmd" ]]; then
        echo "Usage: $0 {mspc|gently|auto}"
        echo ""
        echo "  mspc   - Full swap to MySpace++ role"
        echo "  gently - Full swap to GentlyOS role"
        echo "  auto   - Auto-detect role from ToDo-JobBoard.jsonl"
        exit 1
    fi

    local target_role

    case "$cmd" in
        mspc|m)
            target_role="mspc"
            ;;
        gently|g)
            target_role="gently"
            ;;
        auto|a)
            log_step "0" "Auto-detecting role from Task Board..."
            target_role=$(detect_role_from_jsonl)
            if [[ -n "$target_role" ]]; then
                log_success "Detected role: $target_role"
            else
                log_error "Failed to auto-detect role"
                exit 1
            fi
            ;;
        *)
            log_error "Unknown command: $cmd"
            echo "Usage: $0 {mspc|gently|auto}"
            exit 1
            ;;
    esac

    run_swap_activation "$target_role"
}

main "$@"
