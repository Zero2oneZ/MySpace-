#!/usr/bin/env bash
# cc + cc-studio bootstrap for Linux / macOS.
#
# What this does:
#   1. Verifies system deps (python3, curl, jq, bash)
#   2. Installs uv (fast Python package manager) if missing
#   3. Creates the cc layout: ~/.cc/ and CC_STUDIO_HOME (~/cc-studio)
#   4. Copies cc + lib files from this checkout into ~/.cc and ~/.local/bin
#   5. Builds the Studio Python venv with streamlit + requests
#   6. Initializes the cc sqlite db
#   7. Detects ollama and prints recommended-model pull commands
#   8. Suggests symlinking cc into /usr/local/bin (requires sudo)
#
# Usage: bash setup.sh                  # default install
#        CC_HOME=$HOME/.cc-alt bash setup.sh  # custom home
#        SKIP_VENV=1 bash setup.sh            # skip Python venv

set -euo pipefail

CC_HOME="${CC_HOME:-$HOME/.cc}"
CC_STUDIO_HOME="${CC_STUDIO_HOME:-$HOME/cc-studio}"
INSTALL_BIN="${INSTALL_BIN:-$HOME/.local/bin}"

say()  { printf '\033[36m==\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m  %s\n' "$*"; }
warn() { printf '\033[33m!!\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m✗\033[0m  %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_ROOT="$SCRIPT_DIR/.."  # assume layout: <repo>/setup/setup.sh + <repo>/cc + <repo>/lib/...

# 1. Deps
say "Checking system dependencies"
for cmd in python3 curl jq bash; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd"
  else
    warn "missing $cmd — install via your package manager (apt/brew/nix etc.) then re-run"
    exit 1
  fi
done

# 2. uv (fast pip)
if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv"
  curl -fsSL https://astral.sh/uv/install.sh | sh
  # uv installs to ~/.local/bin; make sure it's on PATH for this session
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version 2>/dev/null | head -1)"

# 3. Directories
say "Preparing directories"
mkdir -p "$CC_HOME/lib" "$CC_HOME/cache" "$CC_HOME/scripts" "$CC_HOME/setup"
mkdir -p "$CC_STUDIO_HOME/projects" "$CC_STUDIO_HOME/models" \
         "$CC_STUDIO_HOME/datasets" "$CC_STUDIO_HOME/workflows"
mkdir -p "$INSTALL_BIN"
ok "$CC_HOME"
ok "$CC_STUDIO_HOME"

# 4. Install cc binary + libs
say "Installing cc binary + libraries"
if [ -f "$SRC_ROOT/cc" ]; then
  install -m 0755 "$SRC_ROOT/cc" "$INSTALL_BIN/cc"
  ok "$INSTALL_BIN/cc"
else
  warn "source $SRC_ROOT/cc not found — skipping binary install"
fi
for lib in db.py studio.py tui.py; do
  if [ -f "$SRC_ROOT/lib/$lib" ]; then
    install -m 0644 "$SRC_ROOT/lib/$lib" "$CC_HOME/lib/$lib"
    ok "$CC_HOME/lib/$lib"
  fi
done

# 5. Studio venv
if [ "${SKIP_VENV:-0}" = "0" ]; then
  say "Creating Studio Python venv"
  if [ ! -d "$CC_STUDIO_HOME/.venv" ]; then
    (cd "$CC_STUDIO_HOME" && uv venv .venv --python 3.12)
  fi
  uv pip install --python "$CC_STUDIO_HOME/.venv/bin/python" \
      streamlit requests pyyaml huggingface-hub
  ok "venv ready: $CC_STUDIO_HOME/.venv"
else
  warn "SKIP_VENV=1 — skipping Python deps install"
fi

# 6. Initialize db
say "Initializing cc db"
if [ -x "$INSTALL_BIN/cc" ]; then
  PATH="$INSTALL_BIN:$PATH" "$INSTALL_BIN/cc" -help >/dev/null 2>&1 || true
  ok "$CC_HOME/cc.db"
fi

# 7. Ollama hints
if command -v ollama >/dev/null 2>&1; then
  say "Detected ollama — recommended models for cc tiny + claude fallback:"
  cat <<EOF
    ollama pull qwen2.5-coder:1.5b     # tiny, fast, instruct-coder (~1 GB)
    ollama pull llama3.2               # general purpose (~2 GB)
    ollama pull kimi-k2.6:cloud        # large fallback for chat
EOF
else
  warn "ollama not found — install from https://ollama.com if you want local models"
fi

# 8. /usr/local/bin symlink
if [ ! -e /usr/local/bin/cc ]; then
  echo
  warn "Optional: link cc into /usr/local/bin for system-wide use:"
  echo "    sudo ln -s $INSTALL_BIN/cc /usr/local/bin/cc"
fi

# 9. PATH sanity
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$INSTALL_BIN"; then
  echo
  warn "$INSTALL_BIN is not on your PATH. Add to ~/.bashrc or ~/.zshrc:"
  echo "    export PATH=\"$INSTALL_BIN:\$PATH\""
fi

echo
ok "All set."
echo "Launch the dashboard with:  cc studio"
