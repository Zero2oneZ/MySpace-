"""sui_ws_feed.py — Real-time Sui DEX WebSocket subscriber.

Subscribes to Sui event stream for DEX package transactions.
Uses raw asyncio socket (no external websockets lib required).

Install websockets for better reliability:
    pip install websockets

Usage:
    python3 sui_ws_feed.py --rpc wss://sui-mainnet-grpc.gateway.tatum.io
    cc -sui-feed-ws
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
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sui_constants import DEX_PACKAGES, FEATURE_DIM
from sui_features import extract_features

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "feed" / "live_features.jsonl"
DEFAULT_WS = os.environ.get("TATUMT_SUI_WS", os.environ.get("SUI_WS", "wss://sui-mainnet-grpc.gateway.tatum.io"))

# ── Shared ring buffer ────────────────────────────────────────────────────────
RING_BUFFER: deque[dict] = deque(maxlen=10000)
HISTORY: list[dict] = []
HISTORY_MAX = 5000


class WsFrame:
    """Minimal WebSocket frame parser/encoder (RFC 6455)."""

    @staticmethod
    def encode(text: str, opcode: int = 0x1) -> bytes:
        data = text.encode("utf-8")
        length = len(data)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, length)
        elif length < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 127, length)
        return header + data

    @staticmethod
    def parse(buffer: bytes) -> tuple[Optional[bytes], bytes]:
        if len(buffer) < 2:
            return None, buffer
        b1, b2 = buffer[0], buffer[1]
        fin = (b1 >> 7) & 1
        opcode = b1 & 0x0F
        masked = (b2 >> 7) & 1
        payload_len = b2 & 0x7F
        offset = 2
        if payload_len == 126:
            if len(buffer) < 4:
                return None, buffer
            payload_len = struct.unpack("!H", buffer[2:4])[0]
            offset = 4
        elif payload_len == 127:
            if len(buffer) < 10:
                return None, buffer
            payload_len = struct.unpack("!Q", buffer[2:10])[0]
            offset = 10
        mask_key = buffer[offset:offset + 4] if masked else b""
        offset += 4 if masked else 0
        if len(buffer) < offset + payload_len:
            return None, buffer
        payload = buffer[offset:offset + payload_len]
        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        if opcode == 0x8:
            return payload, b""  # close frame
        if opcode == 0x9:
            return b"PING", buffer[offset + payload_len:]
        if opcode == 0xA:
            return b"PONG", buffer[offset + payload_len:]
        return payload, buffer[offset + payload_len:]


async def _ws_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host: str, path: str):
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    writer.write(req.encode())
    await writer.drain()
    # Read HTTP response
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = await reader.read(1024)
        if not chunk:
            raise ConnectionError("WebSocket handshake failed")
        response += chunk
    if b"101" not in response:
        raise ConnectionError(f"WebSocket handshake failed: {response[:200]}")


async def _ws_read(reader: asyncio.StreamReader) -> Optional[str]:
    buf = b""
    while True:
        chunk = await reader.read(4096)
        if not chunk:
            return None
        buf += chunk
        payload, buf = WsFrame.parse(buf)
        if payload is not None:
            if payload == b"PING":
                continue
            if payload == b"PONG":
                continue
            try:
                return payload.decode("utf-8")
            except UnicodeDecodeError:
                continue


def _subscribe_payload(dex_pkg: str) -> str:
    return json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sui_subscribeEvent",
        "params": [{
            "MoveEventModule": {
                "package": dex_pkg,
                "module": "*",
            }
        }]
    })


def _subscribe_txs(dex_pkg: str) -> str:
    return json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "sui_subscribeTransaction",
        "params": [{
            "FromAddress": "*",
            "MoveModule": {
                "package": dex_pkg,
                "module": "*",
            }
        }]
    })


async def feed_loop(ws_url: str, out_path: Path, verbose: bool = False):
    """WebSocket feed loop for Sui DEX events."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    known_digests: set[str] = set()

    # Parse URL
    parsed = ws_url.replace("wss://", "").replace("ws://", "")
    host = parsed.split("/")[0]
    path = "/" + "/".join(parsed.split("/")[1:]) if "/" in parsed else "/"
    use_ssl = ws_url.startswith("wss://")
    port = 443 if use_ssl else 80

    print(f"[sui_ws_feed] Connecting to {ws_url}")

    reader, writer = await asyncio.open_connection(host, port, ssl=use_ssl)
    await _ws_handshake(reader, writer, host, path)
    print("[sui_ws_feed] Handshake OK")

    # Subscribe to all DEX packages
    for name, pkg in DEX_PACKAGES.items():
        writer.write(WsFrame.encode(_subscribe_payload(pkg)))
        writer.write(WsFrame.encode(_subscribe_txs(pkg)))
        await writer.drain()
        print(f"[sui_ws_feed] Subscribed to {name} ({pkg[:16]}...)")

    while True:
        try:
            text = await asyncio.wait_for(_ws_read(reader), timeout=60.0)
            if text is None:
                print("[sui_ws_feed] Connection closed")
                break
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                continue

            result = msg.get("params", {}).get("result", {})
            digest = result.get("id", {}).get("txDigest", "") or result.get("txDigest", "")
            if not digest or digest in known_digests:
                continue
            known_digests.add(digest)
            if len(known_digests) > 50000:
                known_digests = set(list(known_digests)[-25000:])

            # Build minimal tx-like object for feature extraction
            tx_obj = {
                "effects": {
                    "status": {"status": result.get("status", "success"), "error": None},
                    "gasUsed": {
                        "computationCost": result.get("gasUsage", 0),
                        "storageCost": 0,
                        "storageRebate": 0,
                    },
                    "balanceChanges": result.get("balanceChanges", []),
                },
                "transaction": {
                    "data": {
                        "sender": result.get("sender", ""),
                        "transaction": {
                            "transactions": result.get("transaction", {}).get("data", {}).get("transactions", []),
                        },
                    }
                },
                "events": result.get("events", []),
                "timestampMs": result.get("timestampMs", int(time.time() * 1000)),
                "checkpoint": result.get("checkpoint", "0"),
                "epoch": result.get("epoch", "0"),
                "digest": digest,
            }

            feats = extract_features(tx_obj, HISTORY)
            deltas = []
            for change in tx_obj["effects"]["balanceChanges"]:
                amt = change.get("amount", "0")
                try:
                    deltas.append(float(amt) / 1e9)
                except (ValueError, TypeError):
                    pass

            obj = {
                "ts": time.time(),
                "checkpoint": tx_obj["checkpoint"],
                "digest": digest,
                "epoch": tx_obj["epoch"],
                "sender": tx_obj["transaction"]["data"]["sender"],
                "features": feats,
                "balance_deltas": deltas,
                "gas": tx_obj["effects"]["gasUsed"],
                "meta": {
                    "status": tx_obj["effects"]["status"]["status"],
                    "err": None,
                },
            }

            with open(out_path, "a") as f:
                f.write(json.dumps(obj, default=str) + "\n")

            RING_BUFFER.append(obj)
            HISTORY.append(obj)
            if len(HISTORY) > HISTORY_MAX:
                HISTORY.pop(0)

            if verbose:
                print(f"[sui_ws_feed] {digest[:16]}... ckpt={tx_obj['checkpoint']} feats={feats[:4]}")
            else:
                if len(RING_BUFFER) % 100 == 0:
                    print(f"[sui_ws_feed] {datetime.now(timezone.utc).isoformat()} buffer={len(RING_BUFFER)} hist={len(HISTORY)}")

        except asyncio.TimeoutError:
            print("[sui_ws_feed] Timeout, sending ping...")
            writer.write(WsFrame.encode("", opcode=0x9))
            await writer.drain()
        except KeyboardInterrupt:
            print("\n[sui_ws_feed] Stopped")
            break
        except Exception as e:
            print(f"[sui_ws_feed] ERROR: {e}")
            await asyncio.sleep(5)

    writer.close()
    await writer.wait_closed()


def main():
    ap = argparse.ArgumentParser(description="Sui DEX WebSocket feeder")
    ap.add_argument("--rpc", default=DEFAULT_WS, help="Sui WebSocket endpoint")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="JSONL output path")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    try:
        asyncio.run(feed_loop(args.rpc, args.out, args.verbose))
    except KeyboardInterrupt:
        print("\n[sui_ws_feed] stopped")


if __name__ == "__main__":
    main()
