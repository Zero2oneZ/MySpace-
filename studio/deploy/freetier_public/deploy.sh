#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# MySpace++ freetier public — production deploy to DO droplet
# ────────────────────────────────────────────────────────────────────────────
# Ships two stdlib Python servers (freetier_callback :8540, model_api :8521),
# their shared lib/, the auth substrate, the agent_defs (read-only audit
# snapshot), the systemd units, and the Caddyfile fragment.
#
# Run from the laptop (not the droplet). DEFAULTS TO DRY-RUN. To actually
# deploy: DRY_RUN=0 ./deploy.sh
#
# Idempotent — re-running upgrades in place.
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Config ─────────────────────────────────────────────────────────────────
DROPLET_HOST="${DROPLET_HOST:-root@159.89.181.146}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/mspc-public}"
DRY_RUN="${DRY_RUN:-1}"

# Resolve repo root from this script's location (deploy/freetier_public/ is 3 up)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# SSH key resolution: explicit override → $HOME → tom's path
if [[ -n "${SSH_KEY:-}" ]]; then :
elif [[ -f "$HOME/.ssh/id_ed25519" ]]; then SSH_KEY="$HOME/.ssh/id_ed25519"
elif [[ -f "/home/tom/.ssh/id_ed25519" ]]; then SSH_KEY="/home/tom/.ssh/id_ed25519"
elif [[ -f "$HOME/.ssh/id_rsa" ]]; then SSH_KEY="$HOME/.ssh/id_rsa"
else SSH_KEY="$HOME/.ssh/id_ed25519"; fi

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
say()   { printf '\033[36m> \033[0m%s\n' "$*"; }

# ── Pre-flight checks (always run, including in dry-run) ───────────────────
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
    "$REPO_ROOT/studio/assets/_agents/agent_defs"
    "$SCRIPT_DIR/Caddyfile.droplet"
    "$SCRIPT_DIR/mspc-callback.service"
    "$SCRIPT_DIR/mspc-model-api.service"
)
for p in "${required_paths[@]}"; do
    if [[ ! -e "$p" ]]; then
        red "MISSING required source: $p"
        exit 1
    fi
done
green "pre-flight: all required source paths present"

# .env must exist on laptop (will be shipped to droplet)
if [[ ! -f "$REPO_ROOT/.env" ]]; then
    red "MISSING $REPO_ROOT/.env — refusing to deploy without it"
    red "The systemd units require an EnvironmentFile at /opt/mspc-public/.env"
    exit 1
fi
green "pre-flight: .env present"

# Rsync flag based on DRY_RUN
RSYNC_FLAGS="-avz --delete-after"
if [[ "$DRY_RUN" == "1" ]]; then
    RSYNC_FLAGS="$RSYNC_FLAGS --dry-run"
fi
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)

# ── Bootstrap remote (mkdir + user + python deps) ──────────────────────────
say "bootstrap remote dirs + mspc user + python check"
if [[ "$DRY_RUN" == "0" ]]; then
    ssh "${SSH_OPTS[@]}" "$DROPLET_HOST" bash <<REMOTE
set -e
# Create dedicated unprivileged user (idempotent)
id mspc >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin mspc

mkdir -p "$REMOTE_ROOT"/{freetier_callback,lib,auth,agent_defs,logs}
chown -R mspc:mspc "$REMOTE_ROOT"

# Sanity: python3 must exist
command -v python3 >/dev/null || { echo "ERROR: python3 missing on droplet"; exit 1; }
echo "python3 ok: \$(python3 --version)"
REMOTE
else
    say "  (dry-run) would: create mspc user, mkdir $REMOTE_ROOT/{freetier_callback,lib,auth,agent_defs,logs}, chown -R"
fi

# ── Sync source trees ──────────────────────────────────────────────────────
set -x

# 1. freetier_callback server + templates
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$REPO_ROOT/studio/endpoints/freetier_callback/" \
    "$DROPLET_HOST:$REMOTE_ROOT/freetier_callback/"

# 2. core/lib (model_api lives here; ship the whole lib so its imports resolve)
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    --exclude='__pycache__' --exclude='*.pyc' \
    "$REPO_ROOT/core/lib/" \
    "$DROPLET_HOST:$REMOTE_ROOT/lib/"

# 3. studio/auth (keys.sqlite + gate.py + keys.py)
#    NOTE: keys.sqlite is host-scoped per the salted-token registry rule.
#    Excluding it means the droplet will create a fresh DB on first run.
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='keys.sqlite' \
    --exclude='.master_secret' --exclude='freetier_acceptances.sqlite' \
    "$REPO_ROOT/studio/auth/" \
    "$DROPLET_HOST:$REMOTE_ROOT/auth/"

# 4. agent_defs (read-only audit snapshot — no runtime use)
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$REPO_ROOT/studio/assets/_agents/agent_defs/" \
    "$DROPLET_HOST:$REMOTE_ROOT/agent_defs/"

# 5. .env (mode 600 on droplet)
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    --chmod=F600 \
    "$REPO_ROOT/.env" \
    "$DROPLET_HOST:$REMOTE_ROOT/.env"

# 6. systemd units + Caddyfile
rsync $RSYNC_FLAGS -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$SCRIPT_DIR/mspc-callback.service" \
    "$SCRIPT_DIR/mspc-model-api.service" \
    "$SCRIPT_DIR/Caddyfile.droplet" \
    "$DROPLET_HOST:$REMOTE_ROOT/"

set +x

# ── Install systemd units + Caddy fragment + start services ────────────────
say "install systemd units, install Caddy fragment, start services"
if [[ "$DRY_RUN" == "0" ]]; then
    ssh "${SSH_OPTS[@]}" "$DROPLET_HOST" bash <<REMOTE
set -e
# Ownership + .env perms
chown -R mspc:mspc "$REMOTE_ROOT"
chmod 600 "$REMOTE_ROOT/.env"

# systemd units
install -m 0644 "$REMOTE_ROOT/mspc-callback.service"  /etc/systemd/system/mspc-callback.service
install -m 0644 "$REMOTE_ROOT/mspc-model-api.service" /etc/systemd/system/mspc-model-api.service
systemctl daemon-reload
systemctl enable mspc-callback.service mspc-model-api.service
systemctl restart mspc-callback.service
systemctl restart mspc-model-api.service

# Caddy fragment
if command -v caddy >/dev/null; then
    mkdir -p /etc/caddy/Caddyfile.d /var/log/caddy
    install -m 0644 "$REMOTE_ROOT/Caddyfile.droplet" /etc/caddy/Caddyfile.d/mspc-freetier-public
    if ! grep -q "Caddyfile.d" /etc/caddy/Caddyfile 2>/dev/null; then
        echo 'import /etc/caddy/Caddyfile.d/*' >> /etc/caddy/Caddyfile
    fi
    caddy validate --config /etc/caddy/Caddyfile || { echo "caddy validate FAILED"; exit 1; }
    systemctl reload caddy || caddy reload --config /etc/caddy/Caddyfile
    echo "Caddy reloaded"
else
    echo "WARNING: caddy not installed on droplet — TLS termination missing"
    echo "         Install with: apt-get install caddy"
fi

# Status summary
echo
echo "── services ──"
systemctl --no-pager status mspc-callback.service  | head -5
systemctl --no-pager status mspc-model-api.service | head -5
REMOTE
else
    say "  (dry-run) would: install /etc/systemd/system/mspc-{callback,model-api}.service"
    say "  (dry-run) would: install /etc/caddy/Caddyfile.d/mspc-freetier-public"
    say "  (dry-run) would: daemon-reload + enable + restart both units + caddy reload"
fi

# ── Smoke test (only when actually deployed) ───────────────────────────────
if [[ "$DRY_RUN" == "0" ]]; then
    say "smoke test (after 3s settle)"
    sleep 3
    say "  curl http://127.0.0.1 via ssh tunnel (skipping public TLS check — needs DNS)"
    ssh "${SSH_OPTS[@]}" "$DROPLET_HOST" bash <<'REMOTE'
echo "── callback (8540) ──"
curl -sf -m 3 http://127.0.0.1:8540/healthz || echo "FAIL: callback not responding on 127.0.0.1:8540"
echo
echo "── model_api (8521) ──"
curl -sf -m 3 http://127.0.0.1:8521/v1/healthz || echo "FAIL: model_api not responding on 127.0.0.1:8521"
REMOTE
    echo
    green "deploy complete. Public surfaces (after DNS + TLS):"
    green "  https://trollz.fun/terms/"
    green "  https://trollz.fun/v1/text/generate"
    green "  https://GentlyOS.io/endpoint/freetier/terms/"
    green "  https://GentlyOS.io/v1/text/generate"
else
    echo
    green "(dry-run by default; set DRY_RUN=0 ./deploy.sh to actually deploy)"
fi
