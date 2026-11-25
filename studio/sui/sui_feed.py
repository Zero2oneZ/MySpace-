"""sui_feed.py — Sui DEX transaction feeder for dual-GPU ML training.

Polls Sui RPC for new DEX package transactions, extracts features,
and appends to a JSONL queue. Also maintains an in-memory ring buffer
for the inference worker on GPU 0.

Zero external dependencies — stdlib urllib + asyncio.

Usage:
    python3 sui_feed.py --rpc https://sui-mainnet-grpc.gateway.tatum.io \
                        --out ./feed/live_features.jsonl \
                        --poll 3

Or via cc:
    cc -sui-feed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sui_constants import DEX_PACKAGES, FEATURE_DIM
from sui_features import extract_features

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "feed" / "live_features.jsonl"
DEFAULT_RPC = os.environ.get("TATUMT_SUI", os.environ.get("SUI_RPC", "https://sui-mainnet-grpc.gateway.tatum.io"))

# ── Shared ring buffer (inference worker reads from here) ────────────────────
RING_BUFFER: deque[dict] = deque(maxlen=10000)
HISTORY: list[dict] = []
HISTORY_MAX = 5000


def _rpc_call(rpc_url: str, method: str, params: list, timeout: float = 30) -> dict:
    """Minimal JSON-RPC 2.0 call over HTTP."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = json.loads(resp.read().decode())
            return body.get("result", {})
    except Exception as e:
        return {"error": str(e)}


def get_latest_checkpoint(rpc_url: str) -> int:
    """Fetch latest checkpoint sequence number."""
    result = _rpc_call(rpc_url, "sui_getLatestCheckpointSequenceNumber", [])
    try:
        return int(result)
    except (ValueError, TypeError):
        return 0


def get_checkpoint(rpc_url: str, seq: int) -> dict:
    """Fetch checkpoint by sequence number."""
    return _rpc_call(rpc_url, "sui_getCheckpoint", [str(seq)])


def get_tx_blocks(rpc_url: str, digests: list[str]) -> list[dict]:
    """Fetch multiple transaction blocks by digest."""
    if not digests:
        return []
    result = _rpc_call(rpc_url, "sui_multiGetTransactionBlocks", [
        digests,
        {"showInput": True, "showEffects": True, "showEvents": True, "showBalanceChanges": True}
    ])
    if isinstance(result, list):
        return result
    return []


def is_dex_tx(tx: dict) -> bool:
    """Check if transaction touches any known DEX package."""
    tx_data = tx.get("transaction", {}).get("data", {})
    for cmd in tx_data.get("transaction", {}).get("transactions", []):
        for key, val in cmd.items():
            if isinstance(val, dict) and "package" in val:
                pkg = val.get("package", "")
                if pkg in DEX_PACKAGES:
                    return True
    # Also check events
    for evt in tx.get("events", []):
        pkg = evt.get("packageId", "")
        if pkg in DEX_PACKAGES:
            return True
    return False


async def feed_loop(rpc_url: str, out_path: Path, poll_interval: float = 3.0, verbose: bool = False):
    """Main feed loop — poll for new Sui checkpoints and write DEX features."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    known_digests: set[str] = set()
    last_checkpoint = get_latest_checkpoint(rpc_url)

    print(f"[sui_feed] Connected to {rpc_url}")
    print(f"[sui_feed] Output: {out_path}")
    print(f"[sui_feed] Starting from checkpoint {last_checkpoint}")

    while True:
        try:
            latest = get_latest_checkpoint(rpc_url)
            if latest <= last_checkpoint:
                await asyncio.sleep(poll_interval)
                continue

            new_count = 0
            for seq in range(last_checkpoint + 1, latest + 1):
                ckpt = get_checkpoint(rpc_url, seq)
                digests = ckpt.get("transactions", [])
                if not digests:
                    continue

                # Filter known
                new_digests = [d for d in digests if d not in known_digests]
                known_digests.update(digests)

                # Trim known set
                if len(known_digests) > 50000:
                    known_digests = set(list(known_digests)[-25000:])

                # Batch fetch tx blocks
                txs = get_tx_blocks(rpc_url, new_digests)
                for tx in txs:
                    if not is_dex_tx(tx):
                        continue

                    digest = tx.get("digest", "")
                    feats = extract_features(tx, HISTORY)
                    effects = tx.get("effects", {})
                    gas = effects.get("gasUsed", {})
                    deltas = []
                    for change in effects.get("balanceChanges", []):
                        amt = change.get("amount", "0")
                        try:
                            deltas.append(float(amt) / 1e9)
                        except (ValueError, TypeError):
                            pass

                    obj = {
                        "ts": time.time(),
                        "checkpoint": tx.get("checkpoint", "0"),
                        "digest": digest,
                        "epoch": tx.get("epoch", "0"),
                        "sender": tx.get("transaction", {}).get("data", {}).get("sender", ""),
                        "features": feats,
                        "gas": {
                            "computationCost": float(gas.get("computationCost", 0)),
                            "storageCost": float(gas.get("storageCost", 0)),
                            "storageRebate": float(gas.get("storageRebate", 0)),
                        },
                        "balance_deltas": deltas,
                        "meta": {
                            "status": effects.get("status", {}).get("status", ""),
                            "err": effects.get("status", {}).get("error", None),
                        },
                    }

                    with open(out_path, "a") as f:
                        f.write(json.dumps(obj, default=str) + "\n")

                    RING_BUFFER.append(obj)
                    HISTORY.append(obj)
                    if len(HISTORY) > HISTORY_MAX:
                        HISTORY.pop(0)

                    new_count += 1
                    if verbose:
                        print(f"[sui_feed] {digest[:16]}... ckpt={seq} feats={feats[:4]}")

            last_checkpoint = latest
            if new_count:
                print(f"[sui_feed] {datetime.now(timezone.utc).isoformat()} +{new_count} txs | buffer={len(RING_BUFFER)} | hist={len(HISTORY)}")

        except Exception as e:
            print(f"[sui_feed] ERROR: {e}")

        await asyncio.sleep(poll_interval)


def main():
    ap = argparse.ArgumentParser(description="Sui DEX transaction feeder")
    ap.add_argument("--rpc", default=DEFAULT_RPC, help="Sui RPC endpoint")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSONL output path")
    ap.add_argument("--poll", type=float, default=3.0, help="Poll interval seconds")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    try:
        asyncio.run(feed_loop(args.rpc, args.out, args.poll, args.verbose))
    except KeyboardInterrupt:
        print("\n[sui_feed] stopped")


if __name__ == "__main__":
    main()
