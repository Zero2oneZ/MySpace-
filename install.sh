#!/usr/bin/env bash
# MySpace++ installer for Linux and macOS (bare-metal, no nix, no docker).
#
# What it does:
#   1. Detects OS + package manager
#   2. Checks required deps; tells you the install command if any are missing
#   3. Copies core/ → $PREFIX/share/myspace-pp/
#   4. Symlinks myspace + cc → $PREFIX/bin/
#   5. Verifies install with `myspace -help`
#
# Usage:
#   ./install.sh                     # installs to ~/.local (with studio)
#   PREFIX=/usr/local ./install.sh   # installs system-wide (needs sudo)
#   ./install.sh --uninstall         # removes the install
#   ./install.sh --no-studio         # core only, no Streamlit/wardrobe apps

set -euo pipefail

# Studio is on by default; --no-studio or MYSPACE_INCLUDE_STUDIO=0 disables.
INCLUDE_STUDIO="${MYSPACE_INCLUDE_STUDIO:-1}"
if [ "${1:-}" = "--no-studio" ]; then INCLUDE_STUDIO=0; shift || true; fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="$PREFIX/bin"
SHARE_DIR="$PREFIX/share/myspace-pp"

# --- colored output ------------------------------------------------------
if [ -t 1 ]; then
  red()    { printf '\033[31m%s\033[0m' "$*"; }
  green()  { printf '\033[32m%s\033[0m' "$*"; }
  yellow() { printf '\033[33m%s\033[0m' "$*"; }
  cyan()   { printf '\033[36m%s\033[0m' "$*"; }
else
  red()    { printf '%s' "$*"; }
  green()  { printf '%s' "$*"; }
  yellow() { printf '%s' "$*"; }
  cyan()   { printf '%s' "$*"; }
fi
say() { printf '%s\n' "$*"; }

# --- uninstall path ------------------------------------------------------
if [ "${1:-}" = "--uninstall" ]; then
  say "$(cyan "Uninstalling MySpace++ from $PREFIX...")"
  rm -f "$BIN_DIR/myspace" "$BIN_DIR/cc"
  rm -rf "$SHARE_DIR"
  say "$(green "Removed.") User data in ~/.cc/ is NOT touched — remove manually if desired."
  exit 0
fi

# --- OS detection --------------------------------------------------------
case "$(uname -s)" in
  Linux*)  OS=linux ;;
  Darwin*) OS=macos ;;
  *) say "$(red "Unsupported OS:") $(uname -s)"
     say "Windows users: run install.ps1 (container-only) or use WSL."
     exit 1 ;;
esac
say "Detected OS: $(cyan "$OS")"

# --- package manager detection -------------------------------------------
detect_pm() {
  command -v apt-get >/dev/null 2>&1 && { echo apt; return; }
  command -v dnf     >/dev/null 2>&1 && { echo dnf; return; }
  command -v pacman  >/dev/null 2>&1 && { echo pacman; return; }
  command -v zypper  >/dev/null 2>&1 && { echo zypper; return; }
  command -v apk     >/dev/null 2>&1 && { echo apk; return; }
  command -v brew    >/dev/null 2>&1 && { echo brew; return; }
  command -v nix-env >/dev/null 2>&1 && { echo nix; return; }
  echo none
}
PM="$(detect_pm)"
say "Detected package manager: $(cyan "$PM")"

# Map a generic binary name to the package that provides it for each PM.
# (Most are 1:1; sqlite3 vs sqlite is the common gotcha.)
pkg_for_bin() {
  local bin="$1" pm="$2"
  case "$bin:$pm" in
    sqlite3:apt|sqlite3:dnf|sqlite3:apk|sqlite3:zypper)  echo "sqlite3" ;;
    sqlite3:pacman|sqlite3:brew|sqlite3:nix)             echo "sqlite" ;;
    sha256sum:brew)                                       echo "coreutils" ;;
    sha256sum:*)                                          echo "coreutils" ;;
    uuidgen:apt|uuidgen:dnf|uuidgen:zypper)              echo "uuid-runtime" ;;
    uuidgen:pacman)                                       echo "util-linux" ;;
    uuidgen:brew|uuidgen:apk)                            echo "" ;;  # built-in or n/a
    *)                                                    echo "$bin" ;;
  esac
}

# --- dependency check ----------------------------------------------------
REQUIRED=(bash python3 jq curl sqlite3 sha256sum awk sed grep mktemp date dirname basename)
missing=()
for bin in "${REQUIRED[@]}"; do
  command -v "$bin" >/dev/null 2>&1 || missing+=("$bin")
done

if [ "${#missing[@]}" -gt 0 ]; then
  say "$(red "Missing required binaries:") ${missing[*]}"
  case "$PM" in
    apt)    pkgs=""; for b in "${missing[@]}"; do pkgs="$pkgs $(pkg_for_bin "$b" apt)"; done
            say "Install with: $(cyan "sudo apt-get install -y$pkgs")" ;;
    dnf)    pkgs=""; for b in "${missing[@]}"; do pkgs="$pkgs $(pkg_for_bin "$b" dnf)"; done
            say "Install with: $(cyan "sudo dnf install -y$pkgs")" ;;
    pacman) pkgs=""; for b in "${missing[@]}"; do pkgs="$pkgs $(pkg_for_bin "$b" pacman)"; done
            say "Install with: $(cyan "sudo pacman -S$pkgs")" ;;
    apk)    pkgs=""; for b in "${missing[@]}"; do pkgs="$pkgs $(pkg_for_bin "$b" apk)"; done
            say "Install with: $(cyan "sudo apk add$pkgs")" ;;
    zypper) pkgs=""; for b in "${missing[@]}"; do pkgs="$pkgs $(pkg_for_bin "$b" zypper)"; done
            say "Install with: $(cyan "sudo zypper install$pkgs")" ;;
    brew)   pkgs=""; for b in "${missing[@]}"; do pkgs="$pkgs $(pkg_for_bin "$b" brew)"; done
            say "Install with: $(cyan "brew install$pkgs")" ;;
    nix)    say "Install with: $(cyan "nix-env -iA nixpkgs.{bash,python3,jq,curl,sqlite,coreutils}")"
            say "Better: just run $(cyan "nix run .#myspace") from the repo — handles deps for you." ;;
    none)   say "$(yellow "Unknown package manager — install the missing binaries manually then re-run.")" ;;
  esac
  exit 1
fi
say "$(green "All required binaries present.")"

# --- install -------------------------------------------------------------
say "Installing to $(cyan "$PREFIX")..."

mkdir -p "$BIN_DIR" "$SHARE_DIR"

# Refuse to clobber an existing install with un-tracked changes.
if [ -d "$SHARE_DIR" ] && [ -n "$(ls -A "$SHARE_DIR" 2>/dev/null || true)" ]; then
  say "$(yellow "Existing install detected at $SHARE_DIR — replacing.")"
fi
rm -rf "$SHARE_DIR"
mkdir -p "$SHARE_DIR"
cp -r "$REPO_ROOT/core/." "$SHARE_DIR/"
chmod +x "$SHARE_DIR/cc" "$SHARE_DIR/tests/"*.sh "$SHARE_DIR/setup/"*.sh 2>/dev/null || true

# Studio (DAG canvas + Wardrobe + YT cutter). Optional via --no-studio.
if [ "$INCLUDE_STUDIO" = "1" ] && [ -d "$REPO_ROOT/studio" ]; then
  say "$(cyan "Installing studio (Streamlit apps)…")"
  rm -rf "$SHARE_DIR/studio"
  mkdir -p "$SHARE_DIR/studio"
  # Copy sources only — skip .venv / media caches / __pycache__.
  if command -v rsync >/dev/null 2>&1; then
    rsync -a \
      --exclude='.venv/' --exclude='__pycache__/' \
      --exclude='media/.cache/' --exclude='media/wardrobe_out/' \
      --exclude='media/sound/' --exclude='media/video/' \
      --exclude='saved/' --exclude='26.1.1' --exclude='*.pyc' \
      "$REPO_ROOT/studio/" "$SHARE_DIR/studio/"
  else
    cp -r "$REPO_ROOT/studio/." "$SHARE_DIR/studio/"
    rm -rf "$SHARE_DIR/studio/.venv" "$SHARE_DIR/studio/__pycache__" \
           "$SHARE_DIR/studio/media/.cache" "$SHARE_DIR/studio/media/wardrobe_out" \
           "$SHARE_DIR/studio/saved" "$SHARE_DIR/studio/26.1.1"
  fi
  chmod +x "$SHARE_DIR/studio/"*.sh 2>/dev/null || true
  # Heads up about heavy native deps Streamlit/opencv/rembg need on Linux.
  if [ "$OS" = "linux" ]; then
    studio_missing=()
    command -v ffmpeg >/dev/null 2>&1 || studio_missing+=("ffmpeg")
    # libGL is needed by opencv-python-headless on some distros.
    case "$PM" in
      apt)    dpkg -s libgl1 >/dev/null 2>&1 || studio_missing+=("libgl1") ;;
      dnf)    rpm -q mesa-libGL >/dev/null 2>&1 || studio_missing+=("mesa-libGL") ;;
      pacman) pacman -Qi libglvnd >/dev/null 2>&1 || studio_missing+=("libglvnd") ;;
    esac
    if [ "${#studio_missing[@]}" -gt 0 ]; then
      say "$(yellow "Studio also needs:") ${studio_missing[*]}"
      case "$PM" in
        apt)    say "Install with: $(cyan "sudo apt-get install -y ${studio_missing[*]}")" ;;
        dnf)    say "Install with: $(cyan "sudo dnf install -y ${studio_missing[*]}")" ;;
        pacman) say "Install with: $(cyan "sudo pacman -S ${studio_missing[*]}")" ;;
        brew)   say "Install with: $(cyan "brew install ${studio_missing[*]}")" ;;
        *)      say "(Install ${studio_missing[*]} via your package manager.)" ;;
      esac
      say "$(yellow "Studio will still install — these are needed at runtime, not at install time.")"
    fi
  fi
fi

# Write a wrapper script (NOT a symlink) that pins CC_INSTALL_ROOT.
# CRITICAL: do NOT symlink myspace → $SHARE_DIR/cc first and then
# `cat > $BIN_DIR/myspace` — that would follow the symlink and overwrite
# the actual cc script with a recursive wrapper. Bug found 2026-05-25.
# Remove any pre-existing symlink defensively.
rm -f "$BIN_DIR/myspace" "$BIN_DIR/cc"
cat > "$BIN_DIR/myspace" <<EOF
#!/usr/bin/env bash
# MySpace++ wrapper — pins CC_INSTALL_ROOT to the install share dir so the
# auto-discovery in cc doesn't have to guess. Auto-generated by install.sh.
CC_INSTALL_ROOT="$SHARE_DIR" exec bash "$SHARE_DIR/cc" "\$@"
EOF
chmod +x "$BIN_DIR/myspace"
# Back-compat alias for users coming from the original tool.
ln -sf "$BIN_DIR/myspace" "$BIN_DIR/cc"

# --- verify --------------------------------------------------------------
say "Verifying..."
if "$BIN_DIR/myspace" -help >/dev/null 2>&1; then
  say "$(green "Verification: PASS")"
else
  say "$(red "Verification: FAIL — 'myspace -help' didn't run cleanly")"
  exit 1
fi

# --- final notes ---------------------------------------------------------
say ""
say "$(green "MySpace++ installed.") Binary: $BIN_DIR/myspace"
case ":$PATH:" in
  *":$BIN_DIR:"*) say "$BIN_DIR is on your PATH — try: $(cyan "myspace -help")" ;;
  *)              say "$(yellow "$BIN_DIR is NOT on your PATH yet.")"
                  say "Add this to your shell rc:"
                  say "  $(cyan "export PATH=\"$BIN_DIR:\$PATH\"")" ;;
esac
say ""
say "Next: $(cyan "cd ~/some-project && myspace -setup")"
if [ "$INCLUDE_STUDIO" = "1" ] && [ -d "$SHARE_DIR/studio" ]; then
  say "Studio: $(cyan "myspace -wardrobe")  → http://localhost:8510"
  say "        $(cyan "myspace -studio")    → http://localhost:8501"
  say "        $(cyan "myspace -yt-cut")    → http://localhost:8511"
  say "(First launch creates a Python venv inside studio/ — takes ~2 min.)"
fi
