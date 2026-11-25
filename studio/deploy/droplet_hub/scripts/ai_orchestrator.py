"""ai_orchestrator.py — Centralized AI hub: Ollama + Claude + cc dispatch.

Usage:
    python3 ai_orchestrator.py --port 8524 --backends ollama,claude,cc
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional

# Backend endpoints (configured via env or defaults)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.200.200.2:11434")  # WireGuard to local
CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_BASE_URL = "https://api.anthropic.com/v1/messages"
CC_TINY_URL = os.environ.get("CC_TINY_URL", "http://10.200.200.2:7681")  # local cc tiny endpoint


def _ollama_generate(prompt: str, model: str = "qwen3-coder-next:latest") -> str:
    """Forward to local Ollama via WireGuard."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "")
    except Exception as e:
        return f"[ollama error: {e}]"


def _claude_generate(prompt: str, max_tokens: int = 1024) -> str:
    """Call Anthropic Claude API."""
    if not CLAUDE_API_KEY:
        return "[claude error: no ANTHROPIC_API_KEY]"
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        CLAUDE_BASE_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            return data.get("content", [{"text": ""}])[0].get("text", "")
    except Exception as e:
        return f"[claude error: {e}]"


def _cc_tiny_generate(prompt: str) -> str:
    """Call local cc tiny endpoint."""
    payload = json.dumps({"prompt": prompt}).encode()
    req = urllib.request.Request(
        f"{CC_TINY_URL}/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode()
    except Exception as e:
        return f"[cc tiny error: {e}]"


class AIOrchestratorHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

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
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._send_json(400, {"error": "empty body"})
            return

        body = json.loads(self.rfile.read(length).decode())
        prompt = body.get("prompt", "")
        backend = body.get("backend", "auto")  # auto | ollama | claude | cc
        max_tokens = body.get("max_tokens", 1024)

        if not prompt:
            self._send_json(400, {"error": "missing prompt"})
            return

        # Route to backend
        if backend == "auto":
            # Default to ollama for speed, fallback to claude
            result = _ollama_generate(prompt)
            if result.startswith("[ollama error"):
                result = _claude_generate(prompt, max_tokens)
        elif backend == "ollama":
            result = _ollama_generate(prompt, body.get("model", "qwen3-coder-next:latest"))
        elif backend == "claude":
            result = _claude_generate(prompt, max_tokens)
        elif backend == "cc":
            result = _cc_tiny_generate(prompt)
        else:
            self._send_json(400, {"error": f"unknown backend: {backend}"})
            return

        self._send_json(200, {
            "backend": backend,
            "prompt": prompt,
            "response": result,
        })

    def do_GET(self):
        if self.path == "/healthz":
            self._send_json(200, {
                "status": "ok",
                "backends": ["ollama", "claude", "cc"],
                "ollama_url": OLLAMA_URL,
            })
            return
        self._send_json(404, {"error": "not found"})


def run_server(port: int):
    server = HTTPServer(("127.0.0.1", port), AIOrchestratorHandler)
    print(f"[ai_orchestrator] Listening on 127.0.0.1:{port}")
    print(f"[ai_orchestrator] Ollama: {OLLAMA_URL}")
    print(f"[ai_orchestrator] Claude: {'enabled' if CLAUDE_API_KEY else 'disabled'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ai_orchestrator] stopped")
        server.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8524)
    ap.add_argument("--backends", type=str, default="ollama,claude,cc")
    args = ap.parse_args()
    run_server(args.port)


if __name__ == "__main__":
    main()
