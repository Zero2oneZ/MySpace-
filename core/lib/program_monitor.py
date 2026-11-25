"""program_monitor.py — multi-program WS supervisor for OTHER web3 apps.

One asyncio task per registered watch=true program. Sinks events to
~/.cc/program_events/<chain>/<short>/<YYYY-MM-DD>.jsonl (append-only).

Solana: logsSubscribe per program_id (RFC 8259 JSON-RPC over WebSocket).
Sui: suix_subscribeEvent per package_id (Move event subscription).

Reuses the raw RFC-6455 frame parser pattern from studio/solana/pump_ws_feed.py
so there is no external WS dep. If the `websockets` library is importable, we
prefer it (faster reconnect, pong handling) and fall back to raw sockets
otherwise.

Every emitted event is run through dimension_pack.emit() so it carries the
canonical 5-tuple signature (vector/circle/hex/rgb/fps) and joins the rest of
the chain in the same coordinate space.
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "lib"))

try:
    from program_registry import ProgramEntry, load as registry_load, watchset
except Exception as exc:  # pragma: no cover
    print(f"[monitor] program_registry import failed: {exc}", file=sys.stderr)
    raise

try:
    from inference_logger import InferenceLogger
    _LOG = InferenceLogger()
except Exception:
    _LOG = None

try:
    from dimension_pack import emit as _dim_emit
except Exception:
    _dim_emit = None

EVENT_ROOT = Path(os.path.expanduser("~/.cc/program_events"))

SOLANA_WSS = os.environ.get("SOLANA_RPC_WSS",
                             "wss://api.mainnet-beta.solana.com")
SUI_WSS = os.environ.get("SUI_RPC_WSS",
                          "wss://fullnode.mainnet.sui.io:443")

# Hard cap on event throughput per program so a token-program subscription
# can never blow up disk (token program is watch=false in seed for this reason).
DEFAULT_PER_PROGRAM_EPS_CAP = 50  # events per second


# ── path helpers ──

def _short(program_id: str) -> str:
    if program_id.startswith("0x"):  # Sui
        body = program_id[2:]
        return body[:8] if len(body) >= 8 else body
    return program_id[:8] if len(program_id) >= 8 else program_id


def _event_path(chain: str, program_id: str) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = EVENT_ROOT / chain / _short(program_id) / f"{today}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── raw WS plumbing (mirrors studio/solana/pump_ws_feed.py) ──

def _parse_ws_url(url: str) -> Tuple[str, str, int, bool]:
    parsed = urllib.parse.urlparse(url)
    is_ssl = parsed.scheme == "wss"
    port = parsed.port or (443 if is_ssl else 80)
    host = parsed.hostname or parsed.netloc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return host, path, port, is_ssl


async def _ws_recv(reader: asyncio.StreamReader) -> Optional[bytes]:
    try:
        header = await reader.readexactly(2)
    except asyncio.IncompleteReadError:
        return None
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
    if opcode == 0x08:
        return None
    if opcode in (0x09, 0x0a):
        return b""
    return payload


async def _ws_send(writer: asyncio.StreamWriter, data: bytes, opcode: int = 0x01) -> None:
    header = [0x80 | opcode]
    length = len(data)
    # client → server must mask
    mask_flag = 0x80
    if length < 126:
        header.append(mask_flag | length)
    elif length < 65536:
        header.extend([mask_flag | 126, *struct.pack(">H", length)])
    else:
        header.extend([mask_flag | 127, *struct.pack(">Q", length)])
    mask_key = os.urandom(4)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
    writer.write(bytes(header) + mask_key + masked)
    await writer.drain()


async def _ws_open(url: str) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    host, path, port, is_ssl = _parse_ws_url(url)
    ctx = ssl.create_default_context() if is_ssl else None
    reader, writer = await asyncio.open_connection(host, port, ssl=ctx)
    key = base64.b64encode(os.urandom(16)).decode()
    upgrade = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    ).encode()
    writer.write(upgrade)
    await writer.drain()
    line = await reader.readline()
    if b"101" not in line:
        raise RuntimeError(f"WS upgrade failed: {line!r}")
    while await reader.readline() != b"\r\n":
        pass
    return reader, writer


# ── per-program subscriber tasks ──

@dataclass
class SubscriberStats:
    chain: str
    program_id: str
    name: str
    events: int = 0
    last_ts: float = 0.0
    last_error: str = ""
    started_at: float = 0.0

    def short(self) -> str:
        return _short(self.program_id)


def _classify_solana_logs(logs: List[str]) -> str:
    """Cheap heuristic action tag from log strings; only what's universal."""
    text = "\n".join(logs)
    if "Instruction: Create" in text:
        return "create"
    if "Instruction: Buy" in text or "Instruction: Swap" in text:
        return "buy"
    if "Instruction: Sell" in text:
        return "sell"
    if "Instruction: Borrow" in text:
        return "borrow"
    if "Instruction: Deposit" in text:
        return "deposit"
    if "Instruction: Withdraw" in text:
        return "withdraw"
    if "Instruction: Liquidate" in text:
        return "liquidate"
    if "Instruction: PlaceOrder" in text or "Instruction: NewOrder" in text:
        return "order_place"
    if "Instruction: CancelOrder" in text:
        return "order_cancel"
    return "other"


def _dim_pack(event: Dict, crystal_id: str) -> Dict:
    if _dim_emit is None:
        return {}
    try:
        # Enrich the record so dimension_pack's vector + circle axes carry
        # signal from the actual chain event content, not all-zero fallbacks.
        # vector: SHA-256 fallback in multi_layer_hex hashes the canonical
        # JSON we pass — we want program_id + action + signature in there so
        # different events get different vectors that cluster by program/action.
        # circle: chain:<category>:<action> is a real recurring motif the NN
        # can pick up on (every buy on every DEX shares the same circle).
        program_id = event.get("program_id", "")
        action = event.get("action", "other")
        category = event.get("category", "")
        record = {
            "tier": "external_chain_event",
            "model": event.get("chain", ""),
            "cost_class": "free",
            "sub_dag": "PLATFORMS",
            "ts": event.get("ts", time.time()),
            # the enrichment payload below is what multi_layer_hex hashes:
            "program_id": program_id,
            "program_short": event.get("program_short", ""),
            "category": category,
            "action": action,
            "signature": event.get("signature") or event.get("tx_digest", ""),
            "slot": event.get("slot", 0),
            "log_count": event.get("log_count", 0),
            "err": event.get("err", False),
            # synthetic categorical-circle motif (chain:<cat>:<action>) gives
            # the recursion detector a leaf-to-bucket mapping until the
            # chain-event SCC detector lands.
            "circle_hint": f"chain:{category}:{action}" if category else f"chain:{event.get('chain','')}:{action}",
        }
        pack = _dim_emit(record, crystal_id=crystal_id)
        circle = pack.circle_motif_id
        if circle in ("", "*", None):
            circle = record["circle_hint"]
        return {
            "rgba": pack.rgba,
            "vec64": pack.vector_hex_64,
            "circle": circle,
            "frame60": pack.frame_pack.get(60, 0),
        }
    except Exception as exc:
        return {"err": repr(exc)[:80]}


def _sink(event: Dict, stats: SubscriberStats, eps_cap: int) -> bool:
    """Append event JSONL, return False if rate-limited."""
    now = time.time()
    # 1-second sliding bucket
    bucket = int(now)
    if not hasattr(_sink, "_buckets"):
        _sink._buckets = {}  # type: ignore
    key = (stats.chain, stats.program_id)
    cur_bucket, cur_count = _sink._buckets.get(key, (bucket, 0))  # type: ignore
    if cur_bucket != bucket:
        cur_bucket, cur_count = bucket, 0
    if cur_count >= eps_cap:
        _sink._buckets[key] = (cur_bucket, cur_count + 1)  # type: ignore
        return False
    _sink._buckets[key] = (cur_bucket, cur_count + 1)  # type: ignore
    path = _event_path(stats.chain, stats.program_id)
    with path.open("a") as f:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")
    stats.events += 1
    stats.last_ts = now
    return True


async def solana_subscriber(entry: ProgramEntry, rpc_wss: str,
                             stats: SubscriberStats,
                             eps_cap: int,
                             stop_event: asyncio.Event,
                             verbose: bool = False) -> None:
    sub_id = 0
    backoff = 1.0
    crystal_id = ""
    if _LOG is not None:
        try:
            payload = json.dumps({
                "program_id": entry.program_id, "name": entry.name,
                "category": entry.category, "rpc": rpc_wss,
            })
            crystal_id = _LOG.log(
                original_prompt=f"sub_open:solana:{entry.short()}",
                enhanced_prompt=payload,
                output_text=payload,
                tier="external_chain_event",
                model="solana",
                scope=f"sub_open:{entry.category}",
                source_action="program_monitor.solana_subscriber",
            ) or ""
        except Exception as exc:
            print(f"[sol] log open failed: {exc!r}", file=sys.stderr)
            crystal_id = ""

    while not stop_event.is_set():
        try:
            reader, writer = await _ws_open(rpc_wss)
            sub_id += 1
            req = {
                "jsonrpc": "2.0",
                "id": sub_id,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [entry.program_id]},
                    {"commitment": "confirmed"},
                ],
            }
            await _ws_send(writer, json.dumps(req).encode())
            stats.started_at = time.time()
            if verbose:
                print(f"[sol] subscribed {entry.short()} {entry.name}",
                      file=sys.stderr)
            seen_sigs: set = set()
            while not stop_event.is_set():
                try:
                    payload = await asyncio.wait_for(_ws_recv(reader), timeout=60)
                except asyncio.TimeoutError:
                    await _ws_send(writer, b"", opcode=0x09)  # ping
                    continue
                if payload is None:
                    break
                if not payload:
                    continue
                try:
                    msg = json.loads(payload.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                params = msg.get("params") or {}
                result = params.get("result") or {}
                value = result.get("value") or {}
                logs = value.get("logs") or []
                signature = value.get("signature", "")
                err = value.get("err")
                slot = (result.get("context") or {}).get("slot") \
                    or value.get("slot", 0)
                if not signature or signature in seen_sigs:
                    continue
                seen_sigs.add(signature)
                if len(seen_sigs) > 50000:
                    seen_sigs = set(list(seen_sigs)[-25000:])
                event = {
                    "ts": time.time(),
                    "chain": "solana",
                    "program_id": entry.program_id,
                    "program_short": entry.short(),
                    "program_name": entry.name,
                    "category": entry.category,
                    "slot": slot,
                    "signature": signature,
                    "action": _classify_solana_logs(logs),
                    "log_count": len(logs),
                    "err": err is not None,
                }
                event["dim"] = _dim_pack(event, crystal_id)
                ok = _sink(event, stats, eps_cap)
                if verbose and ok and event["action"] != "other":
                    print(f"[sol:{entry.short()}] {event['action']} slot={slot}",
                          file=sys.stderr)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            stats.last_error = "disconnected; reconnecting"
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stats.last_error = repr(exc)[:200]
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def sui_subscriber(entry: ProgramEntry, rpc_wss: str,
                          stats: SubscriberStats,
                          eps_cap: int,
                          stop_event: asyncio.Event,
                          verbose: bool = False) -> None:
    sub_id = 0
    backoff = 1.0
    crystal_id = ""
    if _LOG is not None:
        try:
            payload = json.dumps({
                "package_id": entry.program_id, "name": entry.name,
                "category": entry.category, "rpc": rpc_wss,
            })
            crystal_id = _LOG.log(
                original_prompt=f"sub_open:sui:{entry.short()}",
                enhanced_prompt=payload,
                output_text=payload,
                tier="external_chain_event",
                model="sui",
                scope=f"sub_open:{entry.category}",
                source_action="program_monitor.sui_subscriber",
            ) or ""
        except Exception as exc:
            print(f"[sui] log open failed: {exc!r}", file=sys.stderr)
            crystal_id = ""

    while not stop_event.is_set():
        try:
            reader, writer = await _ws_open(rpc_wss)
            sub_id += 1
            req = {
                "jsonrpc": "2.0",
                "id": sub_id,
                "method": "suix_subscribeEvent",
                "params": [{"Package": entry.program_id}],
            }
            await _ws_send(writer, json.dumps(req).encode())
            stats.started_at = time.time()
            if verbose:
                print(f"[sui] subscribed {entry.short()} {entry.name}",
                      file=sys.stderr)
            seen_evs: set = set()
            while not stop_event.is_set():
                try:
                    payload = await asyncio.wait_for(_ws_recv(reader), timeout=60)
                except asyncio.TimeoutError:
                    await _ws_send(writer, b"", opcode=0x09)
                    continue
                if payload is None:
                    break
                if not payload:
                    continue
                try:
                    msg = json.loads(payload.decode("utf-8", errors="replace"))
                except Exception:
                    continue
                params = msg.get("params") or {}
                result = params.get("result") or {}
                ev_id = (result.get("id") or {}).get("eventSeq", "") + ":" + \
                        (result.get("id") or {}).get("txDigest", "")
                if not ev_id or ev_id in seen_evs:
                    continue
                seen_evs.add(ev_id)
                if len(seen_evs) > 50000:
                    seen_evs = set(list(seen_evs)[-25000:])
                event = {
                    "ts": time.time(),
                    "chain": "sui",
                    "program_id": entry.program_id,
                    "program_short": entry.short(),
                    "program_name": entry.name,
                    "category": entry.category,
                    "tx_digest": (result.get("id") or {}).get("txDigest", ""),
                    "event_seq": (result.get("id") or {}).get("eventSeq", ""),
                    "type": result.get("type", ""),
                    "sender": result.get("sender", ""),
                    "action": (result.get("type", "").rsplit("::", 1) + [""])[-1],
                }
                event["dim"] = _dim_pack(event, crystal_id)
                ok = _sink(event, stats, eps_cap)
                if verbose and ok:
                    print(f"[sui:{entry.short()}] {event['action']}", file=sys.stderr)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            stats.last_error = "disconnected; reconnecting"
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stats.last_error = repr(exc)[:200]
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


# ── supervisor ──

async def supervise(entries: List[ProgramEntry],
                     solana_wss: str = SOLANA_WSS,
                     sui_wss: str = SUI_WSS,
                     eps_cap: int = DEFAULT_PER_PROGRAM_EPS_CAP,
                     duration_s: float = 0.0,
                     verbose: bool = False) -> List[SubscriberStats]:
    stop_event = asyncio.Event()
    tasks: List[asyncio.Task] = []
    stats_list: List[SubscriberStats] = []
    for e in entries:
        st = SubscriberStats(chain=e.chain, program_id=e.program_id, name=e.name)
        stats_list.append(st)
        if e.chain == "solana":
            tasks.append(asyncio.create_task(
                solana_subscriber(e, solana_wss, st, eps_cap, stop_event, verbose)))
        elif e.chain == "sui":
            tasks.append(asyncio.create_task(
                sui_subscriber(e, sui_wss, st, eps_cap, stop_event, verbose)))
    if duration_s > 0:
        try:
            await asyncio.sleep(duration_s)
        finally:
            stop_event.set()
    else:
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            stop_event.set()
            raise
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return stats_list


# ── status (read-only file walk) ──

def status() -> Dict:
    root = EVENT_ROOT
    out = {"chains": {}, "total_events": 0, "root": str(root)}
    if not root.exists():
        return out
    for chain_dir in sorted(root.iterdir()):
        if not chain_dir.is_dir():
            continue
        chain = chain_dir.name
        per_chain = {}
        for prog_dir in sorted(chain_dir.iterdir()):
            if not prog_dir.is_dir():
                continue
            count = 0
            for jf in prog_dir.glob("*.jsonl"):
                try:
                    with jf.open("rb") as f:
                        count += sum(1 for _ in f)
                except Exception:
                    pass
            per_chain[prog_dir.name] = count
            out["total_events"] += count
        out["chains"][chain] = per_chain
    return out


# ── CLI ──

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="program_monitor — multi-program WS supervisor")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="start subscribers (foreground)")
    p_start.add_argument("--chain", default="", help="limit chain (solana|sui)")
    p_start.add_argument("--cat", default="", help="limit category")
    p_start.add_argument("--solana-wss", default=SOLANA_WSS)
    p_start.add_argument("--sui-wss", default=SUI_WSS)
    p_start.add_argument("--eps-cap", type=int, default=DEFAULT_PER_PROGRAM_EPS_CAP)
    p_start.add_argument("--duration", type=float, default=0.0,
                         help="seconds (0 = run until interrupt)")
    p_start.add_argument("--verbose", action="store_true")
    p_start.add_argument("--max-programs", type=int, default=0,
                         help="cap number of subscribers (0=all watching)")

    sub.add_parser("status", help="count events on disk")
    sub.add_parser("watchset", help="show what would be subscribed")

    args = ap.parse_args(argv)

    if args.cmd == "status":
        out = status()
        print(json.dumps(out, indent=2))
        return 0

    entries = watchset()
    if args.cmd == "watchset":
        for e in entries:
            print(f"  {e.chain:6s} {e.short():12s} {e.category:20s} {e.name}")
        print(f"[monitor] {len(entries)} would be subscribed")
        return 0

    if args.chain:
        entries = [e for e in entries if e.chain == args.chain]
    if args.cat:
        entries = [e for e in entries if e.category == args.cat]
    if args.max_programs and len(entries) > args.max_programs:
        entries = entries[: args.max_programs]
    if not entries:
        print("[monitor] no watch=true entries match filters", file=sys.stderr)
        return 2
    print(f"[monitor] supervising {len(entries)} programs "
          f"(duration={args.duration}s, eps_cap={args.eps_cap})", file=sys.stderr)
    try:
        stats_list = asyncio.run(supervise(
            entries,
            solana_wss=args.solana_wss,
            sui_wss=args.sui_wss,
            eps_cap=args.eps_cap,
            duration_s=args.duration,
            verbose=args.verbose,
        ))
    except KeyboardInterrupt:
        print("[monitor] interrupted", file=sys.stderr)
        return 130
    print(json.dumps({
        "subscribers": [
            {"chain": s.chain, "short": s.short(), "name": s.name,
             "events": s.events, "last_error": s.last_error,
             "started_at": s.started_at}
            for s in stats_list
        ],
        "total_events": sum(s.events for s in stats_list),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
