#!/usr/bin/env bash
# build_gdext.sh — Compile the MySpace++ C++ GDExtension.
# Called from: studio/godot/project/

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../../godot/project" && pwd)"
CPP_DIR="$PROJECT_DIR/cpp"

cd "$CPP_DIR"

if [ ! -d "godot-cpp" ]; then
    echo "Cloning godot-cpp (this is large, ~500 MB)..."
    git clone --depth 1 --branch 4.3-stable https://github.com/godotengine/godot-cpp.git
fi

echo "Building GDExtension..."
scons platform=linux target=template_debug -j$(nproc)
scons platform=linux target=template_release -j$(nproc)

echo "Build complete. Binaries in $PROJECT_DIR/bin/"
ls -la "$PROJECT_DIR/bin/"
