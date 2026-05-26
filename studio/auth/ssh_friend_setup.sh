#!/usr/bin/env bash
# ssh_friend_setup.sh — onboard / revoke / list friend SSH access.
#
# Friend-scoped GPU sharing model:
#   - Each friend gets a port-forward-only SSH key authorization on YOUR box.
#   - The key is restricted: no shell, no pty, no command exec — only the
#     tunnel that exposes localhost:8510 (Wardrobe) etc. to their machine.
#   - The studio's auth/gate.py then enforces username + IP-binding on top.
#
# Usage:
#   ./ssh_friend_setup.sh add    Jamie  /path/to/jamie.pub
#   ./ssh_friend_setup.sh list
#   ./ssh_friend_setup.sh revoke Jamie
#   ./ssh_friend_setup.sh share  Jamie    # print friend-facing SSH command
#
# Notes:
#   - This script ONLY touches ~/.ssh/authorized_keys. It does not start
#     sshd, does not open firewall ports.
#   - Lines are tagged `# myspace-friend:<name>` so this script can find +
#     remove them later. Don't hand-edit those tags.

set -euo pipefail

AUTH_KEYS="${SSH_AUTHORIZED_KEYS:-$HOME/.ssh/authorized_keys}"
TAG_PREFIX="# myspace-friend:"
DEFAULT_FORWARD_PORTS="${MYSPACE_FORWARD_PORTS:-8510 8501 8511}"

# Allow override of the SSH user@host the friend uses to connect. Default
# tries to detect the box's reachable hostname.
detect_host() {
  local h
  h="$(hostname -f 2>/dev/null || hostname 2>/dev/null || echo "your-host")"
  echo "$h"
}
HOST="${MYSPACE_SSH_HOST:-$(detect_host)}"
SSH_USER="${MYSPACE_SSH_USER:-$USER}"

# --- colored output ---------------------------------------------------------
if [ -t 1 ]; then
  red()    { printf '\033[31m%s\033[0m\n' "$*"; }
  green()  { printf '\033[32m%s\033[0m\n' "$*"; }
  yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
  cyan()   { printf '\033[36m%s\033[0m\n' "$*"; }
else
  red()    { printf '%s\n' "$*"; }
  green()  { printf '%s\n' "$*"; }
  yellow() { printf '%s\n' "$*"; }
  cyan()   { printf '%s\n' "$*"; }
fi

ensure_authkeys() {
  local dir
  dir="$(dirname "$AUTH_KEYS")"
  mkdir -p "$dir"
  # Only tighten dir perms when it's a private .ssh-style dir we own; never
  # touch shared/system dirs like /tmp.
  if [ "$(stat -c '%U' "$dir" 2>/dev/null || echo nobody)" = "$USER" ] \
     && [ "$dir" != "/tmp" ] && [ "$dir" != "/var/tmp" ]; then
    chmod 700 "$dir" 2>/dev/null || true
  fi
  touch "$AUTH_KEYS"
  chmod 600 "$AUTH_KEYS" 2>/dev/null || true
}

# Build the restriction prefix: no shell, no pty, no X11 forwarding,
# permit-listen for the streamlit ports only.
build_options() {
  local opts="no-pty,no-X11-forwarding,no-agent-forwarding,no-user-rc"
  opts="$opts,command=\"echo 'myspace-friend port-forward-only — no shell'; sleep infinity\""
  # Permit-listen rules — friend can only forward to these local ports.
  for p in $DEFAULT_FORWARD_PORTS; do
    opts="$opts,permitlisten=\"localhost:$p\""
  done
  echo "$opts"
}

cmd_add() {
  local name="${1:-}"
  local pubkey_path="${2:-}"
  if [ -z "$name" ] || [ -z "$pubkey_path" ]; then
    red "usage: $0 add <name> <path-to-pubkey>"
    exit 2
  fi
  if [ ! -f "$pubkey_path" ]; then
    red "pubkey not found: $pubkey_path"
    exit 2
  fi
  ensure_authkeys

  # Idempotent — if a friend with this name is already added, drop the old entry first.
  if grep -qE "${TAG_PREFIX}${name}\$" "$AUTH_KEYS"; then
    yellow "Existing entry for '$name' found — replacing."
    cmd_revoke "$name" --quiet
  fi

  local pubkey_body
  pubkey_body="$(awk 'NF' "$pubkey_path" | head -n1)"  # strip blanks, first key only
  if ! printf '%s' "$pubkey_body" | grep -qE '^(ssh-(rsa|ed25519|ecdsa)|ecdsa-sha2-nistp[0-9]+) '; then
    red "doesn't look like an OpenSSH public key (first line): $pubkey_path"
    exit 2
  fi

  local opts
  opts="$(build_options)"
  printf '%s %s %s%s\n' "$opts" "$pubkey_body" "$TAG_PREFIX" "$name" >> "$AUTH_KEYS"
  green "Added port-forward-only key for '$name' to $AUTH_KEYS"
  echo
  cmd_share "$name"
}

cmd_revoke() {
  local name="${1:-}"
  local quiet="${2:-}"
  if [ -z "$name" ]; then
    red "usage: $0 revoke <name>"
    exit 2
  fi
  ensure_authkeys
  if ! grep -qE "${TAG_PREFIX}${name}\$" "$AUTH_KEYS"; then
    [ "$quiet" = "--quiet" ] || yellow "No entry for '$name' — nothing to revoke."
    return 0
  fi
  # Remove every line whose trailing tag matches.
  local tmp
  tmp="$(mktemp)"
  grep -vE "${TAG_PREFIX}${name}\$" "$AUTH_KEYS" > "$tmp" || true
  mv "$tmp" "$AUTH_KEYS"
  chmod 600 "$AUTH_KEYS"
  [ "$quiet" = "--quiet" ] || green "Revoked SSH access for '$name'."
  [ "$quiet" = "--quiet" ] || yellow "Also run: cc -auth-revoke $name   (clears their IP binding too)"
}

cmd_list() {
  ensure_authkeys
  echo "myspace-friend SSH grants in $AUTH_KEYS:"
  grep -E "${TAG_PREFIX}[A-Za-z0-9_.-]+\$" "$AUTH_KEYS" 2>/dev/null \
    | sed -E "s|.*${TAG_PREFIX}||" \
    | sort -u \
    | awk '{print "  - " $0}'
}

cmd_share() {
  local name="${1:-FRIEND}"
  cyan "Share these instructions with $name:"
  echo
  echo "  1. Make sure you've sent me your SSH public key (~/.ssh/id_ed25519.pub)."
  echo "  2. From your terminal:"
  echo
  for p in $DEFAULT_FORWARD_PORTS; do
    echo "       ssh -N -L ${p}:localhost:${p} ${SSH_USER}@${HOST}"
  done
  echo
  echo "  3. With the tunnel running, open in your browser:"
  echo "       Wardrobe:  http://localhost:8510"
  echo "       DAG canvas: http://localhost:8501"
  echo "       YT cutter:  http://localhost:8511"
  echo
  echo "  4. At the login screen, enter your username: $(cyan "$name")"
  echo "     Password: $(cyan "passwd") (or leave blank if you're 'localhost')"
  echo "     Your IP will be bound to your account on first login — connect"
  echo "     from the same network next time."
  echo
}

main() {
  local sub="${1:-help}"
  shift || true
  case "$sub" in
    add)    cmd_add "$@" ;;
    revoke) cmd_revoke "$@" ;;
    list)   cmd_list ;;
    share)  cmd_share "$@" ;;
    help|-h|--help|"")
      cat <<EOF
ssh_friend_setup.sh — onboard a friend's SSH key for port-forward-only access.

Subcommands:
  add <name> <pubkey-path>   Authorize <name>'s pubkey (forward-only)
  revoke <name>              Remove <name>'s key
  list                       Show all current myspace-friend grants
  share <name>               Print the friend-facing SSH+login instructions

Env overrides:
  MYSPACE_SSH_HOST=...           Hostname the friend connects to
  MYSPACE_SSH_USER=...           SSH user on this box (default: \$USER)
  MYSPACE_FORWARD_PORTS=...      Ports to permit-listen on (default: 8510 8501 8511)
  SSH_AUTHORIZED_KEYS=...        Override target file (default: ~/.ssh/authorized_keys)
EOF
      ;;
    *) red "unknown subcommand: $sub"; exit 2 ;;
  esac
}

main "$@"
