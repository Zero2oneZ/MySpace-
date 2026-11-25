#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CPP_DIR="$HERE/cpp"
cd "$CPP_DIR"
if [ ! -d "godot-cpp" ]; then
  echo "Cloning godot-cpp..."
  REPO="https://github.com/godotengine/godot-cpp.git"
  for BR in 4.6 4.5 4.4 4.3 master; do
    if git ls-remote --heads "$REPO" "$BR" | grep -q "$BR"; then
      echo "Trying branch $BR"
      git clone --depth 1 --branch "$BR" "$REPO" && break
    fi
  done
fi
test -d godot-cpp || { echo "no usable godot-cpp branch"; exit 1; }
echo "Building GDExtension..."
scons platform=linux target=template_debug -j$(nproc)
scons platform=linux target=template_release -j$(nproc)
ls -la "$HERE/bin/" 2>/dev/null || true
