#!/usr/bin/env bash
# z21 GPU executor — the service the droplet gpu_gateway tunnels to.
# libstdc++ on the loader path so numpy/onnx/cv2 import inside the studio venv.
set -euo pipefail
cd "$(dirname "$0")/.."
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/home/tom/miniconda3/lib"
exec .venv/bin/python -m backend.gpu_server --port "${1:-8525}"
