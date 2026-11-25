#!/usr/bin/env bash
#
# cc-role-check.sh — Check current agent role and emit context header
#
# Usage:
#   source cc-role-check.sh    # In current shell, sets CC_* vars
#   ./cc-role-check.sh status  # Show status only
#
# This script is designed to be sourced at the start of a cc session
# to ensure the correct role and scope are active.
#

set -euo pipefail

ROLE_STATE_FILE="/tmp/cc-agent-role.state"
MSPC_CLAUDE_MD="/data/Projects/MySpace++/CLAUDE.md"
GENTLY_CLAUDE_MD="/data/Projects/gently/CLAUDE.md"

get_current_role() {
    if [[ -f "$ROLE_STATE_FILE" ]]; then
        cat "$ROLE_STATE_FILE"
    else
        echo "none"
    fi
}

# If sourced, set environment variables based on current role
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Running directly (not sourced)
    case "${1:-status}" in
        status)
            role=$(get_current_role)
            echo "Current role: $role"
            if [[ "$role" == "mspc" ]]; then
                echo "Scope: /data/Projects/MySpace++/"
                echo "CLAUDE.md: $MSPC_CLAUDE_MD"
            elif [[ "$role" == "gently" ]]; then
                echo "Scope: /data/Projects/gently/"
                echo "CLAUDE.md: $GENTLY_CLAUDE_MD"
            else
                echo "No role set. Use agent-role-switch.sh to set."
            fi
            ;;
        *)
            echo "Usage: $0 status"
            ;;
    esac
else
    # Being sourced - export current role vars
    role=$(get_current_role)
    if [[ "$role" == "mspc" ]]; then
        export CC_SCOPE_LOCAL_ROOT="/data/Projects/MySpace++"
        export CC_AGENT_ROLE="mspc"
    elif [[ "$role" == "gently" ]]; then
        export CC_SCOPE_LOCAL_ROOT="/data/Projects/gently"
        export CC_AGENT_ROLE="gently"
    fi
fi
