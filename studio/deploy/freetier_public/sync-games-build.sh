#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# sync-games-build.sh — push a freshly-exported Godot Web Instant Games
# build to the DO droplet for static serving at
#   https://trollz.fun/play/<game_slug>/
#   https://GentlyOS.io/play/<game_slug>/
# ────────────────────────────────────────────────────────────────────────────
# Usage:
#   ./sync-games-build.sh [game_slug] [local_build_dir]
#
# Defaults:
#   game_slug       = myspace_pp
#   local_build_dir = /data/Projects/MySpace++/studio/godot/builds/web_instant_games
#
# DRY_RUN defaults to 1. Set DRY_RUN=0 to actually push.
#
# Pre-flight: verifies build dir exists, contains index.html, rsync is
# installed locally, and the droplet is reachable via SSH (BatchMode). Then
# rsyncs the build to /opt/mspc-public/games/<game_slug>/ owned by mspc:mspc
# with sane permissions. Caddy already serves /play/* via Caddyfile.droplet.
#
# This script is SEPARATE from deploy.sh — it does not modify any systemd
# units, the Caddyfile, or the freetier services. It only ships static files.
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Args + defaults ────────────────────────────────────────────────────────
GAME_SLUG="${1:-myspace_pp}"
BUILD_DIR="${2:-/data/Projects/MySpace++/studio/godot/builds/web_instant_games}"
DROPLET_HOST="${DROPLET_HOST:-root@159.89.181.146}"
REMOTE_GAMES_ROOT="${REMOTE_GAMES_ROOT:-/opt/mspc-public/games}"
REMOTE_DIR="$REMOTE_GAMES_ROOT/$GAME_SLUG"
DRY_RUN="${DRY_RUN:-1}"

# SSH key resolution (same precedence as deploy.sh)
if [[ -n "${SSH_KEY:-}" ]]; then :
elif [[ -f "$HOME/.ssh/id_ed25519" ]]; then SSH_KEY="$HOME/.ssh/id_ed25519"
elif [[ -f "/home/tom/.ssh/id_ed25519" ]]; then SSH_KEY="/home/tom/.ssh/id_ed25519"
elif [[ -f "$HOME/.ssh/id_rsa" ]]; then SSH_KEY="$HOME/.ssh/id_rsa"
else SSH_KEY="$HOME/.ssh/id_ed25519"; fi

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
say()   { printf '\033[36m> \033[0m%s\n' "$*"; }

say "game slug   : $GAME_SLUG"
say "build dir   : $BUILD_DIR"
say "droplet     : $DROPLET_HOST"
say "remote dir  : $REMOTE_DIR"
say "ssh key     : $SSH_KEY"
say "DRY_RUN     : $DRY_RUN  (set DRY_RUN=0 to actually push)"
echo

# ── Pre-flight: validate game slug (used as path component on droplet) ────
if [[ ! "$GAME_SLUG" =~ ^[a-z0-9_-]+$ ]]; then
    red "FAIL: game_slug '$GAME_SLUG' must match ^[a-z0-9_-]+\$"
    red "      (lowercase letters, digits, underscore, dash only — no '..' or '/')"
    exit 1
fi
green "pre-flight: game_slug shape ok"

# ── Pre-flight: local build dir exists and has an index.html ──────────────
if [[ ! -d "$BUILD_DIR" ]]; then
    red "FAIL: build dir does not exist: $BUILD_DIR"
    red "      Run 'cc godot-export web_instant_games' first to produce it."
    exit 1
fi
green "pre-flight: build dir present"

if [[ ! -f "$BUILD_DIR/index.html" ]]; then
    red "FAIL: $BUILD_DIR/index.html missing"
    red "      A valid Godot HTML5 export must contain index.html at its root."
    exit 1
fi
green "pre-flight: index.html present"

# Spot-check for the typical Godot 4 web export artefacts. Warn (don't fail)
# if any are missing — exact filenames depend on the export preset name.
have_pck=0
have_wasm=0
shopt -s nullglob
for f in "$BUILD_DIR"/*.pck;  do have_pck=1;  break; done
for f in "$BUILD_DIR"/*.wasm; do have_wasm=1; break; done
shopt -u nullglob
if [[ "$have_pck" == "0" ]]; then
    say "warn: no *.pck in build dir (unusual for Godot 4 web export)"
fi
if [[ "$have_wasm" == "0" ]]; then
    say "warn: no *.wasm in build dir (unusual for Godot 4 web export)"
fi

# ── Pre-flight: rsync available locally ────────────────────────────────────
if ! command -v rsync >/dev/null 2>&1; then
    red "FAIL: rsync not installed locally — apt-get install rsync"
    exit 1
fi
green "pre-flight: rsync available"

# ── Pre-flight: droplet reachable via SSH (BatchMode, no password) ────────
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
say "ssh probe: $DROPLET_HOST"
if ssh "${SSH_OPTS[@]}" "$DROPLET_HOST" 'true' 2>/dev/null; then
    green "pre-flight: droplet reachable"
else
    red "FAIL: cannot SSH to $DROPLET_HOST with key $SSH_KEY"
    red "      Confirm the droplet is up, key is authorized, and SSH_KEY is correct."
    exit 1
fi

# ── Bootstrap remote dir + ownership (always idempotent) ──────────────────
say "ensure remote tree exists: $REMOTE_DIR"
if [[ "$DRY_RUN" == "0" ]]; then
    ssh "${SSH_OPTS[@]}" "$DROPLET_HOST" bash <<REMOTE
set -e
mkdir -p "$REMOTE_DIR"
# mspc user is created by deploy.sh; fall back to root:root if absent
if id mspc >/dev/null 2>&1; then
    chown -R mspc:mspc "$REMOTE_GAMES_ROOT"
fi
REMOTE
else
    say "  (dry-run) would: mkdir -p $REMOTE_DIR && chown -R mspc:mspc $REMOTE_GAMES_ROOT"
fi

# ── Sync the build ─────────────────────────────────────────────────────────
RSYNC_FLAGS="-avz --delete-after --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r"
if [[ "$DRY_RUN" == "1" ]]; then
    RSYNC_FLAGS="$RSYNC_FLAGS --dry-run"
fi

say "rsync $BUILD_DIR/ -> $DROPLET_HOST:$REMOTE_DIR/"
# Trailing slash on $BUILD_DIR/ is intentional: copy CONTENTS into REMOTE_DIR
rsync $RSYNC_FLAGS \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new" \
    --exclude='.DS_Store' --exclude='Thumbs.db' --exclude='*.swp' \
    "$BUILD_DIR/" \
    "$DROPLET_HOST:$REMOTE_DIR/"

# ── Fix ownership after rsync (only on real push) ─────────────────────────
if [[ "$DRY_RUN" == "0" ]]; then
    say "post-rsync chown/chmod sweep"
    ssh "${SSH_OPTS[@]}" "$DROPLET_HOST" bash <<REMOTE
set -e
if id mspc >/dev/null 2>&1; then
    chown -R mspc:mspc "$REMOTE_DIR"
fi
find "$REMOTE_DIR" -type d -exec chmod 755 {} \;
find "$REMOTE_DIR" -type f -exec chmod 644 {} \;
REMOTE
    echo
    green "sync complete. Game URLs (after Caddy reload — should already be live):"
    green "  https://trollz.fun/play/$GAME_SLUG/"
    green "  https://GentlyOS.io/play/$GAME_SLUG/"
    echo
    say "manual rollback if the new build is broken:"
    say "  ssh $DROPLET_HOST 'mv $REMOTE_DIR $REMOTE_DIR.broken'"
else
    echo
    green "(dry-run by default; set DRY_RUN=0 bash sync-games-build.sh $GAME_SLUG to actually push)"
fi
