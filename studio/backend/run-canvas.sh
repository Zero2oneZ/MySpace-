#!/usr/bin/env bash
# Folded canvas: react-flow editor + FastAPI dispatcher + z21 GPU executor.
#   ./backend/run-canvas.sh          local mode — GPU executor + canvas on :8012
#   STUDIO_BACKEND_MODE=remote ...    dispatch passes to the droplet gpu_gateway
set -euo pipefail
cd "$(dirname "$0")/.."
# libstdc++ so numpy/onnx/cv2 import for the real passes
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/home/tom/miniconda3/lib"

# z21 GPU executor — the service the droplet gpu_gateway tunnels to (:8525)
.venv/bin/python -m backend.gpu_server --port 8525 &
GPU=$!
# optional: text/LLM hub (gemma & friends). Uncomment to run locally.
# ANTHROPIC_API_KEY="$CLAUDE_GUEST" .venv/bin/python \
#   deploy/droplet_hub/scripts/ai_orchestrator.py --port 8524 &
trap 'kill $GPU 2>/dev/null || true' EXIT

[ -d frontend/dist ] || ( cd frontend && npm install --no-audit --no-fund && npm run build )
echo "▶ Studio canvas → http://localhost:8012  (passes real on 2×3090; gen nodes synth until comfyui connector)"
exec .venv/bin/python -m uvicorn backend.app:app --port 8012 --host 127.0.0.1
