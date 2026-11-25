#!/usr/bin/env bash
# Deploy MySpace++ Unified Bridge to the DO droplet.
# Creates droplet endpoints for social routing + MCP tool access.
#
# Endpoints exposed on droplet:
#   http://droplet:8765/            → root (tool list + health)
#   http://droplet:8765/health       → health check
#   http://droplet:8765/social/upload     → multipart file upload
#   http://droplet:8765/social/batch      → batch file upload
#   http://droplet:8765/social/status     → which platforms have keys
#   http://droplet:8765/social/platforms  → platform key requirements
#   http://droplet:8765/mcp/call     → MCP JSON-RPC 2.0
#   http://droplet:8765/tools        → tool catalog
#   http://droplet:8765/dashboard.html → HTML dashboard
#
# Optional Caddy reverse proxy (port 8766) with CORS + gzip.
# Optional systemd service (alternative to pm2).
#
# Run this from /data/Projects/MySpace++/ or anywhere with the repo checked out.
# Idempotent — re-running upgrades in place.
set -euo pipefail

DROPLET="${DROPLET:-159.89.181.146}"
SSH_USER="${SSH_USER:-root}"
REMOTE_DIR="${REMOTE_DIR:-/opt/myspace-bridge}"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE_PORT="${BRIDGE_PORT:-8765}"

# Key resolution: explicit override → $HOME → tom's key
if [[ -n "${SSH_KEY:-}" ]]; then :
elif [[ -f "$HOME/.ssh/id_ed25519" ]]; then SSH_KEY="$HOME/.ssh/id_ed25519"
elif [[ -f "/home/tom/.ssh/id_ed25519" ]]; then SSH_KEY="/home/tom/.ssh/id_ed25519"
elif [[ -f "$HOME/.ssh/id_rsa" ]]; then SSH_KEY="$HOME/.ssh/id_rsa"
else SSH_KEY="$HOME/.ssh/id_ed25519"; fi

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
say()   { printf '\033[36m▸\033[0m %s\n' "$*"; }

# ── Pre-flight ─────────────────────────────────────────────────────────────
[[ -f "$LOCAL_DIR/server.py" ]]       || { red "missing $LOCAL_DIR/server.py"; exit 1; }
[[ -f "$LOCAL_DIR/requirements.txt" ]] || { red "missing $LOCAL_DIR/requirements.txt"; exit 1; }
[[ -f "$SSH_KEY" ]]                   || { red "no SSH key at $SSH_KEY (override with SSH_KEY=...)"; exit 1; }

SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)

say "checking SSH to $SSH_USER@$DROPLET"
ssh "${SSH_OPTS[@]}" "$SSH_USER@$DROPLET" 'echo ok' >/dev/null 2>&1 \
  || { red "SSH failed. Either: (a) add $SSH_KEY.pub to droplet authorized_keys, or (b) export SSH_KEY=<path>"; exit 1; }
green "SSH ok"

# ── Bootstrap remote Python + deps ─────────────────────────────────────────
say "checking remote python3 + fastapi + uvicorn"
ssh "${SSH_OPTS[@]}" "$SSH_USER@$DROPLET" bash <<'REMOTE'
set -e
mkdir -p /opt/myspace-bridge /opt/myspace-bridge/logs /etc/caddy/Caddyfile.d

# Choose package manager
if   command -v apt-get >/dev/null; then PM='apt-get -y'; UPD='apt-get update -y'
elif command -v yum     >/dev/null; then PM='yum -y';     UPD=':'
elif command -v apk     >/dev/null; then PM='apk add --no-cache'; UPD=':'
else echo "no known package manager"; exit 1; fi

needs=()
command -v python3 >/dev/null || needs+=(python3 python3-pip)
if (( ${#needs[@]} )); then
  $UPD
  $PM install ${needs[@]}
fi

# pip deps
python3 -c "import fastapi" 2>/dev/null || pip3 install fastapi uvicorn
python3 -c "import uvicorn" 2>/dev/null || pip3 install uvicorn
python3 -c "import httpx" 2>/dev/null || pip3 install httpx
python3 -c "import python_multipart" 2>/dev/null || pip3 install python-multipart

echo "remote deps ok: python=$(python3 --version 2>/dev/null) fastapi=$(python3 -c 'import fastapi; print(fastapi.__version__)' 2>/dev/null)"
REMOTE

# ── Ship bridge files ──────────────────────────────────────────────────────
say "scp bridge files → $REMOTE_DIR/"
scp "${SSH_OPTS[@]}" "$LOCAL_DIR/server.py"       "$SSH_USER@$DROPLET:$REMOTE_DIR/server.py"
scp "${SSH_OPTS[@]}" "$LOCAL_DIR/requirements.txt"  "$SSH_USER@$DROPLET:$REMOTE_DIR/requirements.txt"
scp "${SSH_OPTS[@]}" "$LOCAL_DIR/dashboard.html"    "$SSH_USER@$DROPLET:$REMOTE_DIR/dashboard.html"
scp "${SSH_OPTS[@]}" "$LOCAL_DIR/REPLIT.md"         "$SSH_USER@$DROPLET:$REMOTE_DIR/REPLIT.md"
scp "${SSH_OPTS[@]}" "$LOCAL_DIR/myspace-bridge.service" "$SSH_USER@$DROPLET:$REMOTE_DIR/myspace-bridge.service"
scp "${SSH_OPTS[@]}" "$LOCAL_DIR/Caddyfile.droplet" "$SSH_USER@$DROPLET:$REMOTE_DIR/Caddyfile.droplet"

# ── Ship data files (snapshot) ─────────────────────────────────────────────
LOCAL_DATA="/data/Projects/MySpace++"
say "syncing data snapshot → $REMOTE_DIR/data/"
ssh "${SSH_OPTS[@]}" "$SSH_USER@$DROPLET" "mkdir -p $REMOTE_DIR/data/browser-pool $REMOTE_DIR/data/scripts $REMOTE_DIR/data/studio/social $REMOTE_DIR/data/studio/auth"
scp "${SSH_OPTS[@]}" "$LOCAL_DATA/ToDo-JobBoard.md"     "$SSH_USER@$DROPLET:$REMOTE_DIR/data/ToDo-JobBoard.md"
scp "${SSH_OPTS[@]}" "$LOCAL_DATA/ToDo-JobBoard.jsonl"  "$SSH_USER@$DROPLET:$REMOTE_DIR/data/ToDo-JobBoard.jsonl"
scp "${SSH_OPTS[@]}" "$LOCAL_DATA"/MASTER-*.svg         "$SSH_USER@$DROPLET:$REMOTE_DIR/data/"
scp "${SSH_OPTS[@]}" "$LOCAL_DATA/browser-pool"/*.svg   "$SSH_USER@$DROPLET:$REMOTE_DIR/data/browser-pool/"
scp "${SSH_OPTS[@]}" "$LOCAL_DATA/scripts/coherence-check.py" "$SSH_USER@$DROPLET:$REMOTE_DIR/data/scripts/coherence-check.py"
scp "${SSH_OPTS[@]}" "$LOCAL_DATA/scripts/todo-runtime-loop.py" "$SSH_USER@$DROPLET:$REMOTE_DIR/data/scripts/todo-runtime-loop.py"
# Ship social package (needed by social:upload tool)
scp -r "${SSH_OPTS[@]}" "$LOCAL_DATA/studio/social/"*     "$SSH_USER@$DROPLET:$REMOTE_DIR/data/studio/social/"
scp "${SSH_OPTS[@]}" "$LOCAL_DATA/studio/paths.py"       "$SSH_USER@$DROPLET:$REMOTE_DIR/data/studio/paths.py"
scp "${SSH_OPTS[@]}" "$LOCAL_DATA/studio/bootstrap.py"   "$SSH_USER@$DROPLET:$REMOTE_DIR/data/studio/bootstrap.py"

# ── Start with pm2 (default) ──────────────────────────────────────────────
say "starting bridge via pm2 on port $BRIDGE_PORT"
ssh "${SSH_OPTS[@]}" "$SSH_USER@$DROPLET" bash <<REMOTE
set -e
cd "$REMOTE_DIR"

# Ensure CC_PROJECT_ROOT is set in the environment for the bridge
export CC_PROJECT_ROOT=/opt/myspace-bridge/data
mkdir -p \$CC_PROJECT_ROOT/browser-pool

# pm2: restart-or-start
pm2 describe myspace-bridge >/dev/null 2>&1 \
  && pm2 reload myspace-bridge \
  || pm2 start server.py --name myspace-bridge --interpreter python3 --time \
       --log "$REMOTE_DIR/logs/bridge.log" \
       -- --replit --port $BRIDGE_PORT

pm2 save
pm2 startup systemd -u root --hp /root 2>/dev/null | tail -1 | sh - || true

echo "pm2 status:"
pm2 jlist | grep -E 'name|pm_id|status' | head -10 || pm2 ls
REMOTE

# ── Install systemd service (optional) ───────────────────────────────────────
say "installing systemd service (optional, does not conflict with pm2)"
ssh "${SSH_OPTS[@]}" "$SSH_USER@$DROPLET" bash <<REMOTE
set -e
cp /opt/myspace-bridge/myspace-bridge.service /etc/systemd/system/myspace-bridge.service
systemctl daemon-reload
systemctl enable myspace-bridge.service || true
# Do not start systemd service if pm2 is already running — avoid port conflict.
if ! pm2 describe myspace-bridge >/dev/null 2>&1; then
  systemctl start myspace-bridge.service || true
  echo "systemd service started (pm2 was not running)"
else
  echo "pm2 is running — systemd service installed but not started (port $BRIDGE_PORT conflict avoided)"
fi
REMOTE

# ── Install Caddy reverse proxy (optional) ─────────────────────────────────
say "installing Caddy reverse proxy config (port 8766 → 8765)"
ssh "${SSH_OPTS[@]}" "$SSH_USER@$DROPLET" bash <<REMOTE
set -e
if command -v caddy >/dev/null; then
  cp /opt/myspace-bridge/Caddyfile.droplet /etc/caddy/Caddyfile.d/myspace-bridge
  # Ensure the main Caddyfile imports this directory
  if ! grep -q "Caddyfile.d" /etc/caddy/Caddyfile 2>/dev/null; then
    echo 'import /etc/caddy/Caddyfile.d/*' >> /etc/caddy/Caddyfile
  fi
  caddy reload --config /etc/caddy/Caddyfile 2>/dev/null || systemctl reload caddy 2>/dev/null || true
  echo "Caddy reloaded. Bridge reachable at http://$DROPLET:8766/ with gzip + CORS"
else
  echo "Caddy not installed — skipping reverse proxy. Bridge is direct on port 8765."
fi
REMOTE

# ── Smoke test ─────────────────────────────────────────────────────────────
say "smoke test → http://$DROPLET:$BRIDGE_PORT/health"
HEALTH=$(curl -sf -m 5 "http://$DROPLET:$BRIDGE_PORT/health" 2>/dev/null || echo '{"status":"fail"}')
if echo "$HEALTH" | grep -q '"status": "ok"'; then
  green "deploy ok — health check passed"
  green "Droplet endpoints:"
  green "  http://$DROPLET:$BRIDGE_PORT/health"
  green "  http://$DROPLET:$BRIDGE_PORT/social/upload"
  green "  http://$DROPLET:$BRIDGE_PORT/social/batch"
  green "  http://$DROPLET:$BRIDGE_PORT/social/status"
  green "  http://$DROPLET:$BRIDGE_PORT/social/platforms"
  green "  http://$DROPLET:$BRIDGE_PORT/mcp/call"
  green "  http://$DROPLET:$BRIDGE_PORT/tools"
  green "  http://$DROPLET:$BRIDGE_PORT/dashboard.html"
else
  red "health check failed. Checking root endpoint..."
  if curl -sf -m 5 "http://$DROPLET:$BRIDGE_PORT/" >/dev/null; then
    green "root is reachable but /health returned unexpected response"
  else
    red "deploy reported success but endpoint is unreachable."
    red "Check droplet firewall: port $BRIDGE_PORT must be open (ufw / DO cloud firewall)."
    red "Quick fix on droplet: ufw allow $BRIDGE_PORT/tcp"
    exit 2
  fi
fi
