#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        snap_kit
# role:        CONNECTOR · SNAPCHAT_SNAP_KIT (Login + Bitmoji + Creative)
# tier:        L0
# substrate:   Snapchat consumer-graph onramp — friend login, avatar fetch,
#              Creative Kit deeplink share for stickers / captions / media.
# storage:     ~/.cc/third_party_logs/snap_kit_sends.jsonl + crystal chain
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.snap_kit.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/dapp/server.py (future: /dapp/api/snap/login + /snap/share)
#   - core/cc.sh (future: cmd_snap_test / cmd_snap_login_url)
#   - studio_runtime._dispatch_cloud (when pass.provider_family='snap_kit')
# outbound:
#   - https://accounts.snapchat.com/accounts/oauth2/auth     (consent URL)
#   - https://accounts.snapchat.com/accounts/oauth2/token    (code exchange)
#   - https://kit.snapchat.com/v1/me                          (profile + bitmoji)
#   - https://api.bitmoji.com/avatar/json                     (avatar render)
#   - inference_logger.log (tier='social_event', model='snap_kit')
# substrate touch:
#   - reads:  SNAP_CLIENT_ID + SNAP_CLIENT_SECRET via studio/auth/keys.load_env
#   - writes: send_log entries + crystal-anchored social_event records
# ============================================================================
"""snap_kit.py — Snapchat Snap Kit connector (Login + Bitmoji + Creative).

Mirrors third_party/stripe_mcp.py + deepseek_mcp.py shape exactly.
SERVICE = "snap_kit". Stdlib only — no `snapchat-py` dep. Form-encoded POST
for token exchange (basic auth), JSON GET for /v1/me, local URL building
for the OAuth consent URL and Creative Kit deeplink.

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - login_oauth2_url(redirect_uri, state, scopes=[...])
  - exchange_code(code, redirect_uri)
  - refresh_token(refresh_token)
  - me(access_token)
  - bitmoji_avatar_url(external_id)
  - creative_share_url(sticker_id, caption, attachment_url)
  - verify_credentials()

Graceful: missing SNAP_CLIENT_ID/SNAP_CLIENT_SECRET → connect() returns False
and network-touching tools return SendResult(success=False,
error='snap_kit_keys not configured') WITHOUT making any urllib request.
The local URL builders (login_oauth2_url, bitmoji_avatar_url,
creative_share_url) still work without keys — they're pure string assembly.
verify_credentials() is a no-network smoke that reports keys_present.

Every successful network call crystal-anchors via
inference_logger.log(tier='social_event', model='snap_kit',
                       scope=f'snap_<tool>').
"""
from __future__ import annotations

import base64
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

EXPECTED_TOOLS = (
    "login_oauth2_url",
    "exchange_code",
    "refresh_token",
    "me",
    "bitmoji_avatar_url",
    "creative_share_url",
    "verify_credentials",
)

# Snap Kit endpoints
SNAP_OAUTH_AUTH_URL  = "https://accounts.snapchat.com/accounts/oauth2/auth"
SNAP_OAUTH_TOKEN_URL = "https://accounts.snapchat.com/accounts/oauth2/token"
SNAP_KIT_ME_URL      = "https://kit.snapchat.com/v1/me"
BITMOJI_AVATAR_URL   = "https://api.bitmoji.com/avatar/json"
BITMOJI_CDN_TEMPLATE = "https://images.bitmoji.com/3d/avatar/{external_id}-v1.webp"

# Creative Kit share is client-side deeplink (no server endpoint)
CREATIVE_KIT_SCHEME  = "snapchat://creativekit/share"

DEFAULT_SCOPES = ["user.display_name", "user.bitmoji.avatar"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_client_id() -> str:
    """Resolve SNAP_CLIENT_ID from .env via keys.load_env or os.environ."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import load_env  # type: ignore
        env = load_env()
        v = env.get("SNAP_CLIENT_ID") or env.get("snap_client_id")
        if v:
            return v
    except Exception:
        pass
    return (os.environ.get("SNAP_CLIENT_ID", "")
            or os.environ.get("SNAPCHAT_CLIENT_ID", ""))


def _load_client_secret() -> str:
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import load_env  # type: ignore
        env = load_env()
        v = env.get("SNAP_CLIENT_SECRET") or env.get("snap_client_secret")
        if v:
            return v
    except Exception:
        pass
    return (os.environ.get("SNAP_CLIENT_SECRET", "")
            or os.environ.get("SNAPCHAT_CLIENT_SECRET", ""))


def _http_post_form(url: str, form: Dict[str, Any], headers: Dict[str, str],
                     timeout: int = 30) -> tuple[int, Dict[str, Any]]:
    body = urllib.parse.urlencode({k: str(v) for k, v in form.items()
                                      if v is not None}).encode("utf-8")
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
            if body_txt.strip().startswith("{"):
                return e.code, json.loads(body_txt)
            return e.code, {"_error": body_txt[:2048]}
        except Exception:
            return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


def _http_get(url: str, headers: Dict[str, str],
                timeout: int = 30) -> tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers)
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


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

_REDACT_KEYS = {
    "access_token", "refresh_token", "code", "client_secret",
    "id_token", "authorization",
}


def _redact(d: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if k in _REDACT_KEYS:
            out[k] = "<redacted>"
        elif isinstance(v, dict):
            out[k] = _redact(v)
        else:
            out[k] = v
    return out


def _log_social_event(tool: str, params: Dict[str, Any],
                       result: Dict[str, Any], latency_ms: int,
                       status_code: int) -> str:
    """Append one InferenceRecord with tier='social_event', model='snap_kit'.
    Returns crystal_id (or empty if logger unavailable)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        crystal_id = il.log(
            original_prompt=f"snap_kit.{tool}",
            enhanced_prompt=json.dumps(_redact(params),
                                         separators=(",", ":"))[:512],
            output_text=json.dumps(_redact({
                k: v for k, v in result.items()
                if k in ("external_id", "display_name", "bitmoji",
                          "token_type", "expires_in", "scope",
                          "share_url", "avatar_url")
            }), separators=(",", ":"))[:512],
            tier="social_event", model="snap_kit",
            scope=f"snap_{tool}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"snap_kit.{tool}",
            done_flag=(200 <= status_code < 300),
            rc=0 if (200 <= status_code < 300) else 1,
        )
        return crystal_id or ""
    except Exception as e:
        sys.stderr.write(f"warn: snap_kit crystal log failed: "
                         f"{type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------

class SnapKitConnector(ThirdPartyConnector):
    """Snapchat Snap Kit REST + deeplink builder connector.

    OAuth 2.0 confidential client: Basic-auth client_id:client_secret on
    token endpoint, bearer access_token on /v1/me. Bitmoji + Creative Kit
    surfaces are URL-only builders, no auth needed for the deeplink itself.
    """

    SERVICE = "snap_kit"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE, name="snap_kit_default",
                action="social_graph",
            )
        super().__init__(config)
        self._client_id = ""
        self._client_secret = ""
        self._connected = False

    # ---- ThirdPartyConnector lifecycle ----------------------------------

    def connect(self) -> bool:
        """Load keys. We don't hit the network here — Snap Kit's token endpoint
        rejects unauthenticated probes, and there's no equivalent of /balance.
        Successful connect just means both client_id + client_secret exist."""
        self._client_id = _load_client_id()
        self._client_secret = _load_client_secret()
        self._connected = bool(self._client_id and self._client_secret)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        # Parse params upfront so local-builder tools work even without keys
        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        # --- Local-only tools (no network, no key requirement) -----------
        if recipient == "verify_credentials":
            return self._do_verify_credentials()
        if recipient == "login_oauth2_url":
            return self._do_login_oauth2_url(params)
        if recipient == "bitmoji_avatar_url":
            return self._do_bitmoji_avatar_url(params)
        if recipient == "creative_share_url":
            return self._do_creative_share_url(params)

        # --- Network tools — require keys --------------------------------
        if not self._connected and not self.connect():
            return SendResult(
                success=False, crystal_id="", service=self.SERVICE,
                recipient=recipient, message_preview="",
                timestamp=time.time(),
                error=("snap_kit_keys not configured "
                       "(missing SNAP_CLIENT_ID / SNAP_CLIENT_SECRET)"),
                metadata={
                    "expected_tools": list(EXPECTED_TOOLS),
                    "has_client_id":     bool(self._client_id),
                    "has_client_secret": bool(self._client_secret),
                },
            )

        t0 = time.time()
        if recipient == "exchange_code":
            status, body = self._exchange_code(params)
        elif recipient == "refresh_token":
            status, body = self._refresh_token(params)
        elif recipient == "me":
            status, body = self._me(params)
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

        crystal_id = ""
        if success:
            crystal_id = _log_social_event(recipient, params, body,
                                              latency_ms, status)

        # Build preview without leaking secrets
        preview = ""
        if recipient == "me":
            preview = (body.get("display_name", "")
                       or body.get("external_id", "")
                       or str(body)[:200])
        elif recipient in ("exchange_code", "refresh_token"):
            # Don't preview the access_token itself
            preview = (f"token_type={body.get('token_type','')} "
                       f"expires_in={body.get('expires_in','')}")
        else:
            preview = str(body)[:200]

        metadata: Dict[str, Any] = {
            "status_code": status,
            "latency_ms": latency_ms,
            "tool": recipient,
        }
        # Surface useful non-secret fields
        for k in ("external_id", "display_name", "token_type",
                   "expires_in", "scope"):
            if k in body and not isinstance(body.get(k), (dict, list)):
                metadata[k] = body[k]
        # Bitmoji avatar field on /v1/me has shape {"avatar": "<url>"}
        if isinstance(body.get("bitmoji"), dict):
            metadata["bitmoji_avatar"] = body["bitmoji"].get("avatar", "")

        err = ""
        if not success:
            snap_err = body.get("error", "") or body.get("error_description", "")
            if snap_err:
                err = f"snap_error:{snap_err}"
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
        log_path = (Path.home() / ".cc" / "third_party_logs"
                    / "snap_kit_sends.jsonl")
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Tool implementations ----------------------------------------

    # Local-only (no network) -----------------------------------------

    def _do_verify_credentials(self) -> SendResult:
        """Network-free smoke: report whether SNAP_CLIENT_ID + SECRET are set."""
        cid = _load_client_id()
        sec = _load_client_secret()
        keys_present = bool(cid and sec)
        success = True  # the smoke itself always succeeds; key state is metadata
        msg = ("keys_present" if keys_present
               else "missing SNAP_CLIENT_ID / SNAP_CLIENT_SECRET")
        return SendResult(
            success=success, crystal_id="", service=self.SERVICE,
            recipient="verify_credentials", message_preview=msg,
            timestamp=time.time(),
            error="" if keys_present else (
                "snap_kit_keys not configured "
                "(missing SNAP_CLIENT_ID / SNAP_CLIENT_SECRET) — "
                "this is a no-network smoke; configure .env to enable network tools"
            ),
            metadata={
                "keys_present":      keys_present,
                "has_client_id":     bool(cid),
                "has_client_secret": bool(sec),
                "expected_tools":    list(EXPECTED_TOOLS),
                "oauth_auth_url":    SNAP_OAUTH_AUTH_URL,
                "oauth_token_url":   SNAP_OAUTH_TOKEN_URL,
                "me_url":            SNAP_KIT_ME_URL,
                "tool":              "verify_credentials",
                "no_network":        True,
            },
        )

    def _do_login_oauth2_url(self, p: Dict[str, Any]) -> SendResult:
        """Build the Snap Kit OAuth2 consent URL. No network."""
        redirect_uri = p.get("redirect_uri") or ""
        state = p.get("state") or ""
        scopes = p.get("scopes") or DEFAULT_SCOPES
        if not redirect_uri:
            return SendResult(
                success=False, crystal_id="", service=self.SERVICE,
                recipient="login_oauth2_url", message_preview="",
                timestamp=time.time(),
                error="missing redirect_uri",
                metadata={"required_params": ["redirect_uri", "state"]},
            )
        if not state:
            return SendResult(
                success=False, crystal_id="", service=self.SERVICE,
                recipient="login_oauth2_url", message_preview="",
                timestamp=time.time(),
                error="missing state (CSRF nonce required)",
                metadata={"required_params": ["redirect_uri", "state"]},
            )
        cid = _load_client_id()  # may be empty — URL still builds (caller can preview)
        scope_str = " ".join(scopes) if isinstance(scopes, list) else str(scopes)
        query = urllib.parse.urlencode({
            "response_type": "code",
            "client_id":     cid or "<SNAP_CLIENT_ID>",
            "redirect_uri":  redirect_uri,
            "scope":         scope_str,
            "state":         state,
        })
        url = f"{SNAP_OAUTH_AUTH_URL}?{query}"
        return SendResult(
            success=True, crystal_id="", service=self.SERVICE,
            recipient="login_oauth2_url", message_preview=url[:200],
            timestamp=time.time(),
            error="" if cid else (
                "warning: SNAP_CLIENT_ID not configured — placeholder embedded"
            ),
            metadata={
                "oauth2_url":  url,
                "scopes":      list(scopes) if isinstance(scopes, list) else [scope_str],
                "state":       state,
                "has_client_id": bool(cid),
                "no_network":  True,
                "tool":        "login_oauth2_url",
            },
        )

    def _do_bitmoji_avatar_url(self, p: Dict[str, Any]) -> SendResult:
        """Build the CDN URL for a Bitmoji 2D/3D avatar render. No network."""
        ext_id = p.get("external_id") or p.get("id") or ""
        if not ext_id:
            return SendResult(
                success=False, crystal_id="", service=self.SERVICE,
                recipient="bitmoji_avatar_url", message_preview="",
                timestamp=time.time(),
                error="missing external_id",
                metadata={"required_params": ["external_id"]},
            )
        safe_ext = urllib.parse.quote(str(ext_id), safe="")
        url = BITMOJI_CDN_TEMPLATE.format(external_id=safe_ext)
        return SendResult(
            success=True, crystal_id="", service=self.SERVICE,
            recipient="bitmoji_avatar_url", message_preview=url[:200],
            timestamp=time.time(),
            error="",
            metadata={
                "avatar_url":      url,
                "external_id":     str(ext_id),
                "bitmoji_api_url": BITMOJI_AVATAR_URL,
                "no_network":      True,
                "tool":            "bitmoji_avatar_url",
            },
        )

    def _do_creative_share_url(self, p: Dict[str, Any]) -> SendResult:
        """Build a snapchat://creativekit/share deeplink the caller passes to
        a client (web/mobile) to open Snapchat's camera with the attachment.
        No network."""
        sticker_id = p.get("sticker_id") or ""
        caption = p.get("caption") or ""
        attachment_url = p.get("attachment_url") or ""
        if not (sticker_id or caption or attachment_url):
            return SendResult(
                success=False, crystal_id="", service=self.SERVICE,
                recipient="creative_share_url", message_preview="",
                timestamp=time.time(),
                error=("need at least one of: sticker_id, caption, "
                       "attachment_url"),
                metadata={"required_params":
                          ["sticker_id_or_caption_or_attachment_url"]},
            )
        query_dict: Dict[str, str] = {}
        if sticker_id:
            query_dict["sticker_id"] = str(sticker_id)
        if caption:
            query_dict["caption"] = str(caption)
        if attachment_url:
            query_dict["attachment_url"] = str(attachment_url)
        query = urllib.parse.urlencode(query_dict)
        url = f"{CREATIVE_KIT_SCHEME}?{query}"
        return SendResult(
            success=True, crystal_id="", service=self.SERVICE,
            recipient="creative_share_url", message_preview=url[:200],
            timestamp=time.time(),
            error="",
            metadata={
                "share_url":      url,
                "deeplink":       url,
                "sticker_id":     sticker_id,
                "caption":        caption,
                "attachment_url": attachment_url,
                "no_network":     True,
                "tool":           "creative_share_url",
            },
        )

    # Network-touching --------------------------------------------------

    def _exchange_code(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """POST /accounts/oauth2/token with grant_type=authorization_code."""
        code = p.get("code") or ""
        redirect_uri = p.get("redirect_uri") or ""
        if not (code and redirect_uri):
            return 400, {"_error": "missing code or redirect_uri"}
        form = {
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": redirect_uri,
        }
        headers = {"Authorization":
                   _basic_auth_header(self._client_id, self._client_secret)}
        return _http_post_form(SNAP_OAUTH_TOKEN_URL, form, headers, timeout=20)

    def _refresh_token(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """POST /accounts/oauth2/token with grant_type=refresh_token."""
        refresh = p.get("refresh_token") or p.get("refresh") or ""
        if not refresh:
            return 400, {"_error": "missing refresh_token"}
        form = {
            "grant_type":    "refresh_token",
            "refresh_token": refresh,
        }
        headers = {"Authorization":
                   _basic_auth_header(self._client_id, self._client_secret)}
        return _http_post_form(SNAP_OAUTH_TOKEN_URL, form, headers, timeout=20)

    def _me(self, p: Dict[str, Any]) -> tuple[int, Dict[str, Any]]:
        """GET /v1/me with bearer access_token. Returns display_name +
        bitmoji.avatar + external_id."""
        access_token = p.get("access_token") or ""
        if not access_token:
            return 400, {"_error": "missing access_token"}
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept":        "application/json",
        }
        return _http_get(SNAP_KIT_ME_URL, headers, timeout=20)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="snap_kit — Snapchat Snap Kit connector smoke")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")
    sub.add_parser("verify", help="no-network credential smoke")

    p_url = sub.add_parser("login-url", help="build OAuth2 consent URL")
    p_url.add_argument("--redirect-uri", required=True)
    p_url.add_argument("--state", default="cli_smoke")
    p_url.add_argument("--scopes", nargs="+", default=DEFAULT_SCOPES)

    p_x = sub.add_parser("exchange", help="exchange authorization code")
    p_x.add_argument("--code", required=True)
    p_x.add_argument("--redirect-uri", required=True)

    p_me = sub.add_parser("me", help="GET /v1/me with a bearer token")
    p_me.add_argument("--access-token", required=True)

    p_bm = sub.add_parser("bitmoji", help="build Bitmoji CDN URL")
    p_bm.add_argument("--external-id", required=True)

    p_sh = sub.add_parser("share", help="build Creative Kit share deeplink")
    p_sh.add_argument("--sticker-id", default="")
    p_sh.add_argument("--caption", default="")
    p_sh.add_argument("--attachment-url", default="")

    sub.add_parser("providers", help="list expected tools + endpoints")

    args = ap.parse_args()
    c = SnapKitConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({"connected": ok,
                            "has_client_id":     bool(c._client_id),
                            "has_client_secret": bool(c._client_secret)},
                           indent=2))

    elif args.cmd == "verify":
        r = c.send("verify_credentials", "")
        print(json.dumps({"success": r.success,
                            "keys_present": r.metadata.get("keys_present"),
                            "preview": r.message_preview,
                            "error": r.error}, indent=2))

    elif args.cmd == "login-url":
        r = c.send("login_oauth2_url", json.dumps({
            "redirect_uri": args.redirect_uri,
            "state":        args.state,
            "scopes":       args.scopes,
        }))
        print(json.dumps({"success": r.success,
                            "url": r.metadata.get("oauth2_url", ""),
                            "error": r.error}, indent=2))

    elif args.cmd == "exchange":
        r = c.send("exchange_code", json.dumps({
            "code":         args.code,
            "redirect_uri": args.redirect_uri,
        }))
        print(json.dumps({"success": r.success,
                            "token_type": r.metadata.get("token_type", ""),
                            "expires_in": r.metadata.get("expires_in", ""),
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "error": r.error}, indent=2))

    elif args.cmd == "me":
        r = c.send("me", json.dumps({"access_token": args.access_token}))
        print(json.dumps({"success": r.success,
                            "display_name": r.metadata.get("display_name", ""),
                            "external_id":  r.metadata.get("external_id", ""),
                            "bitmoji":      r.metadata.get("bitmoji_avatar", ""),
                            "crystal":      r.crystal_id[:24] if r.crystal_id else "",
                            "error":        r.error}, indent=2))

    elif args.cmd == "bitmoji":
        r = c.send("bitmoji_avatar_url",
                    json.dumps({"external_id": args.external_id}))
        print(json.dumps({"success": r.success,
                            "url": r.metadata.get("avatar_url", ""),
                            "error": r.error}, indent=2))

    elif args.cmd == "share":
        r = c.send("creative_share_url", json.dumps({
            "sticker_id":     args.sticker_id,
            "caption":        args.caption,
            "attachment_url": args.attachment_url,
        }))
        print(json.dumps({"success": r.success,
                            "url": r.metadata.get("share_url", ""),
                            "error": r.error}, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools":     list(EXPECTED_TOOLS),
            "oauth_auth_url":     SNAP_OAUTH_AUTH_URL,
            "oauth_token_url":    SNAP_OAUTH_TOKEN_URL,
            "me_url":             SNAP_KIT_ME_URL,
            "bitmoji_avatar_url": BITMOJI_AVATAR_URL,
            "creative_kit_scheme": CREATIVE_KIT_SCHEME,
            "default_scopes":     DEFAULT_SCOPES,
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
