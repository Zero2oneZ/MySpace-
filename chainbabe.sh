#!/bin/bash
# chainbabe runner script
# Builds and runs chainbabe from source

set -euo pipefail

# Get the project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure core/cc doesn't shadow the C compiler during build
if [ -f "core/cc" ] && [ ! -f "core/cc_backup" ]; then
    mv "core/cc" "core/cc_backup"
fi

# Build chainbabe if needed
if [ ! -f "target/release/chainbabe" ]; then
    echo "Building chainbabe..."
    cargo build --release --manifest-path chainbabe/Cargo.toml
fi

# Restore core/cc if it was renamed
if [ -f "core/cc_backup" ] && [ ! -f "core/cc" ]; then
    mv "core/cc_backup" "core/cc"
fi

# Run chainbabe with all arguments passed through
exec target/release/chainbabe "$@"
