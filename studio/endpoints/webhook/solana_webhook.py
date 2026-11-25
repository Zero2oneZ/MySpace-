"""solana_webhook.py — HTTP receiver for chain-event webhooks → image/video.

Listens on port 8524 (env override MSPC_SOLANA_WEBHOOK_PORT). Accepts:

    POST /webhook/solana       — generic Helius/Triton/QuickNode body
    POST /webhook/solana/raw   — bypass normalization; treat body as ChainEvent
    GET  /webhook/solana       — health probe

Each accepted event is normalized to the ChainEvent shape that
core/lib/chain_event_render.render_one() expects, then dispatched.

HMAC verification: if HELIUS_WEBHOOK_SECRET (or MSPC_WEBHOOK_SECRET) is set,
we verify the X-Helius-Signature header — Helius uses HMAC-SHA256 over the
raw body. Replay window: 5 minutes (configurable via MSPC_WEBHOOK_REPLAY_S).
If no secret is set, the receiver accepts unsigned requests but warns on
each one — that's fine for local-only testing, not for production.

Why this is separate from `program_monitor` (which already tails Solana via
WebSocket): the WS path is PULL, this is PUSH. Tom can either:
  (a) run program_monitor + chain_event_render tail mode locally (zero-cost,
      no external dep), or
  (b) configure a Helius webhook → 8524 → render (works behind a tunnel /
      Caddy on the droplet; lower local CPU, paid plan above the free tier).
Both paths converge at render_one().
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "core" / "lib"))

try:
    from chain_event_render import (
        RenderRequest, render_one, derive_prompt,
    )
except Exception as exc:
    print(f"[webhook] chain_event_render import failed: {exc}", file=sys.stderr)
    raise

try:
    from inference_logger import InferenceLogger
    _LOG = InferenceLogger()
except Exception:
    _LOG = None

DEFAULT_PORT = int(os.environ.get("MSPC_SOLANA_WEBHOOK_PORT", "8524"))
DEFAULT_SECRET = (
    os.environ.get("HELIUS_WEBHOOK_SECRET")
    or os.environ.get("MSPC_WEBHOOK_SECRET")
    or ""
)
REPLAY_WINDOW_S = int(os.environ.get("MSPC_WEBHOOK_REPLAY_S", "300"))
MAX_BODY_BYTES = 1_048_576  # 1MB per webhook body — anything bigger is suspect

EVENT_LOG = Path(os.path.expanduser("~/.cc/solana_webhook_events.jsonl"))


# ── normalization ──

def _classify_helius_tx(tx: Dict) -> str:
    """Very cheap heuristic on Helius enhanced-transaction.type."""
    t = str(tx.get("type", "")).upper()
    if t in ("SWAP", "TOKEN_MINT"):
        return "buy" if t == "SWAP" else "create"
    if t == "NFT_SALE":
        return "buy"
    if t == "NFT_LISTING":
        return "order_place"
    if t == "NFT_CANCEL_LISTING":
        return "order_cancel"
    if t == "STAKE_SOL":
        return "deposit"
    if t == "BURN":
        return "burn"
    return t.lower() or "other"


def _category_from_program(program_id: str) -> str:
    """Match against the registry if importable; fallback UNKNOWN."""
    try:
        sys.path.insert(0, str(REPO / "core" / "lib"))
        from program_registry import find  # type: ignore
        hits = find(chain="solana", program_id=program_id)
        if hits:
            return hits[0].category
    except Exception:
        pass
    return "UNKNOWN"


def normalize_event(body: Dict) -> List[Dict[str, Any]]:
    """Convert any of the common webhook shapes to a list of ChainEvent dicts.

    Supported shapes:
      - Helius enhanced webhook: top-level list of {type, signature,
        accountData[], nativeTransfers[], tokenTransfers[], slot, timestamp,
        events: {...}}
      - Helius raw webhook: top-level list of {signature, logMessages[],
        slot, blockTime}
      - Custom: a single object already in ChainEvent shape (pass-through).
    """
    items = body if isinstance(body, list) else [body]
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # Already-normalized custom event (has program_id + action keys)
        if "program_id" in item and "action" in item:
            out.append(item)
            continue
        # Helius enhanced
        if "type" in item and "signature" in item:
            program_id = ""
            # Helius enhanced exposes top-level "source" but not the program ID
            # of the involved program. Pull from accountData if available.
            for ad in item.get("accountData", []) or []:
                if ad.get("account", "").endswith("Pump") or False:
                    program_id = ad.get("account", "")
            event = {
                "ts": float(item.get("timestamp") or time.time()),
                "chain": "solana",
                "program_id": program_id,
                "program_short": program_id[:8] if program_id else "",
                "program_name": item.get("source", "") or item.get("type", ""),
                "category": _category_from_program(program_id) if program_id else item.get("type", "UNKNOWN").upper(),
                "slot": item.get("slot", 0),
                "signature": item.get("signature", ""),
                "action": _classify_helius_tx(item),
                "log_count": len(item.get("instructions", []) or []),
                "err": item.get("transactionError") is not None,
                "source": "helius_enhanced",
            }
            out.append(event)
            continue
        # Helius raw
        if "signature" in item and "logMessages" in item:
            logs = item.get("logMessages") or []
            text = "\n".join(logs)
            action = "other"
            if "Instruction: Create" in text:
                action = "create"
            elif "Instruction: Buy" in text or "Instruction: Swap" in text:
                action = "buy"
            elif "Instruction: Sell" in text:
                action = "sell"
            event = {
                "ts": float(item.get("blockTime") or time.time()),
                "chain": "solana",
                "program_id": "",
                "program_short": "",
                "program_name": "(raw)",
                "category": "UNKNOWN",
                "slot": item.get("slot", 0),
                "signature": item.get("signature", ""),
                "action": action,
                "log_count": len(logs),
                "err": item.get("err") is not None,
                "source": "helius_raw",
            }
            out.append(event)
            continue
        # Anything else: pass through with minimal coercion
        out.append({"raw": item, "ts": time.time(), "source": "unknown"})
    return out


# ── HMAC verify (Helius shape) ──

def verify_signature(body_bytes: bytes, header_sig: str, secret: str) -> Tuple[bool, str]:
    if not secret:
        return True, "no-secret-set (warning)"
    if not header_sig:
        return False, "missing-signature-header"
    expected = hmac.new(secret.encode(), body_bytes,
                         hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header_sig.strip()):
        return False, "bad-signature"
    return True, "ok"


def verify_timestamp(ts_header: str) -> Tuple[bool, str]:
    if not ts_header:
        return True, "no-timestamp-header (warning)"
    try:
        ts = float(ts_header)
    except Exception:
        return False, f"bad-timestamp:{ts_header[:32]}"
    now = time.time()
    skew = abs(now - ts)
    if skew > REPLAY_WINDOW_S:
        return False, f"timestamp-out-of-window skew={skew:.1f}s"
    return True, "ok"


# ── HTTP handler ──

class WebhookHandler(BaseHTTPRequestHandler):
    server_version = "MspcSolanaWebhook/0.1"
    secret: str = DEFAULT_SECRET
    render_image: bool = True
    render_video: bool = False
    on_event: Optional[Callable[[Dict], None]] = None

    def log_message(self, format: str, *args) -> None:
        # Quieter than default; print to stderr.
        sys.stderr.write(f"[wh] {self.address_string()} - {format % args}\n")

    def _reply(self, status: int, body: Dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/webhook/solana"):
            self._reply(200, {
                "ok": True, "service": "mspc-solana-webhook",
                "render_image": WebhookHandler.render_image,
                "render_video": WebhookHandler.render_video,
                "secret_set": bool(WebhookHandler.secret),
                "replay_window_s": REPLAY_WINDOW_S,
                "port": DEFAULT_PORT,
            })
        else:
            self._reply(404, {"error": "not-found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/webhook/solana"):
            self._reply(404, {"error": "not-found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            self._reply(400, {"error": "empty-body"})
            return
        if length > MAX_BODY_BYTES:
            self._reply(413, {"error": "body-too-large", "max": MAX_BODY_BYTES})
            return
        body_bytes = self.rfile.read(length)
        sig = (self.headers.get("X-Helius-Signature")
                or self.headers.get("X-Webhook-Signature")
                or "")
        ts_header = (self.headers.get("X-Helius-Timestamp")
                      or self.headers.get("X-Webhook-Timestamp")
                      or "")
        sig_ok, sig_reason = verify_signature(body_bytes, sig,
                                                WebhookHandler.secret)
        if not sig_ok:
            self._reply(401, {"error": "auth", "detail": sig_reason})
            return
        ts_ok, ts_reason = verify_timestamp(ts_header)
        if not ts_ok:
            self._reply(401, {"error": "replay", "detail": ts_reason})
            return
        try:
            body = json.loads(body_bytes.decode("utf-8", errors="replace"))
        except Exception as exc:
            self._reply(400, {"error": "bad-json", "detail": repr(exc)[:200]})
            return
        # Bypass normalization on /raw
        if self.path.endswith("/raw"):
            events = body if isinstance(body, list) else [body]
        else:
            events = normalize_event(body)
        EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_LOG.open("a") as f:
            for ev in events:
                f.write(json.dumps({"received_at": time.time(),
                                     "event": ev}, default=str) + "\n")
        results = []
        for ev in events:
            req = RenderRequest(
                event=ev,
                want_image=WebhookHandler.render_image,
                want_video=WebhookHandler.render_video,
            )
            try:
                r = render_one(req)
                results.append({"crystal_short": r.crystal_short,
                                  "image_status": r.image_status,
                                  "video_status": r.video_status,
                                  "prompt": r.prompt[:120]})
            except Exception as exc:
                results.append({"error": repr(exc)[:200]})
        if _LOG is not None:
            try:
                _LOG.log(
                    original_prompt=f"solana_webhook:{self.path}",
                    enhanced_prompt=json.dumps({"n_events": len(events),
                                                  "results": results}),
                    output_text=f"rendered {len(results)}",
                    tier="webhook_event",
                    model="solana_webhook",
                    scope=f"{self.path}",
                    source_action="solana_webhook.do_POST",
                )
            except Exception:
                pass
        self._reply(200, {"ok": True, "accepted": len(events),
                            "rendered": results,
                            "sig": sig_reason, "ts": ts_reason})


# ── server entry ──

def serve(port: int = DEFAULT_PORT, secret: str = DEFAULT_SECRET,
           render_image: bool = True, render_video: bool = False) -> None:
    WebhookHandler.secret = secret
    WebhookHandler.render_image = render_image
    WebhookHandler.render_video = render_video
    srv = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
    msg = (f"[wh] serving on :{port} "
           f"secret={'set' if secret else 'UNSET (insecure!)'} "
           f"image={render_image} video={render_video}")
    print(msg, file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


# ── CLI ──

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="MySpace++ Solana webhook receiver")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run the HTTP receiver")
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_serve.add_argument("--secret", default=DEFAULT_SECRET,
                          help="HMAC secret (default: env HELIUS_WEBHOOK_SECRET)")
    p_serve.add_argument("--no-image", dest="image", action="store_false")
    p_serve.add_argument("--video", action="store_true", default=False)
    p_serve.set_defaults(image=True)

    p_test = sub.add_parser("test", help="self-call the receiver with a fake event")
    p_test.add_argument("--url", default=f"http://127.0.0.1:{DEFAULT_PORT}/webhook/solana/raw")
    p_test.add_argument("--secret", default=DEFAULT_SECRET)

    args = ap.parse_args(argv)

    if args.cmd == "serve":
        serve(port=args.port, secret=args.secret,
               render_image=args.image, render_video=args.video)
        return 0

    if args.cmd == "test":
        import urllib.request
        sample = {
            "ts": time.time(), "chain": "solana",
            "program_id": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
            "program_short": "6EF8rr..wF6P",
            "program_name": "Pump.fun bonding curve",
            "category": "MEMECOIN_LAUNCHPAD",
            "action": "create",
            "signature": "TESTwebhook" * 6,
            "log_count": 12, "err": False,
        }
        body_bytes = json.dumps(sample).encode()
        ts_str = str(int(time.time()))
        headers = {"Content-Type": "application/json",
                    "X-Helius-Timestamp": ts_str}
        if args.secret:
            sig = hmac.new(args.secret.encode(), body_bytes,
                            hashlib.sha256).hexdigest()
            headers["X-Helius-Signature"] = sig
        req = urllib.request.Request(args.url, data=body_bytes,
                                      headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                print(r.read().decode())
            return 0
        except urllib.error.HTTPError as exc:  # type: ignore
            print(f"HTTP {exc.code}: {exc.read().decode()[:400]}")
            return 1
        except Exception as exc:
            print(f"error: {exc!r}")
            return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
