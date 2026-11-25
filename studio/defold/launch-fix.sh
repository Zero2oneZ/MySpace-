#!/usr/bin/env bash
# Defold launcher with fixes

PROJECT="/data/Projects/MySpace++/studio/defold/walkthrough"
DEFOLD="/nix/store/jm5ipci07d0yb6miymcibraqkbwzrhz5-defold/bin/defold"

export __GLX_VENDOR_LIBRARY_NAME=nvidia
export __NV_PRIME_RENDER_OFFLOAD=1

# Remove trailing slash if present
PROJECT="${PROJECT%/}"

echo "Launching Defold with project: $PROJECT"
exec "$DEFOLD" "$PROJECT"
