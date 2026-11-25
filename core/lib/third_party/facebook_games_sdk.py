#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        facebook_games_sdk
# role:        CONNECTOR · FACEBOOK_GAMES_SDK_REST
# tier:        L0
# substrate:   Graph API + App Events + Instant Games surface for Meta-hosted
#              game developer flows (login token debug, analytics events,
#              leaderboards, notifications, OAuth user lookup).
# storage:     ~/.cc/third_party_logs/facebook_games_sends.jsonl + crystal chain
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.facebook_games_sdk.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/cc.sh (future: cmd_fb_games_test / cmd_fb_event)
#   - studio/dapp/server.py (future: /dapp/api/fb_event for game telemetry)
#   - studio_runtime._dispatch_cloud (when pass.provider_family='facebook_games')
# outbound:
#   - https://graph.facebook.com/<version>/oauth/access_token   (app token)
#   - https://graph.facebook.com/<version>/debug_token          (token validate)
#   - https://graph.facebook.com/<version>/<app_id>/activities  (App Events)
#   - https://graph.facebook.com/<version>/<app_id>/instant_games
#   - https://graph.facebook.com/<version>/<leaderboard>/scores
#   - https://graph.facebook.com/<version>/<app_id>/notifications
#   - https://graph.facebook.com/<version>/me                   (OAuth user)
#   - inference_logger.log (tier='social_event', model='facebook_games')
# substrate touch:
#   - reads:  FB_APP_ID + FB_APP_SECRET + FB_USER_ACCESS_TOKEN from .env
#   - reads:  FB_GRAPH_API_VERSION (default v18.0) + FB_GRAPH_API_BASE override
#   - writes: send_log entries + crystal_chain social_event records
# ============================================================================
"""facebook_games_sdk.py — Facebook Games SDK REST connector.

Mirrors third_party/stripe_mcp.py + deepseek_mcp.py shape exactly.
SERVICE = "facebook_games". Stdlib only — no `facebook-sdk` python package.

Scope: developer surface from https://developers.facebook.com/docs/games/
  - Login           → debug_token  (validate any access token)
  - App Events      → send_app_event  (purchase, achievement, level_completed)
  - Instant Games   → register_instant_game, leaderboard_get, notification_send
  - Graph (limited) → graph_get_me (user-OAuth scope), app_secret_proof_compute

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - verify_credentials()                          — read-only smoke
  - debug_token(input_token)                      — validate any token
  - send_app_event(event_name, custom_data, ...)  — analytics
  - register_instant_game(name, category, ...)    — needs Meta review
  - leaderboard_get(leaderboard_api_name, limit)  — game leaderboards
  - notification_send(recipient_id, template_name)
  - graph_get_me(user_access_token)               — OAuth identity
  - app_secret_proof_compute(user_access_token)   — local HMAC; no HTTP

Env vars (handled gracefully when absent):
  FB_APP_ID                — your Facebook App ID
  FB_APP_SECRET            — App Secret
  FB_USER_ACCESS_TOKEN     — optional, for endpoints needing user context
  FB_GRAPH_API_VERSION     — defaults to v18.0
  FB_GRAPH_API_BASE        — full base URL override

Every successful HTTP call crystal-anchors via
inference_logger.log(tier='social_event', model='facebook_games').
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
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

DEFAULT_GRAPH_VERSION = "v18.0"
DEFAULT_GRAPH_HOST = "https://graph.facebook.com"

EXPECTED_TOOLS = (
    "debug_token",
    "send_app_event",
    "register_instant_game",
    "leaderboard_get",
    "notification_send",
    "graph_get_me",
    "app_secret_proof_compute",
    "verify_credentials",
)


# ---------------------------------------------------------------------------
# .env loaders — mirror stripe_mcp / deepseek_mcp pattern
# ---------------------------------------------------------------------------

def _load_env_var(name: str) -> str:
    """Resolve a Facebook env var via studio/auth/keys.load_env, then os.environ."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import load_env  # type: ignore
        env = load_env()
        v = env.get(name) or env.get(name.lower())
        if v:
            return v
    except Exception:
        pass
    return os.environ.get(name, "") or os.environ.get(name.lower(), "")


def _load_app_id() -> str:
    return _load_env_var("FB_APP_ID")


def _load_app_secret() -> str:
    return _load_env_var("FB_APP_SECRET")


def _load_user_access_token() -> str:
    return _load_env_var("FB_USER_ACCESS_TOKEN")


def _load_graph_version() -> str:
    return _load_env_var("FB_GRAPH_API_VERSION") or DEFAULT_GRAPH_VERSION


def _load_graph_base() -> str:
    """Return the full base URL, e.g. https://graph.facebook.com/v18.0."""
    override = _load_env_var("FB_GRAPH_API_BASE")
    if override:
        return override.rstrip("/")
    return f"{DEFAULT_GRAPH_HOST}/{_load_graph_version()}"


# ---------------------------------------------------------------------------
# HTTP helpers — stdlib only
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 30) -> tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url)
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
            if body_txt.strip().startswith("{"):
                return e.code, json.loads(body_txt)
            return e.code, {"_error": body_txt[:2048]}
        except Exception:
            return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


def _http_post_form(url: str, form: Dict[str, Any],
                     timeout: int = 30) -> tuple[int, Dict[str, Any]]:
    """POST application/x-www-form-urlencoded — Facebook Graph default."""
    flat: Dict[str, str] = {}
    for k, v in form.items():
        if v is None:
            continue
        if isinstance(v, (dict, list, tuple)):
            flat[k] = json.dumps(v, separators=(",", ":"))
        else:
            flat[k] = str(v)
    body = urllib.parse.urlencode(flat).encode("utf-8")
    hdrs = {"Content-Type": "application/x-www-form-urlencoded"}
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
            if body_txt.strip().startswith("{"):
                return e.code, json.loads(body_txt)
            return e.code, {"_error": body_txt[:2048]}
        except Exception:
            return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_social_event(tool: str, params: Dict[str, Any], result: Dict[str, Any],
                       latency_ms: int, status_code: int) -> str:
    """Append one InferenceRecord with tier='social_event', model='facebook_games'.
    Returns the crystal_id (or empty string if logger unavailable)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        # Redact secrets from the preview payload
        safe_params = {
            k: v for k, v in params.items()
            if k not in ("access_token", "input_token", "user_access_token",
                          "appsecret_proof", "app_secret")
        }
        safe_result = {
            k: v for k, v in result.items()
            if k in ("id", "name", "category", "namespace", "is_valid",
                      "app_id", "application", "user_id", "email", "type",
                      "scopes", "expires_at", "data_access_expires_at",
                      "events_received", "success", "message")
        }
        crystal_id = il.log(
            original_prompt=f"facebook_games.{tool}",
            enhanced_prompt=json.dumps(safe_params, separators=(",", ":"))[:512],
            output_text=json.dumps(safe_result, separators=(",", ":"))[:512],
            tier="social_event", model="facebook_games",
            scope=f"fb_{tool}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"facebook_games.{tool}",
            done_flag=(200 <= status_code < 300),
            rc=0 if 200 <= status_code < 300 else 1,
        )
        return crystal_id or ""
    except Exception as e:
        sys.stderr.write(f"warn: facebook_games crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class FacebookGamesSDKConnector(ThirdPartyConnector):
    """Facebook Games SDK REST connector.

    Auth model: app access token (computed as <app_id>|<app_secret> or via
    /oauth/access_token grant_type=client_credentials). User-context endpoints
    require FB_USER_ACCESS_TOKEN; missing user token returns a graceful error.
    """

    SERVICE = "facebook_games"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="facebook_games_default",
                action="game_sdk",
            )
        super().__init__(config)
        self._app_id = ""
        self._app_secret = ""
        self._user_access_token = ""
        self._base_url = ""
        self._app_access_token = ""
        self._connected = False

    # ---- lifecycle ------------------------------------------------------

    def connect(self) -> bool:
        self._app_id = _load_app_id()
        self._app_secret = _load_app_secret()
        self._user_access_token = _load_user_access_token()
        self._base_url = _load_graph_base().rstrip("/")
        if not (self._app_id and self._app_secret):
            self._connected = False
            return False
        # Probe: fetch app access token via client_credentials grant. Cache it.
        url = (
            f"{self._base_url}/oauth/access_token"
            f"?client_id={urllib.parse.quote(self._app_id)}"
            f"&client_secret={urllib.parse.quote(self._app_secret)}"
            f"&grant_type=client_credentials"
        )
        status, body = _http_get(url, timeout=10)
        if status == 200 and isinstance(body, dict) and body.get("access_token"):
            self._app_access_token = body["access_token"]
            self._connected = True
            return True
        # Fallback per FB docs: app_id|app_secret string also functions as an
        # app access token for many endpoints — accept and continue.
        self._app_access_token = f"{self._app_id}|{self._app_secret}"
        self._connected = bool(self._app_access_token)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False
        self._app_access_token = ""

    # ---- dispatcher -----------------------------------------------------

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        # app_secret_proof_compute is purely local — handle BEFORE the connect gate
        # so callers can use it without keys (it still requires app_secret).
        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        if recipient == "app_secret_proof_compute":
            secret = self._app_secret or _load_app_secret()
            uat = params.get("user_access_token") or self._user_access_token
            if not secret:
                return SendResult(
                    success=False, crystal_id="", service=self.SERVICE,
                    recipient=recipient, message_preview="",
                    timestamp=time.time(),
                    error="facebook_games_keys not configured "
                          "(missing FB_APP_SECRET)",
                    metadata={"expected_tools": list(EXPECTED_TOOLS)},
                )
            if not uat:
                return SendResult(
                    success=False, crystal_id="", service=self.SERVICE,
                    recipient=recipient, message_preview="",
                    timestamp=time.time(),
                    error="missing user_access_token "
                          "(supply via param or FB_USER_ACCESS_TOKEN)",
                    metadata={},
                )
            proof = hmac.new(
                secret.encode("utf-8"),
                uat.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return SendResult(
                success=True, crystal_id="", service=self.SERVICE,
                recipient=recipient, message_preview=proof[:32],
                timestamp=time.time(),
                error="",
                metadata={"appsecret_proof": proof,
                            "user_access_token_preview": uat[:8] + "…"},
            )

        # All other tools require connect.
        if not self._connected and not self.connect():
            err = ("facebook_games_keys not configured "
                   if not (self._app_id and self._app_secret)
                   else "facebook_games_not_configured")
            return SendResult(
                success=False, crystal_id="", service=self.SERVICE,
                recipient=recipient, message_preview="",
                timestamp=time.time(),
                error=err,
                metadata={"has_app_id": bool(self._app_id),
                            "has_app_secret": bool(self._app_secret)},
            )

        t0 = time.time()
        if recipient == "verify_credentials":
            status, body = self._verify_credentials()
        elif recipient == "debug_token":
            status, body = self._debug_token(params)
        elif recipient == "send_app_event":
            status, body = self._send_app_event(params)
        elif recipient == "register_instant_game":
            status, body = self._register_instant_game(params)
        elif recipient == "leaderboard_get":
            status, body = self._leaderboard_get(params)
        elif recipient == "notification_send":
            status, body = self._notification_send(params)
        elif recipient == "graph_get_me":
            status, body = self._graph_get_me(params)
        else:
            return SendResult(
                success=False, crystal_id="", service=self.SERVICE,
                recipient=recipient, message_preview="",
                timestamp=time.time(),
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )

        latency_ms = int((time.time() - t0) * 1000)
        success = 200 <= status < 300

        # Crystal-anchor ONLY when keys are present and the call actually succeeded.
        crystal_id = ""
        if success and self._app_id and self._app_secret:
            crystal_id = _log_social_event(recipient, params, body, latency_ms, status)

        # Build a compact preview
        preview = (body.get("id", "")
                    or body.get("name", "")
                    or body.get("application", "")
                    or str(body.get("is_valid", ""))
                    or str(body)[:200])

        metadata: Dict[str, Any] = {
            "status_code": status,
            "latency_ms": latency_ms,
            "graph_version": _load_graph_version(),
            "tool": recipient,
        }
        # Surface common Facebook response fields
        for k in ("id", "name", "category", "namespace", "is_valid",
                   "app_id", "user_id", "email", "type", "scopes",
                   "expires_at", "data_access_expires_at"):
            if k in body and not isinstance(body.get(k), (dict, list)):
                metadata[k] = body[k]
        if "data" in body:
            metadata["data_count"] = (len(body["data"])
                                          if isinstance(body["data"], list) else 0)

        err = ""
        if not success:
            fb_err = body.get("error", {})
            if isinstance(fb_err, dict) and fb_err.get("message"):
                err = f"fb_error:{fb_err.get('code','')}:{fb_err.get('message','')[:200]}"
            else:
                err = body.get("_error", "") or f"http_{status}"

        return SendResult(
            success=success, crystal_id=crystal_id, service=self.SERVICE,
            recipient=recipient, message_preview=str(preview)[:200],
            timestamp=time.time(),
            error=err,
            metadata=metadata,
        )

    def history(self, limit: int = 20) -> list:
        log_path = Path.home() / ".cc" / "third_party_logs" / "facebook_games_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Tool implementations ------------------------------------------

    def _verify_credentials(self) -> tuple[int, Dict[str, Any]]:
        """Read-only smoke: fetch app token + then GET /<app_id>?fields=..."""
        if not self._app_access_token:
            return 0, {"_error": "no app_access_token after connect"}
        url = (
            f"{self._base_url}/{urllib.parse.quote(self._app_id)}"
            f"?access_token={urllib.parse.quote(self._app_access_token)}"
            f"&fields=name,namespace,category"
        )
        status, body = _http_get(url, timeout=10)
        if status == 200 and isinstance(body, dict):
            body["app_access_token"] = self._app_access_token  # private; redacted from logs
        return status, body

    def _debug_token(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        input_token = p.get("input_token") or p.get("token") or ""
        if not input_token:
            return 400, {"_error": "missing input_token"}
        url = (
            f"{self._base_url}/debug_token"
            f"?input_token={urllib.parse.quote(input_token)}"
            f"&access_token={urllib.parse.quote(self._app_access_token)}"
        )
        status, body = _http_get(url, timeout=15)
        # Unwrap Facebook's "data" envelope for convenience
        if status == 200 and isinstance(body, dict) and isinstance(body.get("data"), dict):
            merged = dict(body["data"])
            merged["_envelope"] = "data"
            return status, merged
        return status, body

    def _send_app_event(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """POST /<app_id>/activities — App Events for Mobile shape."""
        event_name = p.get("event_name") or p.get("event") or ""
        if not event_name:
            return 400, {"_error": "missing event_name"}
        custom_data = p.get("custom_data") or {}
        event_id = p.get("event_id") or ""
        # Mobile App Events expects "custom_events" as JSON-encoded list.
        evt: Dict[str, Any] = {"_eventName": event_name}
        if event_id:
            evt["_eventId"] = event_id
        for k, v in custom_data.items():
            evt[str(k)] = v
        form = {
            "event": "CUSTOM_APP_EVENTS",
            "custom_events": [evt],
            "advertiser_tracking_enabled": 0,
            "application_tracking_enabled": 0,
            "access_token": self._app_access_token,
        }
        url = f"{self._base_url}/{urllib.parse.quote(self._app_id)}/activities"
        return _http_post_form(url, form, timeout=20)

    def _register_instant_game(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """POST /<app_id>/instant_games — most apps require Meta review first.
        4xx here is documented as 'needs Meta review' rather than a wiring bug."""
        name = p.get("name") or ""
        category = p.get("category") or ""
        namespace = p.get("namespace") or ""
        asset_urls = p.get("asset_urls") or []
        if not (name and namespace):
            return 400, {"_error": "missing name or namespace"}
        form = {
            "name": name,
            "category": category,
            "namespace": namespace,
            "asset_urls": asset_urls,
            "access_token": self._app_access_token,
        }
        url = f"{self._base_url}/{urllib.parse.quote(self._app_id)}/instant_games"
        return _http_post_form(url, form, timeout=20)

    def _leaderboard_get(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        lb = p.get("leaderboard_api_name") or p.get("leaderboard") or ""
        limit = int(p.get("limit", 10))
        if not lb:
            return 400, {"_error": "missing leaderboard_api_name"}
        url = (
            f"{self._base_url}/{urllib.parse.quote(lb)}/scores"
            f"?limit={limit}"
            f"&access_token={urllib.parse.quote(self._app_access_token)}"
        )
        return _http_get(url, timeout=15)

    def _notification_send(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        recipient_id = p.get("recipient_id") or p.get("recipient") or ""
        template = p.get("template_name") or p.get("template") or ""
        if not (recipient_id and template):
            return 400, {"_error": "missing recipient_id or template_name"}
        form = {
            "recipient": recipient_id,
            "template": template,
            "access_token": self._app_access_token,
        }
        url = f"{self._base_url}/{urllib.parse.quote(self._app_id)}/notifications"
        return _http_post_form(url, form, timeout=15)

    def _graph_get_me(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """GET /me?access_token=<user_token>&fields=id,name,email
        Auto-attaches appsecret_proof if user token + app secret available."""
        uat = (p.get("user_access_token")
                or p.get("access_token")
                or self._user_access_token)
        if not uat:
            return 400, {"_error": "missing user_access_token"}
        fields = p.get("fields") or "id,name,email"
        url = (
            f"{self._base_url}/me"
            f"?access_token={urllib.parse.quote(uat)}"
            f"&fields={urllib.parse.quote(fields)}"
        )
        if self._app_secret:
            proof = hmac.new(
                self._app_secret.encode("utf-8"),
                uat.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            url += f"&appsecret_proof={urllib.parse.quote(proof)}"
        return _http_get(url, timeout=15)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="facebook_games_sdk — Facebook Games SDK connector")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")
    sub.add_parser("verify", help="fetch app info via app token")
    p_dbg = sub.add_parser("debug-token", help="validate any access token")
    p_dbg.add_argument("input_token")
    p_evt = sub.add_parser("event", help="send an App Event")
    p_evt.add_argument("event_name")
    p_evt.add_argument("--custom-data", default="{}",
                          help="JSON-encoded dict of event params")
    p_evt.add_argument("--event-id", default="")
    p_lb = sub.add_parser("leaderboard", help="fetch leaderboard scores")
    p_lb.add_argument("leaderboard_api_name")
    p_lb.add_argument("--limit", type=int, default=10)
    p_me = sub.add_parser("me", help="GET /me with a user token")
    p_me.add_argument("--user-token", default="")
    p_pf = sub.add_parser("appsecret-proof", help="compute appsecret_proof locally")
    p_pf.add_argument("--user-token", default="")
    sub.add_parser("providers", help="list expected tools + env vars")

    args = ap.parse_args()
    c = FacebookGamesSDKConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({
            "connected": ok,
            "base_url": c._base_url,
            "has_app_id": bool(c._app_id),
            "has_app_secret": bool(c._app_secret),
            "has_user_token": bool(c._user_access_token),
            "graph_version": _load_graph_version(),
        }, indent=2))

    elif args.cmd == "verify":
        r = c.send("verify_credentials", "")
        print(json.dumps({"success": r.success,
                            "preview": r.message_preview,
                            "metadata": {k: v for k, v in r.metadata.items()
                                          if k != "app_access_token"},
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "error": r.error}, indent=2))

    elif args.cmd == "debug-token":
        r = c.send("debug_token", json.dumps({"input_token": args.input_token}))
        print(json.dumps({"success": r.success,
                            "metadata": r.metadata,
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "error": r.error}, indent=2))

    elif args.cmd == "event":
        try:
            cd = json.loads(args.custom_data)
        except json.JSONDecodeError:
            cd = {}
        r = c.send("send_app_event", json.dumps({
            "event_name": args.event_name,
            "custom_data": cd,
            "event_id": args.event_id,
        }))
        print(json.dumps({"success": r.success,
                            "metadata": r.metadata,
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "error": r.error}, indent=2))

    elif args.cmd == "leaderboard":
        r = c.send("leaderboard_get", json.dumps({
            "leaderboard_api_name": args.leaderboard_api_name,
            "limit": args.limit,
        }))
        print(json.dumps({"success": r.success,
                            "metadata": r.metadata,
                            "preview": r.message_preview,
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "error": r.error}, indent=2))

    elif args.cmd == "me":
        uat = args.user_token or _load_user_access_token()
        r = c.send("graph_get_me", json.dumps({"user_access_token": uat}))
        print(json.dumps({"success": r.success,
                            "metadata": r.metadata,
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "error": r.error}, indent=2))

    elif args.cmd == "appsecret-proof":
        uat = args.user_token or _load_user_access_token()
        r = c.send("app_secret_proof_compute",
                    json.dumps({"user_access_token": uat}))
        print(json.dumps({"success": r.success,
                            "proof_preview": r.message_preview,
                            "error": r.error}, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "env_vars": ["FB_APP_ID", "FB_APP_SECRET", "FB_USER_ACCESS_TOKEN",
                          "FB_GRAPH_API_VERSION", "FB_GRAPH_API_BASE"],
            "default_graph_version": DEFAULT_GRAPH_VERSION,
            "default_graph_host": DEFAULT_GRAPH_HOST,
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
