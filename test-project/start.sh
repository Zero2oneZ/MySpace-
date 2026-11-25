#!/bin/bash
# Start the Gradio-like HTMX server

echo "=== Generative Environment Startup ==="
echo "Project: $(basename "$PWD")"
echo "Started at: $(date -Iseconds)"
echo ""

# Check for Python dependencies
if ! python3 -c "import blake3" 2>/dev/null; then
    echo "Installing blake3..."
    pip3 install blake3 --quiet
fi

echo "Starting server on http://localhost:8080"
echo "Press Ctrl+C to stop"
echo ""

# Start the server
python3 server.py
