"""mcp_host_server.py — MCP endpoint for web services on the droplet.

Exposes tools as both stdio (for MCP clients) and HTTP SSE (for web).
Tools:
  - solana_feed: get latest feed stats
  - pattern_predict: score a pattern
  - token_risk: compute risk score for a token
  - contract_gen: generate smart contract scaffold

Usage:
    python3 mcp_host_server.py --port 8091 --tools solana_feed,pattern_predict,token_risk,contract_gen
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
FEED_PATH = Path("/opt/mspc-public/solana/feed/live_features.jsonl")
MODEL_PATH = Path("/opt/mspc-public/solana/feed/pattern_model.json")

# Tool registry
TOOLS: Dict[str, dict] = {}


def _load_model() -> Optional[dict]:
    if not MODEL_PATH.exists():
        return None
    with open(MODEL_PATH) as f:
        return json.load(f)


def _mat_vec_mul(W, x):
    return [sum(wi * xi for wi, xi in zip(row, x)) for row in W]

def _vec_add(a, b):
    return [ai + bi for ai, bi in zip(a, b)]

def _relu(v):
    return [max(0.0, x) for x in v]

def _sigmoid(x):
    if x < -20:
        return 0.0
    if x > 20:
        return 1.0
    return 1.0 / (1.0 + __import__("math").exp(-x))

def _predict(model: dict, feats: List[float]) -> float:
    z1 = _vec_add(_mat_vec_mul(model["W1"], feats), model["b1"])
    a1 = _relu(z1)
    z2 = _vec_add(_mat_vec_mul(model["W2"], a1), model["b2"])
    return _sigmoid(z2[0])


# ── Tool implementations ────────────────────────────────────────────────────

def tool_solana_feed(args: dict) -> dict:
    """Get latest Solana feed statistics."""
    if not FEED_PATH.exists():
        return {"error": "feed not found"}

    lines = 0
    real = 0
    tokens = set()
    wallets = set()
    with open(FEED_PATH) as f:
        for line in f:
            lines += 1
            try:
                o = json.loads(line.strip())
                if o.get("slot", 0) > 0 and o.get("token"):
                    real += 1
                    tokens.add(o.get("token", ""))
                    wallets.add(o.get("wallet", ""))
            except Exception:
                pass

    return {
        "total_lines": lines,
        "real_records": real,
        "unique_tokens": len(tokens),
        "unique_wallets": len(wallets),
        "feed_path": str(FEED_PATH),
        "timestamp": time.time(),
    }


def tool_pattern_predict(args: dict) -> dict:
    """Score a pattern using the trained MLP."""
    model = _load_model()
    if not model:
        return {"error": "model not found"}

    pattern = args.get("pattern", {})
    chain = pattern.get("chain", [])
    depth = len(chain)
    freq = pattern.get("freq", 0)
    is_rec = 1.0 if pattern.get("recursive") else 0.0
    is_self = 1.0 if pattern.get("self_activating") else 0.0
    tags = pattern.get("tags", [])

    unique_nodes = len(set(chain))
    node_diversity = unique_nodes / depth if depth else 0.0
    root = chain[0] if chain else ""
    is_sys = 1.0 if root == "11111111111111111111111111111111" else 0.0
    is_pump = 1.0 if root == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P" else 0.0
    is_token = 1.0 if root.startswith("Token") else 0.0
    is_other = 1.0 if not (is_sys or is_pump or is_token) else 0.0

    counts = {}
    for c in chain:
        counts[c] = counts.get(c, 0) + 1
    max_rep = max(counts.values()) if counts else 0
    rep_ratio = max_rep / depth if depth else 0.0

    feats = [
        depth / 10.0,
        __import__("math").log1p(freq),
        0.0,
        is_rec,
        is_self,
        node_diversity,
        rep_ratio,
        is_sys,
        is_pump,
        is_token,
        is_other,
        len(tags) / 5.0,
        1.0 if "DEEP_CHAIN" in tags else 0.0,
        1.0 if "DETERMINISTIC_GRID" in tags else 0.0,
        1.0 if "HIGH_FREQUENCY" in tags else 0.0,
    ]

    score = _predict(model, feats)
    return {"predicted_score": round(score, 4), "threshold_met": score >= 0.6}


def tool_token_risk(args: dict) -> dict:
    """Compute risk score for a token."""
    token = args.get("token", "")
    if not token:
        return {"error": "missing token"}

    txs = []
    with open(FEED_PATH) as f:
        for line in f:
            try:
                o = json.loads(line.strip())
                if o.get("token") == token and o.get("slot", 0) > 0:
                    txs.append(o)
            except Exception:
                pass

    if not txs:
        return {"error": "token not found"}

    wallet_counts = defaultdict(int)
    for t in txs:
        wallet_counts[t.get("wallet", "")] += 1
    max_wallet_ratio = max(wallet_counts.values()) / len(txs)
    bot_score = min(1.0, max_wallet_ratio * 2)
    rug_score = min(1.0, (1 if len(txs) < 5 else 0) * 0.3 + max_wallet_ratio * 0.7)

    return {
        "token": token,
        "tx_count": len(txs),
        "bot_score": round(bot_score, 3),
        "rug_pull_probability": round(rug_score, 3),
        "risk_level": "HIGH" if rug_score > 0.7 else "MEDIUM" if rug_score > 0.4 else "LOW",
    }


def tool_contract_gen(args: dict) -> dict:
    """Generate smart contract scaffold."""
    description = args.get("description", "")
    chain = args.get("chain", "sui")
    if not description:
        return {"error": "missing description"}

    # Call AI orchestrator
    ai_endpoint = os.environ.get("AI_ENDPOINT", "http://127.0.0.1:8524")
    try:
        payload = json.dumps({
            "prompt": f"Generate a {chain.upper()} smart contract for: {description}\n\nInclude imports, comments, error handling. Output ONLY code.",
            "backend": "ollama",
            "max_tokens": 2048,
        }).encode()
        req = __import__("urllib.request").Request(
            f"{ai_endpoint}/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with __import__("urllib.request").urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            code = data.get("response", "")
    except Exception as e:
        return {"error": f"AI generation failed: {e}"}

    return {"chain": chain, "code": code}


# Register tools
TOOLS = {
    "solana_feed": {
        "name": "solana_feed",
        "description": "Get latest Solana Pump.fun feed statistics",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_solana_feed,
    },
    "pattern_predict": {
        "name": "pattern_predict",
        "description": "Score an orchestration pattern using the trained MLP",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "object"},
            },
        },
        "handler": tool_pattern_predict,
    },
    "token_risk": {
        "name": "token_risk",
        "description": "Compute bot activity and rug pull risk score for a token",
        "input_schema": {
            "type": "object",
            "properties": {
                "token": {"type": "string"},
            },
        },
        "handler": tool_token_risk,
    },
    "contract_gen": {
        "name": "contract_gen",
        "description": "Generate a Sui or Solana smart contract scaffold",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "chain": {"type": "string", "enum": ["sui", "solana"]},
            },
        },
        "handler": tool_contract_gen,
    },
}


# ── HTTP Handler ────────────────────────────────────────────────────────────

class MCPHostHandler(BaseHTTPRequestHandler):
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/healthz":
            self._send_json(200, {
                "status": "ok",
                "tools": list(TOOLS.keys()),
            })
            return
        if self.path == "/tools":
            self._send_json(200, {
                "tools": [
                    {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                    for t in TOOLS.values()
                ],
            })
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._send_json(400, {"error": "empty body"})
            return

        body = json.loads(self.rfile.read(length).decode())

        if path == "/call":
            tool_name = body.get("tool", "")
            if tool_name not in TOOLS:
                self._send_json(404, {"error": f"tool not found: {tool_name}"})
                return
            args = body.get("args", {})
            result = TOOLS[tool_name]["handler"](args)
            self._send_json(200, {"tool": tool_name, "result": result})
            return

        self._send_json(404, {"error": "not found"})


def run_server(port: int, tools: List[str]):
    # Filter tools
    global TOOLS
    if tools:
        TOOLS = {k: v for k, v in TOOLS.items() if k in tools}

    server = HTTPServer(("127.0.0.1", port), MCPHostHandler)
    print(f"[mcp_host] Listening on 127.0.0.1:{port}")
    print(f"[mcp_host] Tools: {list(TOOLS.keys())}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[mcp_host] stopped")
        server.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--tools", type=str, default="solana_feed,pattern_predict,token_risk,contract_gen")
    args = ap.parse_args()
    tool_list = [t.strip() for t in args.tools.split(",")]
    run_server(args.port, tool_list)


if __name__ == "__main__":
    main()
