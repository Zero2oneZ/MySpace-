"""pump_ws_feed.py — Real-time Pump.fun WebSocket subscriber.

Uses asyncio + raw socket (no external websockets lib required).
Subscribes to Pump.fun program logs and immediately writes features to JSONL.

Install websockets for better reliability:
    pip install websockets

Usage:
    python3 pump_ws_feed.py --rpc wss://api.mainnet-beta.solana.com
    cc -pump-feed-ws
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import ssl
import struct
import sys
import time
import urllib.parse
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pump_constants import PUMP_PROGRAM_ID, FEATURE_DIM
from pump_features import extract_features

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "feed" / "live_features.jsonl"
DEFAULT_WS = os.environ.get("TATUM_SOL_WS", "wss://api.mainnet-beta.solana.com")

RING_BUFFER: deque[dict] = deque(maxlen=10000)
HISTORY: list[dict] = []
HISTORY_MAX = 5000


def _parse_ws_url(url: str) -> tuple[str, str, int, str]:
    """Parse wss://host:port/path into (host, path, port, ssl)."""
    parsed = urllib.parse.urlparse(url)
    is_ssl = parsed.scheme == "wss"
    port = parsed.port or (443 if is_ssl else 80)
    host = parsed.hostname or parsed.netloc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return host, path, port, is_ssl


# ── Minimal WebSocket frame parser (RFC 6455) ───────────────────────────────

async def _ws_recv(reader: asyncio.StreamReader) -> Optional[bytes]:
    """Read one WebSocket text/binary frame. Returns payload or None on close."""
    try:
        header = await reader.readexactly(2)
    except asyncio.IncompleteReadError:
        return None

    fin = (header[0] & 0x80) != 0
    opcode = header[0] & 0x0f
    masked = (header[1] & 0x80) != 0
    payload_len = header[1] & 0x7f

    if payload_len == 126:
        payload_len = struct.unpack(">H", await reader.readexactly(2))[0]
    elif payload_len == 127:
        payload_len = struct.unpack(">Q", await reader.readexactly(8))[0]

    mask = await reader.readexactly(4) if masked else b"\x00\x00\x00\x00"
    payload = await reader.readexactly(payload_len)
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

    if opcode == 0x08:  # close
        return None
    if opcode == 0x09:  # ping
        return b""  # caller should send pong
    if opcode == 0x0a:  # pong
        return b""
    return payload


async def _ws_send(writer: asyncio.StreamWriter, data: bytes, opcode: int = 0x01):
    """Send one WebSocket text frame."""
    header = [0x80 | opcode]
    length = len(data)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.extend([126, *struct.pack(">H", length)])
    else:
        header.extend([127, *struct.pack(">Q", length)])
    writer.write(bytes(header) + data)
    await writer.drain()


# ── Solana JSON-RPC over WebSocket ────────────────────────────────────────────

async def solana_ws_subscribe(rpc_url: str, program: str, out_path: Path,
                              verbose: bool = False):
    """Subscribe to Pump.fun program logs via WebSocket."""
    host, path, port, is_ssl = _parse_ws_url(rpc_url)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # HTTP upgrade request
    key = base64.b64encode(bytes(range(16))).decode()
    upgrade = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    ).encode()

    ctx = ssl.create_default_context() if is_ssl else None
    reader, writer = await asyncio.open_connection(host, port, ssl=ctx)
    writer.write(upgrade)
    await writer.drain()

    # Read HTTP response
    response = await reader.readline()
    if b"101" not in response:
        print(f"[ws] Upgrade failed: {response.decode().strip()}")
        return
    while await reader.readline() != b"\r\n":
        pass

    # Send logsSubscribe
    sub_id = 1
    req = {
        "jsonrpc": "2.0",
        "id": sub_id,
        "method": "logsSubscribe",
        "params": [{"mentions": [program]}, {"commitment": "confirmed"}]
    }
    await _ws_send(writer, json.dumps(req).encode())

    print(f"[ws] Subscribed to {program} logs on {rpc_url}")
    known_sigs: set[str] = set()

    while True:
        try:
            payload = await asyncio.wait_for(_ws_recv(reader), timeout=60)
            if payload is None:
                print("[ws] Connection closed")
                break
            if not payload:
                continue  # ping/pong
            try:
                msg = json.loads(payload.decode("utf-8", errors="replace"))
            except Exception:
                continue

            if verbose:
                print(f"[ws] {json.dumps(msg, indent=2)[:200]}")

            # Parse log notification
            result = msg.get("params", {}).get("result", {})
            value = result.get("value", {})
            logs = value.get("logs", [])
            signature = value.get("signature", "")
            err = value.get("err")

            if not signature or signature in known_sigs:
                continue
            known_sigs.add(signature)

            # Check for Pump.fun instruction signatures in logs
            is_create = any("Instruction: Create" in log for log in logs)
            is_buy = any("Instruction: Buy" in log for log in logs)
            is_sell = any("Instruction: Sell" in log for log in logs)

            # Extract features from what we have (logs don't have full tx data,
            # so we use what we can + fetch tx details if needed)
            # For speed, we build a partial feature vector from log heuristics.
            feats = [0.0] * FEATURE_DIM
            # Slot
            slot = value.get("slot", 0)
            feats[31] = float(slot)
            # Log-based heuristics
            if is_create:
                feats[29] = 0.0  # just created
            if is_buy:
                feats[9] = 1.0
                feats[14] = 1.0
            if is_sell:
                feats[10] = 1.0
                feats[14] = 0.0

            # Entropy of log patterns
            if logs:
                unique_logs = set(logs)
                import math
                probs = [1.0 / len(unique_logs)] * len(unique_logs)
                feats[17] = -sum(p * math.log2(p) for p in probs)

            obj = {
                "ts": time.time(),
                "slot": slot,
                "signature": signature,
                "features": feats,
                "is_buy": is_buy,
                "is_sell": is_sell,
                "is_create": is_create,
                "sol_delta": 0.0,
                "meta": {
                    "err": err,
                    "log_count": len(logs),
                },
            }

            with open(out_path, "a") as f:
                f.write(json.dumps(obj, default=str) + "\n")

            RING_BUFFER.append(obj)
            HISTORY.append(obj)
            if len(HISTORY) > HISTORY_MAX:
                HISTORY.pop(0)

            if is_create:
                print(f"🪙 NEW TOKEN created at slot={slot} sig={signature[:16]}...")
            elif is_buy:
                print(f"💰 BUY at slot={slot} sig={signature[:16]}...")
            elif is_sell:
                print(f"📉 SELL at slot={slot} sig={signature[:16]}...")

        except asyncio.TimeoutError:
            # Send ping
            await _ws_send(writer, b"", opcode=0x09)
            continue
        except Exception as e:
            print(f"[ws] ERROR: {e}")
            await asyncio.sleep(5)

    writer.close()
    await writer.wait_closed()


# ── Fallback: use websockets library if available ────────────────────────────

async def _ws_lib_subscribe(rpc_url: str, program: str, out_path: Path, verbose: bool = False):
    """Use the `websockets` library if installed (more reliable)."""
    try:
        import websockets
    except ImportError:
        raise RuntimeError("websockets library not installed")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    known_sigs: set[str] = set()

    print(f"[ws_lib] Connecting to {rpc_url}")
    async with websockets.connect(rpc_url) as ws:
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [{"mentions": [program]}, {"commitment": "confirmed"}]
        }
        await ws.send(json.dumps(req))
        print(f"[ws_lib] Subscribed to {program}")

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=60)
                msg = json.loads(raw)
                if verbose:
                    print(f"[ws_lib] {json.dumps(msg)[:200]}")

                value = msg.get("params", {}).get("result", {}).get("value", {})
                logs = value.get("logs", [])
                signature = value.get("signature", "")
                slot = value.get("slot", 0)
                err = value.get("err")

                if not signature or signature in known_sigs:
                    continue
                known_sigs.add(signature)

                is_create = any("Instruction: Create" in log for log in logs)
                is_buy = any("Instruction: Buy" in log for log in logs)
                is_sell = any("Instruction: Sell" in log for log in logs)

                feats = [0.0] * FEATURE_DIM
                feats[31] = float(slot)
                if is_buy:
                    feats[9] = 1.0
                    feats[14] = 1.0
                if is_sell:
                    feats[10] = 1.0
                    feats[14] = 0.0
                if logs:
                    unique_logs = set(logs)
                    import math
                    probs = [1.0 / len(unique_logs)] * len(unique_logs)
                    feats[17] = -sum(p * math.log2(p) for p in probs)

                obj = {
                    "ts": time.time(), "slot": slot, "signature": signature,
                    "features": feats, "is_buy": is_buy, "is_sell": is_sell,
                    "is_create": is_create, "sol_delta": 0.0,
                    "meta": {"err": err, "log_count": len(logs)},
                }
                with open(out_path, "a") as f:
                    f.write(json.dumps(obj, default=str) + "\n")
                RING_BUFFER.append(obj)
                HISTORY.append(obj)
                if len(HISTORY) > HISTORY_MAX:
                    HISTORY.pop(0)

                emoji = "🪙" if is_create else ("💰" if is_buy else ("📉" if is_sell else "📡"))
                print(f"{emoji} slot={slot} sig={signature[:16]}... create={is_create} buy={is_buy} sell={is_sell}")

            except asyncio.TimeoutError:
                await ws.ping()
            except Exception as e:
                print(f"[ws_lib] ERROR: {e}")
                await asyncio.sleep(5)


async def main_async():
    ap = argparse.ArgumentParser(description="Pump.fun WebSocket feed")
    ap.add_argument("--rpc", default=DEFAULT_WS, help="WebSocket RPC URL")
    ap.add_argument("--program", default=PUMP_PROGRAM_ID)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--use-lib", action="store_true", help="Use websockets library if installed")
    args = ap.parse_args()

    if args.use_lib:
        try:
            await _ws_lib_subscribe(args.rpc, args.program, args.out, args.verbose)
        except RuntimeError:
            print("! websockets library not installed, falling back to raw socket")
            await solana_ws_subscribe(args.rpc, args.program, args.out, args.verbose)
    else:
        await solana_ws_subscribe(args.rpc, args.program, args.out, args.verbose)


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[ws] stopped")


if __name__ == "__main__":
    main()
