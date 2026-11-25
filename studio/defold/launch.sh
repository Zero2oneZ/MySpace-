#!/usr/bin/env bash
# Defold launcher for MySpace++ walkthrough project
# Uses steam-run for proper FHS environment without bwrap sandbox issues

PROJECT="/data/Projects/MySpace++/studio/defold/walkthrough/"
DEFOLD_BINARY="/nix/store/ig7qikrbykb7gy5nvsj0gqrv4iq8ljq0-Defold-x86_64-linux/Defold/Defold"

echo "Launching Defold with steam-run..."
echo "Project: $PROJECT"

# steam-run provides the FHS environment that Defold's JavaFX needs
exec steam-run "$DEFOLD_BINARY" "$PROJECT" &
echo "Defold launched. Check your desktop for the editor window."
