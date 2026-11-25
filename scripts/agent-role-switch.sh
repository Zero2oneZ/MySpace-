#!/usr/bin/env bash
#
# agent-role-switch.sh — Switch between MySpace++ and GentlyOS agent roles
#
# Usage:
#   ./agent-role-switch.sh mspc     # Switch to MySpace++ agent role
#   ./agent-role-switch.sh gently   # Switch to GentlyOS agent role
#   ./agent-role-switch.sh status   # Show current role + active instructions
#   ./agent-role-switch.sh loop     # Start continuous loop (prompts for role each iteration)
#
# Both roles inherit from /home/tom/.claude/CLAUDE.md (constitutional architecture)
# and load project-specific CLAUDE.md instructions.
#

set -euo pipefail

# === CONFIG ===
MSPC_CLAUDE_MD="/data/Projects/MySpace++/CLAUDE.md"
GENTLY_CLAUDE_MD="/data/Projects/gently/CLAUDE.md"
COMMS_FILE_MSPC="/data/Projects/MySpace++/studio/docs/NOTES-FOR-INFERANCE.md"
COMMS_FILE_GENTLY="/data/Projects/gently/docs/NOTES-FOR-INFERENCE.md"
ROLE_STATE_FILE="/tmp/cc-agent-role.state"
DEFAULT_MODEL="kimi-k2.6:cloud"

# === COLORS ===
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# === HELPERS ===

log_info() {
    echo -e "${CYAN}[INFO]${NC} $1"
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

# === ROLE FUNCTIONS ===

get_current_role() {
    if [[ -f "$ROLE_STATE_FILE" ]]; then
        cat "$ROLE_STATE_FILE"
    else
        echo "none"
    fi
}

set_role() {
    local role="$1"
    echo "$role" > "$ROLE_STATE_FILE"
}

show_status() {
    echo ""
    echo "=========================================="
    echo "     CC AGENT ROLE STATUS"
    echo "=========================================="
    echo ""

    local current_role
    current_role=$(get_current_role)

    if [[ "$current_role" == "mspc" ]]; then
        echo -e "Current Role: ${GREEN}MySpace++ Agent${NC}"
        echo "Scope:        /data/Projects/MySpace++/"
    elif [[ "$current_role" == "gently" ]]; then
        echo -e "Current Role: ${GREEN}GentlyOS Agent${NC}"
        echo "Scope:        /data/Projects/gently/"
    else
        echo -e "Current Role: ${YELLOW}NONE (not set)${NC}"
        echo "Scope:        (use 'm' or 'g' to set)"
    fi

    echo ""
    echo "Model:        $DEFAULT_MODEL"
    echo ""
    echo "=========================================="
    echo "     ACTIVE INSTRUCTIONS"
    echo "=========================================="
    echo ""

    # Always show both project instruction summaries
    echo -e "${MAGENTA}MySpace++ (Python/DAG scope):${NC}"
    if [[ -f "$MSPC_CLAUDE_MD" ]]; then
        echo "  File: $MSPC_CLAUDE_MD"
        echo "  Key points:"
        echo "    - Communicates with GentlyOS via: studio/docs/NOTES-FOR-INFERANCE.md"
        echo "    - Core: cc dispatcher, 28-table SQLite DB, Streamlit studio"
        echo "    - Phases: 0 (core) → 5 (avatar pipeline)"
        echo "    - Hard rule: Read NOTES-FOR-INFERANCE.md at session start"
    else
        echo "  ${RED}FILE NOT FOUND: $MSPC_CLAUDE_MD${NC}"
    fi

    echo ""
    echo -e "${MAGENTA}GentlyOS (Rust/.bb scope):${NC}"
    if [[ -f "$GENTLY_CLAUDE_MD" ]]; then
        echo "  File: $GENTLY_CLAUDE_MD"
        echo "  Key points:"
        echo "    - Communicates with MySpace++ via: docs/NOTES-FOR-INFERENCE.md"
        echo "    - Core: 175 Rust crates, .bb runtime, Crystal DAG"
        echo "    - 12 domains: core, intelligence, runtime, orc, identity, network, chain, mcp, models, social, security, discovery"
        echo "    - Hard rule: Read SYNC-PROTOCOL.md before cross-session work"
    else
        echo "  ${RED}FILE NOT FOUND: $GENTLY_CLAUDE_MD${NC}"
    fi

    echo ""
    echo "=========================================="
    echo "     CROSS-SESSION COMMS FILES"
    echo "=========================================="
    echo ""

    echo -e "${CYAN}MySpace++ side:${NC} $COMMS_FILE_MSPC"
    if [[ -f "$COMMS_FILE_MSPC" ]]; then
        echo "  Status: EXISTS ($(wc -l < "$COMMS_FILE_MSPC") lines)"
    else
        echo "  Status: ${RED}NOT FOUND${NC}"
    fi

    echo -e "${CYAN}GentlyOS side:${NC}   $COMMS_FILE_GENTLY"
    if [[ -f "$COMMS_FILE_GENTLY" ]]; then
        echo "  Status: EXISTS ($(wc -l < "$COMMS_FILE_GENTLY") lines)"
    else
        echo "  Status: ${RED}NOT FOUND${NC}"
    fi

    echo ""
    echo "=========================================="
    echo "     QUICK SWITCH"
    echo "=========================================="
    echo ""
    echo "  Switch to MySpace++:  $0 mspc"
    echo "  Switch to GentlyOS:   $0 gently"
    echo "  Start loop mode:      $0 loop"
    echo ""
}

activate_mspc_role() {
    log_info "Activating MySpace++ agent role..."

    # Validate files exist
    if [[ ! -f "$MSPC_CLAUDE_MD" ]]; then
        log_error "MySpace++ CLAUDE.md not found: $MSPC_CLAUDE_MD"
        return 1
    fi

    # Set the role
    set_role "mspc"

    # Export environment variables for cc
    export CC_SCOPE_LOCAL_ROOT="/data/Projects/MySpace++"
    export CC_PROJECT_LOCAL="tom"
    export CC_AGENT_ROLE="mspc"

    log_success "MySpace++ role activated"
    echo ""
    echo "Environment:"
    echo "  CC_SCOPE_LOCAL_ROOT=$CC_SCOPE_LOCAL_ROOT"
    echo "  CC_PROJECT_LOCAL=$CC_PROJECT_LOCAL"
    echo "  CC_AGENT_ROLE=$CC_AGENT_ROLE"
    echo ""
    echo "To start a session with this role:"
    echo "  cc -model $DEFAULT_MODEL"
    echo ""
    echo "First steps in session:"
    echo "  1. Read: $MSPC_CLAUDE_MD"
    echo "  2. Read: $COMMS_FILE_MSPC"
    echo "  3. Run:  cc -context"
}

activate_gently_role() {
    log_info "Activating GentlyOS agent role..."

    # Validate files exist
    if [[ ! -f "$GENTLY_CLAUDE_MD" ]]; then
        log_error "GentlyOS CLAUDE.md not found: $GENTLY_CLAUDE_MD"
        return 1
    fi

    # Set the role
    set_role "gently"

    # Export environment variables for cc
    export CC_SCOPE_LOCAL_ROOT="/data/Projects/gently"
    export CC_PROJECT_LOCAL="tom"
    export CC_AGENT_ROLE="gently"

    log_success "GentlyOS role activated"
    echo ""
    echo "Environment:"
    echo "  CC_SCOPE_LOCAL_ROOT=$CC_SCOPE_LOCAL_ROOT"
    echo "  CC_PROJECT_LOCAL=$CC_PROJECT_LOCAL"
    echo "  CC_AGENT_ROLE=$CC_AGENT_ROLE"
    echo ""
    echo "To start a session with this role:"
    echo "  cc -model $DEFAULT_MODEL"
    echo ""
    echo "First steps in session:"
    echo "  1. Read: $GENTLY_CLAUDE_MD"
    echo "  2. Read: $COMMS_FILE_GENTLY"
    echo "  3. Read: /data/Projects/gently/docs/SYNC-PROTOCOL.md"
    echo "  4. Run:  cc -context"
}

# === LOOP MODE ===

run_loop() {
    log_info "Starting AGENT ROLE LOOP mode..."
    echo ""
    echo "In loop mode, you will be prompted to select a role each iteration."
    echo "Press Ctrl+C to exit the loop."
    echo ""

    local iteration=0

    while true; do
        ((iteration++))
        echo ""
        echo "=========================================="
        echo "     LOOP ITERATION #$iteration"
        echo "=========================================="
        echo ""

        echo "Select role for this iteration:"
        echo "  [m] MySpace++ agent"
        echo "  [g] GentlyOS agent"
        echo "  [s] Show status"
        echo "  [q] Quit loop"
        echo ""
        read -rp "Choice: " choice

        case "$choice" in
            m|M|mspc)
                activate_mspc_role
                ;;
            g|gently)
                activate_gently_role
                ;;
            s|status)
                show_status
                ;;
            q|quit|exit)
                log_info "Exiting loop mode."
                break
                ;;
            *)
                log_warn "Unknown choice: $choice"
                ;;
        esac

        echo ""
        read -rp "Press Enter to continue to next iteration..."
    done
}

# === MAIN ===

main() {
    local cmd="${1:-status}"

    case "$cmd" in
        mspc|mspace|m)
            activate_mspc_role
            ;;
        gently|g|gent)
            activate_gently_role
            ;;
        status|s|show)
            show_status
            ;;
        loop|l)
            run_loop
            ;;
        help|h|-help|--help)
            echo "Usage: $0 {mspc|gently|status|loop|help}"
            echo ""
            echo "Commands:"
            echo "  mspc    - Activate MySpace++ agent role"
            echo "  gently  - Activate GentlyOS agent role"
            echo "  status  - Show current role and active instructions"
            echo "  loop    - Start interactive loop (prompt for role each iteration)"
            echo "  help    - Show this help message"
            ;;
        *)
            log_error "Unknown command: $cmd"
            echo "Use '$0 help' for usage."
            exit 1
            ;;
    esac
}

main "$@"
