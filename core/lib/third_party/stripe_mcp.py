#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        stripe_mcp
# role:        CONNECTOR · STRIPE_FIAT_RAIL
# tier:        L0
# substrate:   fiat onramp for the dApp + product subscriptions
# storage:     ~/.cc/third_party_logs/stripe_sends.jsonl
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.stripe_mcp.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/dapp/server.py /dapp/api/buy?payment_method=stripe
#   - core/cc.sh::cmd_stripe_test  /  cmd_stripe_webhook_test
#   - studio_runtime (when card pass.engine='cloud' and provider='stripe')
# outbound:
#   - https://api.stripe.com/v1/* via stdlib urllib
#   - inference_logger.log (tier='monetization', model='stripe')
# substrate touch:
#   - reads:  STRIPE_SECRET_KEY + STRIPE_WEBHOOK_SECRET from keys.load_env
#   - writes: ~/.cc/third_party_logs/stripe_sends.jsonl + studio/third_party/stripe/
# ============================================================================
"""stripe_mcp.py — Stripe REST API connector + crystal-anchored monetization log.

Mirrors third_party/blender_mcp.py shape exactly. SERVICE = "stripe".
Stdlib only — no `stripe` python SDK dep. Stripe's REST accepts form-encoded
POST bodies; we use hf_hub-style urllib helpers.

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - create_payment_intent(amount_cents, currency='usd', customer='', description='')
  - create_subscription(customer, price_id, trial_days=0)
  - customer_create(email, name='')
  - webhook_route(event_body, sig_header)   — HMAC-verify + parse
  - retrieve_payment_intent(pi_id)

Every successful call crystal-anchors via inference_logger.log(tier='monetization').
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

STRIPE_API_ROOT = "https://api.stripe.com"
EXPECTED_TOOLS = (
    "create_payment_intent",
    "create_subscription",
    "customer_create",
    "retrieve_payment_intent",
    "webhook_route",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_secret_key() -> str:
    """Resolve STRIPE_SECRET_KEY from keys.upstream_key('stripe') or env."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import upstream_key  # type: ignore
        k = upstream_key("stripe")
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("STRIPE_SECRET_KEY", "") or os.environ.get("STRIPE_API_KEY", "")


def _load_webhook_secret() -> str:
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import load_env  # type: ignore
        env = load_env()
        return env.get("STRIPE_WEBHOOK_SECRET", "")
    except Exception:
        return os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def _http_post_form(url: str, form: Dict[str, Any], headers: Dict[str, str],
                     timeout: int = 30) -> tuple[int, Dict[str, Any]]:
    body = urllib.parse.urlencode(_flatten_for_form(form)).encode("utf-8")
    hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
    hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(txt)
            except json.JSONDecodeError:
                return resp.status, {"_raw": txt[:8192]}
    except urllib.error.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
            return e.code, json.loads(body_txt) if body_txt.strip().startswith("{") else {"_error": body_txt[:2048]}
        except Exception:
            return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


def _flatten_for_form(d: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
    """Stripe expects nested dicts as bracketed form keys: foo[bar][baz]=val."""
    out: Dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten_for_form(v, key))
        elif isinstance(v, (list, tuple)):
            for i, item in enumerate(v):
                if isinstance(item, dict):
                    out.update(_flatten_for_form(item, f"{key}[{i}]"))
                else:
                    out[f"{key}[{i}]"] = str(item)
        elif v is not None:
            out[key] = str(v)
    return out


def _http_get(url: str, headers: Dict[str, str], timeout: int = 30) -> tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(txt)
            except json.JSONDecodeError:
                return resp.status, {"_raw": txt[:8192]}
    except urllib.error.HTTPError as e:
        return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_monetization(tool: str, params: Dict[str, Any], result: Dict[str, Any],
                       latency_ms: int, status_code: int) -> str:
    """Append one InferenceRecord with tier='monetization', model='stripe'.
    Returns the crystal_id (or empty string if logger unavailable)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        crystal_id = il.log(
            original_prompt=f"stripe.{tool}",
            enhanced_prompt=json.dumps({k: v for k, v in params.items()
                                         if k not in ("expand", "metadata")},
                                        separators=(",", ":"))[:512],
            output_text=json.dumps({k: v for k, v in result.items()
                                     if k in ("id", "status", "amount", "currency",
                                              "customer", "client_secret")},
                                    separators=(",", ":"))[:512],
            tier="monetization", model="stripe",
            scope=f"stripe_{tool}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"stripe.{tool}",
            done_flag=(status_code == 200),
            rc=0 if status_code == 200 else 1,
        )
        return crystal_id or ""
    except Exception as e:
        sys.stderr.write(f"warn: stripe crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------

class StripeMCPConnector(ThirdPartyConnector):
    """Stripe REST API connector. Bearer-auth via STRIPE_SECRET_KEY."""

    SERVICE = "stripe"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(service=self.SERVICE, name="stripe_default", action="payment_rail")
        super().__init__(config)
        self._secret_key = ""
        self._connected = False

    # ---- ThirdPartyConnector lifecycle ----------------------------------

    def connect(self) -> bool:
        self._secret_key = _load_secret_key()
        if not self._secret_key:
            return False
        # smoke: GET /v1/balance (free, no charge) — verifies key works
        status, _ = _http_get(
            f"{STRIPE_API_ROOT}/v1/balance",
            headers={"Authorization": f"Bearer {self._secret_key}"},
            timeout=10,
        )
        self._connected = (status == 200)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        """recipient = tool name; message = JSON args (preferred) or empty if kwargs."""
        if not self._connected and not self.connect():
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                error="stripe_not_connected (missing STRIPE_SECRET_KEY?)",
                metadata={},
            )
        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        t0 = time.time()
        if recipient == "create_payment_intent":
            status, body = self._create_payment_intent(params)
        elif recipient == "create_subscription":
            status, body = self._create_subscription(params)
        elif recipient == "customer_create":
            status, body = self._customer_create(params)
        elif recipient == "retrieve_payment_intent":
            status, body = self._retrieve_payment_intent(params)
        elif recipient == "webhook_route":
            status, body = self._webhook_route(params)
        else:
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )

        latency_ms = int((time.time() - t0) * 1000)
        crystal_id = _log_monetization(recipient, params, body, latency_ms, status)
        success = (200 <= status < 300)
        preview = body.get("id", "") or body.get("status", "") or str(body)[:200]

        return SendResult(
            success=success, service=self.SERVICE, recipient=recipient,
            message_preview=preview[:200], timestamp=time.time(),
            crystal_id=crystal_id,
            error="" if success else body.get("_error", "") or f"http_{status}",
            metadata={
                "status_code": status, "latency_ms": latency_ms,
                "stripe_id": body.get("id", ""),
                "stripe_status": body.get("status", ""),
                "amount": body.get("amount", 0),
                "currency": body.get("currency", ""),
                "client_secret": body.get("client_secret", ""),
            },
        )

    def history(self, limit: int = 20) -> list:
        log_path = Path.home() / ".cc" / "third_party_logs" / "stripe_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Tool implementations -------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._secret_key}"}

    def _create_payment_intent(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        form = {
            "amount": int(p.get("amount_cents", 0)),
            "currency": p.get("currency", "usd"),
        }
        if p.get("customer"):
            form["customer"] = p["customer"]
        if p.get("description"):
            form["description"] = p["description"]
        if p.get("metadata"):
            form["metadata"] = p["metadata"]
        if p.get("automatic_payment_methods", True):
            form["automatic_payment_methods"] = {"enabled": "true"}
        return _http_post_form(f"{STRIPE_API_ROOT}/v1/payment_intents",
                                 form, self._auth_headers())

    def _create_subscription(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        form = {
            "customer": p["customer"],
            "items": [{"price": p["price_id"]}],
        }
        if int(p.get("trial_days", 0)) > 0:
            form["trial_period_days"] = int(p["trial_days"])
        return _http_post_form(f"{STRIPE_API_ROOT}/v1/subscriptions",
                                 form, self._auth_headers())

    def _customer_create(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        form = {"email": p.get("email", "")}
        if p.get("name"):
            form["name"] = p["name"]
        return _http_post_form(f"{STRIPE_API_ROOT}/v1/customers",
                                 form, self._auth_headers())

    def _retrieve_payment_intent(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        pi_id = p.get("pi_id", "")
        if not pi_id:
            return 400, {"_error": "missing pi_id"}
        return _http_get(f"{STRIPE_API_ROOT}/v1/payment_intents/{pi_id}",
                          self._auth_headers())

    def _webhook_route(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """HMAC-verify Stripe-Signature header; return parsed event or error."""
        payload = p.get("payload", "")
        sig_header = p.get("sig_header", "")
        secret = _load_webhook_secret()
        if not secret:
            return 500, {"_error": "no STRIPE_WEBHOOK_SECRET"}
        # Stripe-Signature format: t=<ts>,v1=<sig>
        ts = ""
        sig = ""
        for part in sig_header.split(","):
            if part.startswith("t="):
                ts = part[2:]
            elif part.startswith("v1="):
                sig = part[3:]
        if not ts or not sig:
            return 400, {"_error": "bad_sig_header"}
        try:
            if abs(time.time() - int(ts)) > 300:
                return 400, {"_error": "stale_timestamp"}
        except ValueError:
            return 400, {"_error": "bad_timestamp"}
        signed = f"{ts}.{payload}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return 401, {"_error": "signature_mismatch"}
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return 400, {"_error": "bad_json"}
        return 200, event


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="stripe_mcp — Stripe connector smoke")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")
    p_pi = sub.add_parser("payment-intent")
    p_pi.add_argument("--amount-cents", type=int, default=100)
    p_pi.add_argument("--currency", default="usd")
    p_pi.add_argument("--description", default="MySpace++ smoke test")
    p_sub = sub.add_parser("subscription")
    p_sub.add_argument("--customer", required=True)
    p_sub.add_argument("--price-id", required=True)
    p_sub.add_argument("--trial-days", type=int, default=0)
    p_cust = sub.add_parser("customer-create")
    p_cust.add_argument("--email", required=True)
    p_cust.add_argument("--name", default="")
    sub.add_parser("providers", help="list expected tools")

    args = ap.parse_args()
    c = StripeMCPConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({"connected": ok}, indent=2))

    elif args.cmd == "payment-intent":
        r = c.send("create_payment_intent",
                    json.dumps({"amount_cents": args.amount_cents,
                                  "currency": args.currency,
                                  "description": args.description}))
        print(json.dumps({"success": r.success, "preview": r.message_preview,
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "stripe_id": r.metadata.get("stripe_id", ""),
                            "client_secret": r.metadata.get("client_secret", "")[:32],
                            "latency_ms": r.metadata.get("latency_ms", 0),
                            "error": r.error}, indent=2))

    elif args.cmd == "subscription":
        r = c.send("create_subscription",
                    json.dumps({"customer": args.customer,
                                  "price_id": args.price_id,
                                  "trial_days": args.trial_days}))
        print(json.dumps({"success": r.success, "preview": r.message_preview,
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "stripe_id": r.metadata.get("stripe_id", ""),
                            "error": r.error}, indent=2))

    elif args.cmd == "customer-create":
        r = c.send("customer_create", json.dumps({"email": args.email, "name": args.name}))
        print(json.dumps({"success": r.success, "stripe_id": r.metadata.get("stripe_id", ""),
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "error": r.error}, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({"expected_tools": list(EXPECTED_TOOLS)}, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
