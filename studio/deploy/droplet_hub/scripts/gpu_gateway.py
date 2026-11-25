"""gpu_gateway.py — Droplet-side GPU inference gateway.

Receives inference requests via HTTP, validates friend-token,
and forwards through WireGuard tunnel to local GPU machine.

Usage:
    python3 gpu_gateway.py --port 8523 --tunnel-interface wg0
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
TUNNEL_HOST = os.environ.get("GPU_TUNNEL_HOST", "10.200.200.2")  # WireGuard peer IP
TUNNEL_PORT = int(os.environ.get("GPU_TUNNEL_PORT", "8525"))


def validate_token(token: str) -> bool:
    """Validate friend-token against local keys.sqlite."""
    # In production, query the auth substrate
    # For now, accept any non-empty token with length > 16
    return bool(token and len(token) > 16)


class GPUHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress noisy logs

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_POST(self):
        path = self.path
        auth = self.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""

        if not validate_token(token):
            self._send_json(401, {"error": "invalid or missing token"})
            return

        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._send_json(400, {"error": "empty body"})
            return

        body = self.rfile.read(length)

        # Forward to local GPU via WireGuard tunnel
        try:
            url = f"http://{TUNNEL_HOST}:{TUNNEL_PORT}{path}"
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_body = resp.read()
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(k, v)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            self._send_json(e.code, {"error": str(e.reason)})
        except Exception as e:
            self._send_json(502, {"error": f"GPU tunnel failed: {e}"})

    def do_GET(self):
        # Health check
        if self.path == "/healthz":
            self._send_json(200, {"status": "ok", "gpu_tunnel": f"{TUNNEL_HOST}:{TUNNEL_PORT}"})
            return
        self._send_json(404, {"error": "not found"})


def run_server(port: int):
    server = HTTPServer(("127.0.0.1", port), GPUHandler)
    print(f"[gpu_gateway] Listening on 127.0.0.1:{port}")
    print(f"[gpu_gateway] GPU tunnel: {TUNNEL_HOST}:{TUNNEL_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[gpu_gateway] stopped")
        server.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8523)
    ap.add_argument("--tunnel-interface", type=str, default="wg0")
    args = ap.parse_args()
    run_server(args.port)


if __name__ == "__main__":
    main()
