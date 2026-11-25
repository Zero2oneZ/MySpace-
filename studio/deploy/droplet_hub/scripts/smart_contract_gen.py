"""smart_contract_gen.py — Free public tools + AI content generator.

Serves:
  /tools/pattern-explorer      — token pattern stats
  /tools/token-risk-score      — bot + rug pull scoring
  /tools/smart-contract-generator — Sui/Solana contract scaffold
  /generate/landing-page       — AI-generated HTML landing page

Usage:
    python3 smart_contract_gen.py --port 8526 --ai-endpoint http://127.0.0.1:8524
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
import urllib.request
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
AI_ENDPOINT = "http://127.0.0.1:8524"

# Rate limiting: simple in-memory bucket
RATE_LIMITS: Dict[str, List[float]] = defaultdict(list)


def check_rate(ip: str, max_requests: int, window_s: float = 60.0) -> bool:
    now = time.time()
    window = [t for t in RATE_LIMITS[ip] if now - t < window_s]
    RATE_LIMITS[ip] = window
    if len(window) >= max_requests:
        return False
    RATE_LIMITS[ip].append(now)
    return True


def _ai_generate(prompt: str, backend: str = "auto") -> str:
    """Call AI orchestrator for content generation."""
    try:
        payload = json.dumps({"prompt": prompt, "backend": backend, "max_tokens": 2048}).encode()
        req = urllib.request.Request(
            f"{AI_ENDPOINT}/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "")
    except Exception as e:
        return f"[AI error: {e}]"


# ── Tool implementations ────────────────────────────────────────────────────

def pattern_explorer(token: str, feed_path: Path) -> dict:
    """Analyze a token's pattern from the feed."""
    txs = []
    wallets = set()
    total_delta = 0.0
    buy_count = 0
    sell_count = 0
    with open(feed_path) as f:
        for line in f:
            o = json.loads(line.strip())
            if o.get("token") == token and o.get("slot", 0) > 0:
                txs.append(o)
                wallets.add(o.get("wallet", ""))
                total_delta += o.get("sol_delta", 0.0)
                if o.get("is_buy"):
                    buy_count += 1
                if o.get("is_sell"):
                    sell_count += 1

    if not txs:
        return {"error": "token not found in feed"}

    txs.sort(key=lambda x: x.get("slot", 0))
    slots = [t.get("slot", 0) for t in txs]
    slot_spread = max(slots) - min(slots) if len(slots) > 1 else 0

    return {
        "token": token,
        "tx_count": len(txs),
        "unique_wallets": len(wallets),
        "total_sol_delta": round(total_delta, 6),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "slot_spread": slot_spread,
        "avg_sol_per_tx": round(total_delta / len(txs), 6),
        "first_slot": min(slots),
        "last_slot": max(slots),
    }


def token_risk_score(token: str, feed_path: Path) -> dict:
    """Compute bot activity + rug pull risk score."""
    txs = []
    with open(feed_path) as f:
        for line in f:
            o = json.loads(line.strip())
            if o.get("token") == token and o.get("slot", 0) > 0:
                txs.append(o)

    if not txs:
        return {"error": "token not found"}

    # Heuristics
    wallet_counts = defaultdict(int)
    slot_counts = defaultdict(int)
    for t in txs:
        wallet_counts[t.get("wallet", "")] += 1
        slot_counts[t.get("slot", 0)] += 1

    max_wallet_ratio = max(wallet_counts.values()) / len(txs) if txs else 0
    slot_cluster = max(slot_counts.values()) / len(txs) if txs else 0

    # Score 0-1
    bot_score = min(1.0, max_wallet_ratio * 2 + slot_cluster * 1.5)
    rug_score = min(1.0, (1 if len(txs) < 5 else 0) * 0.3 + max_wallet_ratio * 0.7)

    return {
        "token": token,
        "tx_count": len(txs),
        "bot_score": round(bot_score, 3),
        "rug_pull_probability": round(rug_score, 3),
        "max_wallet_ratio": round(max_wallet_ratio, 3),
        "slot_cluster_ratio": round(slot_cluster, 3),
        "risk_level": "HIGH" if rug_score > 0.7 else "MEDIUM" if rug_score > 0.4 else "LOW",
    }


def smart_contract_generator(description: str, chain: str = "sui") -> str:
    """Generate a smart contract scaffold using AI."""
    prompt = f"""Generate a {chain.upper()} smart contract for: {description}

Requirements:
- Include all necessary imports
- Add comments explaining each function
- Include error handling
- Make it production-ready

Output ONLY the contract code, no explanations outside the code."""
    return _ai_generate(prompt, backend="ollama")


def generate_landing_page(description: str, style: str = "modern") -> str:
    """Generate an HTML landing page using AI."""
    prompt = f"""Generate a complete HTML+CSS landing page for: {description}

Style: {style}
Requirements:
- Use Tailwind CSS (via CDN)
- Include hero section, features, CTA, footer
- Responsive design
- Dark mode default
- No external images (use placeholders)
- Single file, self-contained

Output ONLY the HTML code, no explanations."""
    return _ai_generate(prompt, backend="ollama")


# ── HTTP Handler ────────────────────────────────────────────────────────────

class SmartContractHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html: str):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path
        ip = self.client_address[0]

        if path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return

        if path.startswith("/tools/pattern-explorer"):
            if not check_rate(ip, 10):
                self._send_json(429, {"error": "rate limit exceeded"})
                return
            token = path.split("?token=")[-1] if "?token=" in path else ""
            if not token:
                self._send_json(400, {"error": "missing ?token= parameter"})
                return
            feed = Path("/opt/mspc-public/solana/feed/live_features.jsonl")
            self._send_json(200, pattern_explorer(token, feed))
            return

        if path.startswith("/tools/token-risk-score"):
            if not check_rate(ip, 5):
                self._send_json(429, {"error": "rate limit exceeded"})
                return
            token = path.split("?token=")[-1] if "?token=" in path else ""
            if not token:
                self._send_json(400, {"error": "missing ?token= parameter"})
                return
            feed = Path("/opt/mspc-public/solana/feed/live_features.jsonl")
            self._send_json(200, token_risk_score(token, feed))
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path
        ip = self.client_address[0]
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._send_json(400, {"error": "empty body"})
            return

        body = json.loads(self.rfile.read(length).decode())

        if path == "/tools/smart-contract-generator":
            if not check_rate(ip, 3):
                self._send_json(429, {"error": "rate limit exceeded"})
                return
            desc = body.get("description", "")
            chain = body.get("chain", "sui")
            code = smart_contract_generator(desc, chain)
            self._send_json(200, {"chain": chain, "code": code})
            return

        if path == "/generate/landing-page":
            if not check_rate(ip, 2):
                self._send_json(429, {"error": "rate limit exceeded"})
                return
            desc = body.get("description", "")
            style = body.get("style", "modern")
            html = generate_landing_page(desc, style)
            self._send_json(200, {"html": html})
            return

        self._send_json(404, {"error": "not found"})


def run_server(port: int):
    server = HTTPServer(("127.0.0.1", port), SmartContractHandler)
    print(f"[smart_contract_gen] Listening on 127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[smart_contract_gen] stopped")
        server.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8526)
    ap.add_argument("--ai-endpoint", type=str, default="http://127.0.0.1:8524")
    args = ap.parse_args()
    global AI_ENDPOINT
    AI_ENDPOINT = args.ai_endpoint
    run_server(args.port)


if __name__ == "__main__":
    main()
