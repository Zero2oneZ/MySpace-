"""pump_feed.py — Pump.fun transaction feeder for dual-GPU ML training.

Polls Solana RPC for new Pump.fun program transactions, extracts features,
and appends to a JSONL queue. Also maintains an in-memory ring buffer
for the inference worker on GPU 0.

Zero external dependencies — stdlib urllib + asyncio.

Usage:
    python3 pump_feed.py --rpc https://api.mainnet-beta.solana.com \
                        --out ./feed/live_features.jsonl \
                        --buffer 10000

Or via cc:
    cc -pump-feed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import ssl
import sys
import time
import urllib.request
import urllib.parse
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pump_constants import PUMP_PROGRAM_ID, FEATURE_DIM
from pump_features import extract_features, features_to_jsonl

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "feed" / "live_features.jsonl"

# ── RPC endpoint pool ─────────────────────────────────────────────────────────
# Tatum key is currently returning "anonymous access" errors for getSignaturesForAddress.
# Re-verify at https://co.tatum.io/signup if you want to use Tatum.
# For now, we round-robin across public endpoints with exponential backoff.
RPC_POOL = [
    "https://api.mainnet-beta.solana.com",
    "https://rpc.ankr.com/solana",
    "https://solana.public-rpc.com",
]
TATUM_KEY = os.environ.get("TATUM_MAINET", "").strip()
if TATUM_KEY:
    # Prepend Tatum if key exists (will be tried first)
    RPC_POOL.insert(0, "https://solana-mainnet.gateway.tatum.io")
DEFAULT_RPC = RPC_POOL[0]

# ── Shared ring buffer (inference worker reads from here) ───────────────────
RING_BUFFER: deque[dict] = deque(maxlen=10000)
HISTORY: list[dict] = []  # recent history for feature computation
HISTORY_MAX = 5000


def _rpc_call_single(rpc_url: str, payload: bytes, headers: dict, timeout: float) -> dict:
    """Single RPC call with backoff. Returns result or error dict."""
    req = urllib.request.Request(rpc_url, data=payload, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    backoff = 1.0
    max_backoff = 16.0
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                body = json.loads(resp.read().decode())
                if "error" in body:
                    err = body["error"]
                    code = err.get("code", 0)
                    if code == 429:
                        time.sleep(backoff)
                        backoff = min(backoff * 2, max_backoff)
                        continue
                    return {"error": f"RPC error {code}: {err}"}
                return body.get("result", {})
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue
            return {"error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}
    return {"error": "Max retries exceeded (rate limit)"}


def _rpc_call(rpc_urls: list[str], method: str, params: list, timeout: float = 30) -> dict:
    """Round-robin across RPC pool. Tries each endpoint once, then returns best result."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    headers = {"Content-Type": "application/json"}
    tatum_key = os.environ.get("TATUM_MAINET", "").strip()
    if tatum_key:
        headers["x-api-key"] = tatum_key

    last_error = {"error": "No endpoints tried"}
    for url in rpc_urls:
        result = _rpc_call_single(url, payload, headers, timeout)
        if "error" not in result:
            return result
        last_error = result
    return last_error


def fetch_signatures(program: str, before: Optional[str] = None, limit: int = 25) -> list[dict]:
    """Fetch transaction signatures for a program (round-robins across RPC_POOL)."""
    params = [program, {"limit": limit}]
    if before:
        params[1]["before"] = before
    result = _rpc_call(RPC_POOL, "getSignaturesForAddress", params)
    if isinstance(result, list):
        return result
    return []


def fetch_transaction(sig: str) -> Optional[dict]:
    """Fetch full transaction details by signature (round-robins across RPC_POOL)."""
    result = _rpc_call(
        RPC_POOL, "getTransaction",
        [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0}],
        timeout=30
    )
    if isinstance(result, dict) and "error" not in result:
        return result
    return None


async def feed_loop(out_path: Path, poll_interval: float = 2.0, verbose: bool = False):
    """Main feed loop — poll for new Pump.fun transactions and write features."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    known_sigs: set[str] = set()
    last_before: Optional[str] = None

    # Warm up: load last N signatures from existing file to avoid duplicates
    if out_path.exists():
        try:
            for line in out_path.read_text().strip().splitlines()[-2000:]:
                try:
                    obj = json.loads(line)
                    sig = obj.get("meta", {}).get("signature", "")
                    if sig:
                        known_sigs.add(sig)
                except Exception:
                    pass
        except Exception:
            pass

    print(f"[pump_feed] RPC pool: {RPC_POOL}")
    print(f"[pump_feed] Output: {out_path}")
    print(f"[pump_feed] Polling every {poll_interval}s")

    while True:
        try:
            sigs = fetch_signatures(PUMP_PROGRAM_ID, before=last_before, limit=25)
            if not sigs:
                await asyncio.sleep(poll_interval)
                continue

            new_count = 0
            for sig_info in reversed(sigs):  # oldest first
                sig = sig_info.get("signature", "")
                if sig in known_sigs:
                    continue
                known_sigs.add(sig)
                last_before = sig

                tx = fetch_transaction(sig)
                if tx is None:
                    continue

                # Extract features
                feats = extract_features(tx, HISTORY)
                pre_bal = tx.get("meta", {}).get("preBalances", [])
                post_bal = tx.get("meta", {}).get("postBalances", [])
                delta = [pb - pa for pa, pb in zip(pre_bal, post_bal)]
                is_buy = bool(sum(max(0, d) for d in delta))
                is_sell = bool(sum(max(0, -d) for d in delta))
                logs = tx.get("meta", {}).get("logMessages", [])
                logs_str = " ".join(logs)
                is_create = "Instruction: Create" in logs_str
                is_buy_log = "Instruction: Buy" in logs_str
                is_sell_log = "Instruction: Sell" in logs_str
                fee = tx.get("meta", {}).get("fee", 5000)

                # Wallet = fee payer (first account key)
                accts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                wallet = accts[0] if accts else sig[:8]

                # Token mint: prefer postTokenBalances mint, else try to parse from logs
                token = None
                ptb = tx.get("meta", {}).get("postTokenBalances", [])
                if ptb:
                    token = ptb[0].get("mint")
                if not token and is_create:
                    # Heuristic: find a 32-44 char base58-ish token in logs after "Create"
                    for line in logs:
                        if "Create" in line:
                            parts = line.split()
                            for p in parts:
                                if 32 <= len(p) <= 44 and p[0] not in "0123456789":
                                    token = p
                                    break
                        if token:
                            break

                obj = {
                    "ts": time.time(),
                    "slot": tx.get("slot", 0),
                    "signature": sig,
                    "wallet": wallet,
                    "token": token,
                    "features": feats,
                    "is_buy": is_buy_log or is_buy,
                    "is_sell": is_sell_log or is_sell,
                    "is_create": is_create,
                    "sol_delta": sum(max(0, d) / 1e9 for d in delta),
                    "fee": fee,
                    "meta": {
                        "err": tx.get("meta", {}).get("err"),
                        "fee": fee,
                        "logMessages": logs,
                        "innerInstructions": tx.get("meta", {}).get("innerInstructions", []),
                        "accountKeys": accts,
                    },
                }

                # Write to JSONL
                with open(out_path, "a") as f:
                    f.write(json.dumps(obj, default=str) + "\n")

                # Push to ring buffer
                RING_BUFFER.append(obj)
                HISTORY.append(obj)
                if len(HISTORY) > HISTORY_MAX:
                    HISTORY.pop(0)

                new_count += 1
                if verbose:
                    print(f"[pump_feed] {sig[:20]}... slot={tx.get('slot')} feats={feats[:4]}")

            if new_count:
                print(f"[pump_feed] {datetime.now(timezone.utc).isoformat()} +{new_count} txs | buffer={len(RING_BUFFER)} | hist={len(HISTORY)}")

        except Exception as e:
            print(f"[pump_feed] ERROR: {e}")

        await asyncio.sleep(poll_interval)


def main():
    ap = argparse.ArgumentParser(description="Pump.fun transaction feeder")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSONL output path")
    ap.add_argument("--poll", type=float, default=2.0, help="Poll interval seconds")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    try:
        asyncio.run(feed_loop(args.out, args.poll, args.verbose))
    except KeyboardInterrupt:
        print("\n[pump_feed] stopped")


if __name__ == "__main__":
    main()
