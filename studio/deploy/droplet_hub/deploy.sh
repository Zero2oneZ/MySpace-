#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# MySpace++ Droplet Hub — production deploy to DO droplet
# ────────────────────────────────────────────────────────────────────────────
# Ships the complete multi-service architecture:
#   · freetier_callback (:8540)
#   · model_api (:8521)
#   · solana_feed (:8522)
#   · pattern_dashboard (:8767)
#   · mcp_host (:8091)
#   · gpu_gateway (:8523)
#   · ai_orchestrator (:8524)
#   · smart_contract_gen (:8526)
#   · HF sync (cron)
#   · Replit sync (cron)
#
# Run from the laptop (not the droplet). DEFAULTS TO DRY-RUN.
# To actually deploy: DRY_RUN=0 ./deploy.sh
#
# Idempotent — re-running upgrades in place.
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Config ─────────────────────────────────────────────────────────────────
DROPLET_HOST="${DROPLET_HOST:-root@159.89.181.146}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/mspc-public}"
DRY_RUN="${DRY_RUN:-1}"

# Resolve repo root from this script's location (deploy/droplet_hub/ is 3 up)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# SSH key resolution
if [[ -n "${SSH_KEY:-}" ]]; then :
elif [[ -f "$HOME/.ssh/id_ed25519" ]]; then SSH_KEY="$HOME/.ssh/id_ed25519"
elif [[ -f "/home/tom/.ssh/id_ed25519" ]]; then SSH_KEY="/home/tom/.ssh/id_ed25519"
elif [[ -f "$HOME/.ssh/id_rsa" ]]; then SSH_KEY="$HOME/.ssh/id_rsa"
else SSH_KEY="$HOME/.ssh/id_ed25519"; fi

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
say()   { printf '\033[36m> \033[0m%s\n' "$*"; }

# ── Pre-flight checks ─────────────────────────────────────────────────────
say "repo root : $REPO_ROOT"
say "droplet   : $DROPLET_HOST"
say "remote    : $REMOTE_ROOT"
say "ssh key   : $SSH_KEY"
say "DRY_RUN   : $DRY_RUN  (set DRY_RUN=0 to actually deploy)"
echo

# Source paths must exist on the laptop
required_paths=(
    "$REPO_ROOT/studio/endpoints/freetier_callback"
    "$REPO_ROOT/core/lib"
    "$REPO_ROOT/studio/auth"
    "$REPO_ROOT/studio/solana"
    "$REPO_ROOT/studio/assets/_agents/agent_defs"
    "$SCRIPT_DIR/Caddyfile.droplet"
)
for p in "${required_paths[@]}"; do
    if [[ ! -e "$p" ]]; then
        red "MISSING required source: $p"
        exit 1
    fi
done
green "pre-flight: all required source paths present"

# .env must exist on laptop
if [[ ! -f "$REPO_ROOT/.env" ]]; then
    red "MISSING $REPO_ROOT/.env — refusing to deploy without it"
    exit 1
fi
green "pre-flight: .env present"

# Rsync flag based on DRY_RUN
RSYNC_FLAGS="-avz --delete-after"
if [[ "$DRY_RUN" == "1" ]]; then
    RSYNC_FLAGS="$RSYNC_FLAGS --dry-run"
fi
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)

# ── Bootstrap remote ────────────────────────────────────────────────────────
say "bootstrap remote dirs + mspc user + python check"
if [[ "$DRY_RUN" == "0" ]]; then
    ssh "${SSH_OPTS[@]}" "$DROPLET_HOST" bash <<REMOTE
set -e
id mspc >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin mspc

mkdir -p "$REMOTE_ROOT"/{freetier_callback,lib,auth,agent_defs,logs,solana/feed,scripts,games}
chown -R mspc:mspc "$REMOTE_ROOT"
mkdir -p /var/log/mspc
chown mspc:mspc /var/log/mspc

command -v python3 >/dev/null || { echo "ERROR: python3 missing on droplet"; exit 1; }
echo "python3 ok: \$(python3 --version)"
REMOTE
else
    say "  (dry-run) would: create mspc user, mkdir $REMOTE_ROOT/{...}, chown -R"
fi

# ── Sync source trees ──────────────────────────────────────────────────────
set -x

# 1. freetier_callback server + templates
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$REPO_ROOT/studio/endpoints/freetier_callback/" \
    "$DROPLET_HOST:$REMOTE_ROOT/freetier_callback/"

# 2. core/lib (model_api + all helpers)
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    --exclude='__pycache__' --exclude='*.pyc' \
    "$REPO_ROOT/core/lib/" \
    "$DROPLET_HOST:$REMOTE_ROOT/lib/"

# 3. studio/auth (keys.sqlite excluded — host-scoped)
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='keys.sqlite' \
    --exclude='.master_secret' --exclude='freetier_acceptances.sqlite' \
    "$REPO_ROOT/studio/auth/" \
    "$DROPLET_HOST:$REMOTE_ROOT/auth/"

# 4. solana/ (feed + mapper + ML + dashboard + trader)
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='*.log' \
    "$REPO_ROOT/studio/solana/" \
    "$DROPLET_HOST:$REMOTE_ROOT/solana/"

# 5. scripts/ (hf_sync, replit_sync, gpu_gateway, ai_orchestrator, smart_contract_gen, mcp_host)
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$SCRIPT_DIR/scripts/" \
    "$DROPLET_HOST:$REMOTE_ROOT/scripts/"

# 6. agent_defs (read-only audit snapshot)
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$REPO_ROOT/studio/assets/_agents/agent_defs/" \
    "$DROPLET_HOST:$REMOTE_ROOT/agent_defs/"

# 7. .env (mode 600 on droplet)
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    --chmod=F600 \
    "$REPO_ROOT/.env" \
    "$DROPLET_HOST:$REMOTE_ROOT/.env"

# 8. systemd units + Caddyfile
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$SCRIPT_DIR/"*.service \
    "$SCRIPT_DIR/"*.timer \
    "$SCRIPT_DIR/Caddyfile.droplet" \
    "$DROPLET_HOST:$REMOTE_ROOT/"

set +x

# ── Install systemd units + Caddy + start services ─────────────────────────
say "install systemd units, install Caddy fragment, start services"
if [[ "$DRY_RUN" == "0" ]]; then
    ssh "${SSH_OPTS[@]}" "$DROPLET_HOST" bash <<'REMOTE'
set -e
chown -R mspc:mspc /opt/mspc-public
chmod 600 /opt/mspc-public/.env

# Install all systemd units
for unit in \
    mspc-callback.service \
    mspc-model-api.service \
    mspc-solana-feed.service \
    mspc-pattern-dashboard.service \
    mspc-mcp-host.service \
    mspc-gpu-gateway.service \
    mspc-ai-orchestrator.service \
    mspc-smart-contract-gen.service \
    mspc-hf-sync.service \
    mspc-hf-sync.timer \
    mspc-replit-sync.service \
    mspc-replit-sync.timer; do
    install -m 0644 "/opt/mspc-public/$unit" "/etc/systemd/system/$unit"
done

systemctl daemon-reload

# Enable + restart all services
for svc in \
    mspc-callback \
    mspc-model-api \
    mspc-solana-feed \
    mspc-pattern-dashboard \
    mspc-mcp-host \
    mspc-gpu-gateway \
    mspc-ai-orchestrator \
    mspc-smart-contract-gen; do
    systemctl enable $svc.service
    systemctl restart $svc.service || true
done

# Enable timers
systemctl enable mspc-hf-sync.timer
systemctl start mspc-hf-sync.timer
systemctl enable mspc-replit-sync.timer
systemctl start mspc-replit-sync.timer

# Caddy fragment
if command -v caddy >/dev/null; then
    mkdir -p /etc/caddy/Caddyfile.d /var/log/caddy
    install -m 0644 /opt/mspc-public/Caddyfile.droplet /etc/caddy/Caddyfile.d/mspc-droplet-hub
    if ! grep -q "Caddyfile.d" /etc/caddy/Caddyfile 2>/dev/null; then
        echo 'import /etc/caddy/Caddyfile.d/*' >> /etc/caddy/Caddyfile
    fi
    caddy validate --config /etc/caddy/Caddyfile || { echo "caddy validate FAILED"; exit 1; }
    systemctl reload caddy || caddy reload --config /etc/caddy/Caddyfile
    echo "Caddy reloaded"
else
    echo "WARNING: caddy not installed — TLS termination missing"
    echo "         Install with: apt-get install caddy"
fi

# Status summary
echo
echo "── services ──"
for svc in mspc-callback mspc-model-api mspc-solana-feed mspc-pattern-dashboard mspc-mcp-host mspc-gpu-gateway mspc-ai-orchestrator mspc-smart-contract-gen; do
    systemctl --no-pager status $svc.service | head -3 || true
    echo "---"
done
REMOTE
else
    say "  (dry-run) would: install all systemd units + timers"
    say "  (dry-run) would: daemon-reload + enable + restart all services"
    say "  (dry-run) would: install /etc/caddy/Caddyfile.d/mspc-droplet-hub + reload caddy"
fi

# ── Smoke test ──────────────────────────────────────────────────────────────
if [[ "$DRY_RUN" == "0" ]]; then
    say "smoke test (after 5s settle)"
    sleep 5
    ssh "${SSH_OPTS[@]}" "$DROPLET_HOST" bash <<'REMOTE'
echo "── callback (8540) ──"
curl -sf -m 3 http://127.0.0.1:8540/healthz || echo "FAIL: callback"
echo
echo "── model_api (8521) ──"
curl -sf -m 3 http://127.0.0.1:8521/v1/healthz || echo "FAIL: model_api"
echo
echo "── pattern_dashboard (8767) ──"
curl -sf -m 3 http://127.0.0.1:8767/dashboard.html | head -1 || echo "FAIL: dashboard"
echo
echo "── mcp_host (8091) ──"
curl -sf -m 3 http://127.0.0.1:8091/healthz || echo "FAIL: mcp_host"
echo
echo "── ai_orchestrator (8524) ──"
curl -sf -m 3 http://127.0.0.1:8524/healthz || echo "FAIL: ai_orchestrator"
echo
echo "── smart_contract_gen (8526) ──"
curl -sf -m 3 http://127.0.0.1:8526/healthz || echo "FAIL: smart_contract_gen"
echo
echo "── gpu_gateway (8523) ──"
curl -sf -m 3 http://127.0.0.1:8523/healthz || echo "FAIL: gpu_gateway"
REMOTE
    echo
    green "deploy complete. Public surfaces (after DNS + TLS):"
    green "  https://trollz.fun/terms/"
    green "  https://trollz.fun/patterns/       ← Pattern Intelligence Dashboard"
    green "  https://trollz.fun/mcp/            ← MCP Host"
    green "  https://trollz.fun/tools/            ← Free Public Tools"
    green "  https://trollz.fun/generate/         ← Smart Contract + AI Content"
    green "  https://trollz.fun/gpu/              ← GPU Gateway (token-gated)"
    green "  https://GentlyOS.io/patterns/"
    green "  https://GentlyOS.io/mcp/"
    green "  https://GentlyOS.io/tools/"
    green "  https://GentlyOS.io/generate/"
else
    echo
    green "(dry-run by default; set DRY_RUN=0 ./deploy.sh to actually deploy)"
fi
