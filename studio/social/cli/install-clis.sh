#!/usr/bin/env bash
# install-clis.sh — download standalone CLIs for social/game dev platforms.
# Targets: studio/.bin/  (added to PATH by cc -social-dev)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HERE}/../../.bin"
mkdir -p "$BIN_DIR"

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
say()   { printf '\033[36m▸\033[0m %s\n' "$*"; }

OS="linux"
ARCH="amd64"
if [[ "$(uname -m)" == "aarch64" ]]; then ARCH="arm64"; fi

# ── Livepeer ────────────────────────────────────────────────────────────────
install_livepeer() {
  say "livepeer — checking"
  if [[ -f "$BIN_DIR/livepeer" ]]; then
    green "livepeer already installed"
    return
  fi
  # Download latest release
  LP_URL="https://github.com/livepeer/go-livepeer/releases/download/0.7.4/livepeer-${OS}-${ARCH}.tar.gz"
  TMP=$(mktemp -d)
  curl -sL "$LP_URL" | tar -xz -C "$TMP" --strip-components=1 2>/dev/null || true
  if [[ -f "$TMP/livepeer" ]]; then
    mv "$TMP/livepeer" "$BIN_DIR/"
    chmod +x "$BIN_DIR/livepeer"
    green "livepeer installed → $BIN_DIR/livepeer"
  else
    red "livepeer download failed (may need manual install)"
  fi
  rm -rf "$TMP"
}

# ── Butler (itch.io) ────────────────────────────────────────────────────────
install_butler() {
  say "butler (itch.io) — checking"
  if [[ -f "$BIN_DIR/butler" ]]; then
    green "butler already installed"
    return
  fi
  BUTLER_URL="https://broth.itch.ovh/butler/${OS}-${ARCH}/LATEST/archive/default"
  TMP=$(mktemp -d)
  curl -sL "$BUTLER_URL" | tar -xz -C "$TMP" 2>/dev/null || true
  if [[ -f "$TMP/butler" ]]; then
    mv "$TMP/butler" "$BIN_DIR/"
    chmod +x "$BIN_DIR/butler"
    green "butler installed → $BIN_DIR/butler"
  else
    red "butler download failed (may need manual install)"
  fi
  rm -rf "$TMP"
}

# ── SteamCMD ────────────────────────────────────────────────────────────────
install_steamcmd() {
  say "steamcmd — checking"
  if [[ -f "$BIN_DIR/steamcmd" ]]; then
    green "steamcmd already installed"
    return
  fi
  TMP=$(mktemp -d)
  curl -sL "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" | tar -xz -C "$TMP" 2>/dev/null || true
  if [[ -f "$TMP/steamcmd.sh" ]]; then
    mv "$TMP/"* "$BIN_DIR/"
    ln -sf steamcmd.sh "$BIN_DIR/steamcmd" 2>/dev/null || true
    green "steamcmd installed → $BIN_DIR/steamcmd"
  else
    red "steamcmd download failed (may need manual install)"
  fi
  rm -rf "$TMP"
}

# ── Godot (headless) ────────────────────────────────────────────────────────
install_godot() {
  say "godot — checking"
  if [[ -f "$BIN_DIR/godot" ]]; then
    green "godot already installed"
    return
  fi
  # Check if there's a zip in the project root
  PROJ_ROOT="${HERE}/../../../.."
  ZIPS=("$PROJ_ROOT"/Godot_*_stable_linux*.zip)
  if [[ -f "${ZIPS[0]}" ]]; then
    say "extracting godot from ${ZIPS[0]}"
    unzip -o "${ZIPS[0]}" -d "$BIN_DIR/" >/dev/null 2>&1 || true
    # Find the binary and rename to 'godot'
    for f in "$BIN_DIR"/Godot_*; do
      if [[ -f "$f" && ! -L "$BIN_DIR/godot" ]]; then
        ln -s "$(basename "$f")" "$BIN_DIR/godot" 2>/dev/null || true
        break
      fi
    done
    green "godot installed → $BIN_DIR/godot"
  else
    red "godot zip not found in project root. Download from godotengine.org"
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
case "${1:-all}" in
  all)
    install_livepeer
    install_butler
    install_steamcmd
    install_godot
    ;;
  livepeer)  install_livepeer ;;
  butler)    install_butler ;;
  steamcmd)  install_steamcmd ;;
  godot)     install_godot ;;
  *)
    echo "Usage: install-clis.sh [all|livepeer|butler|steamcmd|godot]"
    exit 2
    ;;
esac

green "Done. Binaries in $BIN_DIR"
echo "Add to PATH: export PATH=\"$BIN_DIR:\$PATH\""
