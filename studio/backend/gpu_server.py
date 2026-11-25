"""gpu_server.py — the z21 GPU executor (the box the droplet gpu_gateway tunnels to).

This is the missing service the whole remote topology converges on:

    friend browser ─▶ Caddy:443 ─▶ gpu_gateway:8523 ─(WireGuard)─▶ z21:8525 (THIS)
                                                                       │
                                                              passes.inference.* on 2×3090

Contract (matches what gpu_gateway forwards verbatim):
    POST /run   {node_id, params, input_path}  ->  PassResult + {artifact}
    GET  /healthz

PassResult shape comes straight from passes/inference.py:
    {ok, kind, value, path, duration_ms, instruction, pass_id, error}

MUST be launched with libstdc++ on the loader path so numpy/onnx/cv2 import:
    LD_LIBRARY_PATH=/home/tom/miniconda3/lib .venv/bin/python -m backend.gpu_server
(see backend/run-gpu.sh). Passes whose deps are missing return a clean
PassUnavailable instead of crashing.
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from passes import registry as preg            # noqa: E402
from passes import inference as pinf           # noqa: E402
from backend.node_map import route_for         # noqa: E402

# Build {pass_id: Pass}, binding fn from inference.py when the registry left it None.
PASS_BY_ID = {}
for _p in preg.REGISTRY:
    if _p.fn is None:
        _p.fn = getattr(pinf, f"pass_{_p.id}", None)
    PASS_BY_ID[_p.id] = _p


def run_node(node_id: str, params: dict, input_path: str | None) -> dict:
    kind, target = route_for(node_id)
    if kind != "pass":
        return {"ok": False, "error": f"node {node_id} is not a GPU pass (route={kind})",
                "pass_id": None}
    p = PASS_BY_ID.get(target)
    if p is None:
        return {"ok": False, "error": f"no such pass {target!r}", "pass_id": target}
    if p.fn is None:
        return {"ok": False, "error": f"pass {target!r} has no bound callable", "pass_id": target}
    if not input_path or not Path(input_path).exists():
        return {"ok": False, "error": f"input file not found: {input_path!r}", "pass_id": target}
    # passes take (src: Path, **kwargs); pass only kwargs the fn accepts is the fn's job,
    # so forward params loosely and let the shim ignore extras.
    try:
        result = p.fn(Path(input_path), **{k: v for k, v in (params or {}).items()
                                           if k not in ("file", "seed")})
    except TypeError:
        result = p.fn(Path(input_path))   # shim takes no kwargs
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self._json(200, {"status": "ok", "passes": sorted(PASS_BY_ID),
                                    "bound": [k for k, v in PASS_BY_ID.items() if v.fn]})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            return self._json(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n).decode()) if n else {}
        res = run_node(body.get("node_id"), body.get("params", {}), body.get("input_path"))
        self._json(200 if res.get("ok") else 422, res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8525)
    a = ap.parse_args()
    bound = sum(1 for v in PASS_BY_ID.values() if v.fn)
    print(f"[gpu_server] :{a.port} · {len(PASS_BY_ID)} passes ({bound} bound)")
    HTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
