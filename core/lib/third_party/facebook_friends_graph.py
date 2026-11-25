#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        facebook_friends_graph
# role:        CONNECTOR · FACEBOOK_FRIENDS_GRAPH_HARVESTER
# tier:        L0
# substrate:   Graph API /me/friends + FBInstant.player.getConnectedPlayersAsync
#              landing point for the MySpace++ social graph. Persists each
#              consenting friend edge via social_graph_persistence.upsert_edge
#              and crystal-anchors every harvest event.
# storage:     ~/.cc/third_party_logs/facebook_friends_sends.jsonl
#              + crystal chain (tier='social_graph', model='facebook_friends_graph')
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.facebook_friends_graph.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/cc.sh (future: cmd_fb_friends_harvest)
#   - studio/dapp/server.py (FBInstant webhook handler — POST connected_players
#     after the SDK reports them client-side)
#   - facebook_games_sdk.graph_get_me callers (once /me?fields=permissions
#     confirms user_friends scope was granted, this connector runs)
# outbound:
#   - https://graph.facebook.com/<version>/me/friends?fields=...
#   - https://graph.facebook.com/<version>/me/permissions
#   - https://graph.facebook.com/<version>/me?fields=id  (revoke probe)
#   - social_graph_persistence.upsert_edge(player_id, friend_player_id, **meta)
#   - inference_logger.log (tier='social_graph', model='facebook_friends_graph')
# substrate touch:
#   - reads:  FB_APP_ID + FB_APP_SECRET + optional FB_USER_ACCESS_TOKEN
#   - reads:  FB_GRAPH_API_VERSION + FB_GRAPH_API_BASE (shared with games_sdk)
#   - writes: send_log entries + crystal_chain social_graph records +
#             social_graph DB edges (when persistence module is importable)
# ----------------------------------------------------------------------------
# SAFETY RAIL
# ----------------------------------------------------------------------------
# NEVER harvest /me/friends without the user_friends scope being granted via
# explicit FB OAuth consent + a checkbox on the terms page. The harvest_for
# tool calls check_permissions FIRST; if 'user_friends' is missing or marked
# 'declined' it refuses to call /me/friends and returns
# SendResult(success=False, error='user_friends_scope_not_granted').
# Facebook platform policy: /me/friends returns ONLY app-active friends; this
# is enforced by the platform, not the connector.
# ============================================================================
"""facebook_friends_graph.py — Friends-graph harvester.

Companion to facebook_games_sdk.py (which owns the developer surface). This
module is single-purpose:
  - given a user_access_token + player_id, harvest the consenting friends
    list and persist each edge into the MySpace++ social graph.

Supported sources:
  - source='graph_api'  → GET /me/friends?fields=id,name,picture.type(large)
                           &limit=5000&access_token=<token>  (paginates)
  - source='fb_instant' → consumes payload.connected_players array from
                           FBInstant.player.getConnectedPlayersAsync (which
                           includes signed signatures when available)

Tools (via send(recipient=tool_name, message=json_args)):
  - harvest_for(user_access_token, player_id, source, payload?)
      Primary entry. graph_api or fb_instant; persists every friend; returns
      SendResult with metadata.friends_count + new_friends_count.
  - check_permissions(user_access_token)
      GET /me/permissions  → SAFETY RAIL — must show user_friends granted
      before harvest_for(source='graph_api') is allowed.
  - revoke_check(user_access_token)
      GET /me?fields=id  → 401/190 signals token revoked.
  - friend_of_friend(player_id, depth=2)
      Query the persisted graph for 2nd-degree connections.
  - nearby_active_friends(player_id, geo_radius_km=50)
      Geo filter on persisted friends (graceful empty when geo unknown).
  - verify_credentials()
      Read-only smoke; mirrors the games_sdk shape.

Env vars (gracefully empty when absent):
  FB_APP_ID                — Facebook App ID
  FB_APP_SECRET            — App Secret (used for appsecret_proof)
  FB_USER_ACCESS_TOKEN     — Optional fallback user token for CLI usage
  FB_GRAPH_API_VERSION     — Defaults to v18.0
  FB_GRAPH_API_BASE        — Full base URL override

Every successful harvest crystal-anchors via inference_logger.log
(tier='social_graph', model='facebook_friends_graph', scope='friends_harvest').
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
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

DEFAULT_GRAPH_VERSION = "v18.0"
DEFAULT_GRAPH_HOST = "https://graph.facebook.com"
DEFAULT_PAGE_LIMIT = 5000
MAX_PAGES = 50  # hard cap on pagination loops to prevent runaway harvests

EXPECTED_TOOLS = (
    "harvest_for",
    "check_permissions",
    "revoke_check",
    "friend_of_friend",
    "nearby_active_friends",
    "verify_credentials",
)


# ---------------------------------------------------------------------------
# .env loaders — mirror facebook_games_sdk pattern
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
    override = _load_env_var("FB_GRAPH_API_BASE")
    if override:
        return override.rstrip("/")
    return f"{DEFAULT_GRAPH_HOST}/{_load_graph_version()}"


# ---------------------------------------------------------------------------
# HTTP helpers — stdlib only
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# Social graph persistence — import-guarded (agent F builds the real module)
# ---------------------------------------------------------------------------

def _persist_edge(player_id: str, friend_player_id: str,
                   meta: Dict[str, Any]) -> bool:
    """Try to persist via social_graph_persistence.upsert_edge.
    Returns True if persisted, False if module unavailable (graceful no-op)."""
    try:
        from social_graph_persistence import upsert_edge  # type: ignore
        upsert_edge(player_id, friend_player_id, **meta)
        return True
    except ImportError:
        return False
    except Exception as e:
        sys.stderr.write(
            f"warn: social_graph_persistence.upsert_edge failed for "
            f"{player_id}->{friend_player_id}: {type(e).__name__}: {e}\n"
        )
        return False


def _query_persisted_edges(player_id: str, depth: int = 1) -> List[Dict[str, Any]]:
    """Query persisted edges. Graceful empty list if module not importable."""
    try:
        from social_graph_persistence import query_edges  # type: ignore
        return query_edges(player_id, depth=depth) or []
    except ImportError:
        return []
    except Exception as e:
        sys.stderr.write(
            f"warn: social_graph_persistence.query_edges failed for "
            f"{player_id}: {type(e).__name__}: {e}\n"
        )
        return []


def _query_persisted_geo(player_id: str, geo_radius_km: float
                          ) -> Tuple[List[Dict[str, Any]], str]:
    """Geo-filtered friends from persisted graph. Returns (list, note)."""
    try:
        from social_graph_persistence import query_geo_friends  # type: ignore
        rows = query_geo_friends(player_id, geo_radius_km=geo_radius_km) or []
        return rows, ""
    except ImportError:
        return [], "social_graph_persistence not yet available"
    except Exception as e:
        return [], f"query_geo_friends_error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_social_graph(tool: str, params: Dict[str, Any],
                       result: Dict[str, Any], latency_ms: int,
                       status_code: int) -> str:
    """Append one InferenceRecord with tier='social_graph',
    model='facebook_friends_graph'. Returns crystal_id or empty string."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        # Redact bearer-equivalent + PII-like fields from the preview payload
        safe_params = {
            k: v for k, v in params.items()
            if k not in (
                "access_token", "user_access_token", "appsecret_proof",
                "app_secret", "signed_player_info", "payload",
            )
        }
        # Only surface aggregate / id-shaped result fields
        safe_result = {
            k: v for k, v in result.items()
            if k in (
                "friends_count", "new_friends_count", "page_count",
                "scope_user_friends_granted", "permissions_count",
                "token_valid", "depth", "edges_count",
                "geo_radius_km", "matched_count", "note",
                "source", "id",
            )
        }
        crystal_id = il.log(
            original_prompt=f"facebook_friends_graph.{tool}",
            enhanced_prompt=json.dumps(safe_params, separators=(",", ":"))[:512],
            output_text=json.dumps(safe_result, separators=(",", ":"))[:512],
            tier="social_graph",
            model="facebook_friends_graph",
            scope="friends_harvest" if tool == "harvest_for" else f"fb_{tool}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"facebook_friends_graph.{tool}",
            done_flag=(200 <= status_code < 300),
            rc=0 if 200 <= status_code < 300 else 1,
        )
        return crystal_id or ""
    except Exception as e:
        sys.stderr.write(
            f"warn: facebook_friends_graph crystal log failed: "
            f"{type(e).__name__}: {e}\n"
        )
        return ""


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class FacebookFriendsGraphConnector(ThirdPartyConnector):
    """Friends-graph harvester for the MySpace++ social graph.

    Auth model: user-context endpoints (/me/friends, /me/permissions, /me) all
    require a user_access_token. Token can be supplied per-call (preferred) via
    send(..., user_access_token=<t>) OR fall back to FB_USER_ACCESS_TOKEN env.

    connect() validates FB_APP_ID + FB_APP_SECRET are present (needed for
    appsecret_proof signing on subsequent /me/* calls); harvest is gated behind
    check_permissions confirming user_friends scope is GRANTED.
    """

    SERVICE = "facebook_friends"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="facebook_friends_default",
                action="friends_harvest",
            )
        super().__init__(config)
        self._app_id = ""
        self._app_secret = ""
        self._user_access_token = ""
        self._base_url = ""
        self._connected = False

    # ---- lifecycle ------------------------------------------------------

    def connect(self) -> bool:
        self._app_id = _load_app_id()
        self._app_secret = _load_app_secret()
        self._user_access_token = _load_user_access_token()
        self._base_url = _load_graph_base().rstrip("/")
        self._connected = bool(self._app_id and self._app_secret)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        log_path = (Path.home() / ".cc" / "third_party_logs"
                    / "facebook_friends_sends.jsonl")
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- helpers --------------------------------------------------------

    def _appsecret_proof(self, user_access_token: str) -> str:
        if not (self._app_secret and user_access_token):
            return ""
        return hmac.new(
            self._app_secret.encode("utf-8"),
            user_access_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _attach_proof(self, url: str, user_access_token: str) -> str:
        proof = self._appsecret_proof(user_access_token)
        if proof:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}appsecret_proof={urllib.parse.quote(proof)}"
        return url

    @staticmethod
    def _friend_picture(rec: Dict[str, Any]) -> str:
        """Extract picture URL from a Graph API friend record OR fb_instant
        connected_player record. Graph API returns picture.data.url; the SDK
        returns a flat 'photo' field per FBInstant docs."""
        pic = rec.get("picture")
        if isinstance(pic, dict):
            data = pic.get("data") or {}
            if isinstance(data, dict) and data.get("url"):
                return data["url"]
        return (rec.get("photo")
                or rec.get("picture_url")
                or rec.get("avatar")
                or "")

    # ---- dispatcher -----------------------------------------------------

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        # Always re-resolve env on every send so .env edits take effect
        if not self._base_url:
            self.connect()
        # Even if connect() returned False (missing FB_APP_ID/SECRET) we still
        # have self._base_url + self._app_id/_app_secret cached from connect().

        t0 = time.time()

        if recipient == "verify_credentials":
            status, body = self._verify_credentials()
        elif recipient == "check_permissions":
            status, body = self._check_permissions(params)
        elif recipient == "revoke_check":
            status, body = self._revoke_check(params)
        elif recipient == "harvest_for":
            status, body = self._harvest_for(params)
        elif recipient == "friend_of_friend":
            status, body = self._friend_of_friend(params)
        elif recipient == "nearby_active_friends":
            status, body = self._nearby_active_friends(params)
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
        # Crystal-anchor harvest + local queries even without app keys (they
        # are the deterministic events we care about). Network tools still
        # require keys to avoid logging fake successes.
        is_local_tool = recipient in (
            "friend_of_friend", "nearby_active_friends"
        )
        if success and (is_local_tool or (self._app_id and self._app_secret)):
            crystal_id = _log_social_graph(
                recipient, params, body, latency_ms, status,
            )

        # Build a compact preview
        preview = (
            str(body.get("friends_count", ""))
            or str(body.get("edges_count", ""))
            or str(body.get("matched_count", ""))
            or body.get("note", "")
            or str(body.get("scope_user_friends_granted", ""))
            or str(body)[:200]
        )

        metadata: Dict[str, Any] = {
            "status_code": status,
            "latency_ms": latency_ms,
            "graph_version": _load_graph_version(),
            "tool": recipient,
        }
        # Surface harvest + permission stats from the body
        for k in (
            "friends_count", "new_friends_count", "page_count",
            "scope_user_friends_granted", "permissions_count",
            "token_valid", "depth", "edges_count",
            "geo_radius_km", "matched_count", "note", "source",
            "error_for_oauth_revoked", "persisted",
        ):
            if k in body and not isinstance(body.get(k), (dict, list)):
                metadata[k] = body[k]
        if isinstance(body.get("friends"), list):
            metadata["friends_sample"] = [
                {
                    "id": f.get("friend_player_id", ""),
                    "name": f.get("friend_name", ""),
                }
                for f in body["friends"][:3]
            ]

        err = ""
        if not success:
            fb_err = body.get("error", {})
            if isinstance(fb_err, dict) and fb_err.get("message"):
                code = fb_err.get("code", "")
                err = f"fb_error:{code}:{fb_err.get('message','')[:200]}"
            else:
                err = body.get("_error", "") or f"http_{status}"

        return SendResult(
            success=success, crystal_id=crystal_id, service=self.SERVICE,
            recipient=recipient, message_preview=str(preview)[:200],
            timestamp=time.time(),
            error=err,
            metadata=metadata,
        )

    # ---- Tool implementations ------------------------------------------

    def _verify_credentials(self) -> Tuple[int, Dict[str, Any]]:
        """Read-only smoke: confirm FB_APP_ID + FB_APP_SECRET present.
        Does NOT hit the network — friends harvesting never needs an app token
        independent of the user context."""
        if not (self._app_id and self._app_secret):
            return 400, {
                "_error": (
                    "facebook_friends_keys not configured "
                    "(missing FB_APP_ID and/or FB_APP_SECRET)"
                ),
                "has_app_id": bool(self._app_id),
                "has_app_secret": bool(self._app_secret),
            }
        return 200, {
            "has_app_id": True,
            "has_app_secret": True,
            "base_url": self._base_url,
            "graph_version": _load_graph_version(),
            "note": "ready — supply user_access_token per call",
        }

    def _check_permissions(self, p: Dict[str, Any]
                            ) -> Tuple[int, Dict[str, Any]]:
        """GET /me/permissions — returns the list of granted/declined scopes.
        Surfaces scope_user_friends_granted so harvest_for can gate on it."""
        uat = (p.get("user_access_token")
               or p.get("access_token")
               or self._user_access_token)
        if not uat:
            return 400, {
                "_error": "missing user_access_token",
                "scope_user_friends_granted": False,
            }
        if not self._base_url:
            return 400, {"_error": "facebook_friends_not_configured"}
        url = (
            f"{self._base_url}/me/permissions"
            f"?access_token={urllib.parse.quote(uat)}"
        )
        url = self._attach_proof(url, uat)
        status, body = _http_get(url, timeout=15)
        # Normalize: surface scope_user_friends_granted as top-level bool
        granted = False
        permissions_count = 0
        if isinstance(body, dict) and isinstance(body.get("data"), list):
            permissions_count = len(body["data"])
            for perm in body["data"]:
                if (isinstance(perm, dict)
                        and perm.get("permission") == "user_friends"
                        and perm.get("status") == "granted"):
                    granted = True
                    break
        if isinstance(body, dict):
            body["scope_user_friends_granted"] = granted
            body["permissions_count"] = permissions_count
        return status, body

    def _revoke_check(self, p: Dict[str, Any]
                       ) -> Tuple[int, Dict[str, Any]]:
        """GET /me?fields=id — 401/190 (OAuthException code 190) means the
        user token was revoked. Status 200 means the token is still valid."""
        uat = (p.get("user_access_token")
               or p.get("access_token")
               or self._user_access_token)
        if not uat:
            return 400, {
                "_error": "missing user_access_token",
                "token_valid": False,
            }
        if not self._base_url:
            return 400, {"_error": "facebook_friends_not_configured"}
        url = (
            f"{self._base_url}/me"
            f"?fields=id"
            f"&access_token={urllib.parse.quote(uat)}"
        )
        url = self._attach_proof(url, uat)
        status, body = _http_get(url, timeout=10)
        # Surface token_valid as top-level bool
        if status == 200:
            if isinstance(body, dict):
                body["token_valid"] = True
        else:
            if not isinstance(body, dict):
                body = {"_error": str(body)}
            body["token_valid"] = False
            fb_err = body.get("error") if isinstance(body, dict) else None
            if isinstance(fb_err, dict) and fb_err.get("code") == 190:
                body["error_for_oauth_revoked"] = True
            elif status == 401:
                body["error_for_oauth_revoked"] = True
        return status, body

    def _harvest_for(self, p: Dict[str, Any]
                      ) -> Tuple[int, Dict[str, Any]]:
        """Primary entry. Honors the user_friends safety rail and either
        paginates /me/friends OR consumes the FBInstant connected_players
        payload, persisting each edge."""
        player_id = p.get("player_id") or ""
        source = (p.get("source") or "graph_api").lower()
        uat = (p.get("user_access_token")
               or p.get("access_token")
               or self._user_access_token)
        signed_player_info = p.get("signed_player_info") or ""

        if not player_id:
            return 400, {"_error": "missing player_id"}

        captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # ---- fb_instant source ------------------------------------------
        if source == "fb_instant":
            payload = p.get("payload") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            connected = payload.get("connected_players") or []
            if not isinstance(connected, list):
                return 400, {"_error": "payload.connected_players must be a list"}
            return self._record_harvest(
                player_id=player_id,
                friends_raw=connected,
                source="fb_instant",
                signed=bool(signed_player_info),
                captured_at=captured_at,
            )

        # ---- graph_api source -------------------------------------------
        if source != "graph_api":
            return 400, {"_error": f"unsupported source: {source}"}

        if not uat:
            return 400, {
                "_error": "missing user_access_token",
                "scope_user_friends_granted": False,
            }

        # SAFETY RAIL: require keys for network harvest + user_friends scope.
        if not (self._app_id and self._app_secret) or not self._base_url:
            return 400, {
                "_error": "facebook_friends_not_configured",
                "has_app_id": bool(self._app_id),
                "has_app_secret": bool(self._app_secret),
            }

        # Step 1 — check_permissions (the safety rail)
        perm_status, perm_body = self._check_permissions(
            {"user_access_token": uat}
        )
        if perm_status != 200:
            return perm_status, {
                "_error": "permission_check_failed",
                "permission_status": perm_status,
                "permission_body": perm_body,
                "scope_user_friends_granted": False,
            }
        if not perm_body.get("scope_user_friends_granted"):
            return 403, {
                "_error": "user_friends_scope_not_granted",
                "scope_user_friends_granted": False,
                "note": (
                    "harvest refused — user_friends scope must be granted "
                    "via FB OAuth + explicit checkbox on terms page"
                ),
            }

        # Step 2 — paginate /me/friends
        limit = int(p.get("limit", DEFAULT_PAGE_LIMIT))
        fields = "id,name,picture.type(large)"
        url: Optional[str] = (
            f"{self._base_url}/me/friends"
            f"?fields={urllib.parse.quote(fields)}"
            f"&limit={limit}"
            f"&access_token={urllib.parse.quote(uat)}"
        )
        url = self._attach_proof(url, uat)

        friends_raw: List[Dict[str, Any]] = []
        page_count = 0
        last_status = 200
        last_body: Dict[str, Any] = {}
        while url and page_count < MAX_PAGES:
            status, body = _http_get(url, timeout=20)
            last_status = status
            last_body = body
            page_count += 1
            if status != 200:
                # Detect revoked-token error explicitly
                fb_err = body.get("error", {}) if isinstance(body, dict) else {}
                if isinstance(fb_err, dict) and (
                    fb_err.get("code") == 190 or status == 401
                ):
                    return status, {
                        "_error": "user_token_revoked",
                        "error_for_oauth_revoked": True,
                        "page_count": page_count,
                    }
                return status, {
                    "_error": body.get("_error", "")
                    or body.get("error", {}).get("message", "")
                    or f"http_{status}",
                    "page_count": page_count,
                }
            data = body.get("data") if isinstance(body, dict) else None
            if isinstance(data, list):
                friends_raw.extend(data)
            paging = body.get("paging") if isinstance(body, dict) else None
            next_url = ""
            if isinstance(paging, dict):
                next_url = paging.get("next") or ""
            url = next_url or None

        result = self._record_harvest(
            player_id=player_id,
            friends_raw=friends_raw,
            source="graph_api",
            signed=False,
            captured_at=captured_at,
        )
        result_status, result_body = result
        if isinstance(result_body, dict):
            result_body["page_count"] = page_count
        return result_status, result_body

    def _record_harvest(self, player_id: str,
                         friends_raw: List[Dict[str, Any]],
                         source: str, signed: bool,
                         captured_at: str) -> Tuple[int, Dict[str, Any]]:
        """Normalize + persist + return summary body. Used by both source paths."""
        friends_normalized: List[Dict[str, Any]] = []
        persisted_count = 0
        for raw in friends_raw:
            if not isinstance(raw, dict):
                continue
            fid = (raw.get("id")
                   or raw.get("friend_player_id")
                   or raw.get("player_id")
                   or "")
            if not fid:
                continue
            name = (raw.get("name")
                    or raw.get("friend_name")
                    or "")
            picture_url = self._friend_picture(raw)
            rec = {
                "player_id": player_id,
                "friend_player_id": str(fid),
                "friend_name": str(name),
                "friend_picture_url": str(picture_url),
                # /me/friends ONLY returns app-active friends per FB policy;
                # FBInstant connected_players are also by definition app-active
                "friend_app_active": True,
                "captured_at": captured_at,
                "source": source,
                "signed": bool(signed),
            }
            friends_normalized.append(rec)
            meta = {
                k: v for k, v in rec.items()
                if k not in ("player_id", "friend_player_id")
            }
            if _persist_edge(player_id, str(fid), meta):
                persisted_count += 1

        body: Dict[str, Any] = {
            "friends_count": len(friends_normalized),
            # Without an existing graph to diff, treat persisted as "new".
            # social_graph_persistence is the source of truth here once it
            # lands; this counter is a best-effort proxy.
            "new_friends_count": persisted_count,
            "persisted": persisted_count,
            "source": source,
            "signed": bool(signed),
            "error_for_oauth_revoked": False,
            "friends": friends_normalized,
        }
        return 200, body

    def _friend_of_friend(self, p: Dict[str, Any]
                           ) -> Tuple[int, Dict[str, Any]]:
        """Query persisted graph for 2nd-degree (default) connections."""
        player_id = p.get("player_id") or ""
        if not player_id:
            return 400, {"_error": "missing player_id"}
        depth = int(p.get("depth", 2))
        if depth < 1:
            depth = 1
        edges = _query_persisted_edges(player_id, depth=depth)
        return 200, {
            "depth": depth,
            "edges_count": len(edges),
            "edges": edges[:200],
            "note": (
                "" if edges
                else "no persisted edges yet — run harvest_for first or "
                     "wait for social_graph_persistence to land"
            ),
        }

    def _nearby_active_friends(self, p: Dict[str, Any]
                                ) -> Tuple[int, Dict[str, Any]]:
        """Geo-filtered friends from persisted graph. Geo data may not be
        attached yet — graceful empty with explanatory note."""
        player_id = p.get("player_id") or ""
        if not player_id:
            return 400, {"_error": "missing player_id"}
        geo_radius_km = float(p.get("geo_radius_km", 50))
        matches, note = _query_persisted_geo(player_id, geo_radius_km)
        return 200, {
            "geo_radius_km": geo_radius_km,
            "matched_count": len(matches),
            "matches": matches[:200],
            "note": note or (
                "no geo-tagged matches — players in this region either "
                "haven't shared geo or social_graph_persistence has no "
                "geo column yet"
            ),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="facebook_friends_graph — Friends-graph harvester"
    )
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")
    sub.add_parser("verify", help="read-only smoke")
    p_perm = sub.add_parser("permissions", help="check user_friends scope")
    p_perm.add_argument("--user-token", default="")
    p_rev = sub.add_parser("revoke-check", help="probe token validity")
    p_rev.add_argument("--user-token", default="")
    p_harv = sub.add_parser("harvest", help="run /me/friends harvest")
    p_harv.add_argument("player_id")
    p_harv.add_argument("--user-token", default="")
    p_harv.add_argument("--source", default="graph_api",
                         choices=["graph_api", "fb_instant"])
    p_harv.add_argument("--payload-json", default="",
                         help="JSON for fb_instant connected_players")
    p_fof = sub.add_parser("fof", help="friend-of-friend query")
    p_fof.add_argument("player_id")
    p_fof.add_argument("--depth", type=int, default=2)
    p_geo = sub.add_parser("nearby", help="nearby active friends")
    p_geo.add_argument("player_id")
    p_geo.add_argument("--radius-km", type=float, default=50.0)
    sub.add_parser("providers", help="list expected tools + env vars")

    args = ap.parse_args()
    c = FacebookFriendsGraphConnector()

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
        print(json.dumps({
            "success": r.success,
            "preview": r.message_preview,
            "metadata": r.metadata,
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "error": r.error,
        }, indent=2))

    elif args.cmd == "permissions":
        uat = args.user_token or _load_user_access_token()
        r = c.send("check_permissions",
                    json.dumps({"user_access_token": uat}))
        print(json.dumps({
            "success": r.success,
            "metadata": r.metadata,
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "error": r.error,
        }, indent=2))

    elif args.cmd == "revoke-check":
        uat = args.user_token or _load_user_access_token()
        r = c.send("revoke_check",
                    json.dumps({"user_access_token": uat}))
        print(json.dumps({
            "success": r.success,
            "metadata": r.metadata,
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "error": r.error,
        }, indent=2))

    elif args.cmd == "harvest":
        uat = args.user_token or _load_user_access_token()
        body: Dict[str, Any] = {
            "user_access_token": uat,
            "player_id": args.player_id,
            "source": args.source,
        }
        if args.payload_json:
            try:
                body["payload"] = json.loads(args.payload_json)
            except json.JSONDecodeError:
                body["payload"] = {}
        r = c.send("harvest_for", json.dumps(body))
        print(json.dumps({
            "success": r.success,
            "metadata": r.metadata,
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "error": r.error,
        }, indent=2))

    elif args.cmd == "fof":
        r = c.send("friend_of_friend",
                    json.dumps({"player_id": args.player_id,
                                  "depth": args.depth}))
        print(json.dumps({
            "success": r.success,
            "metadata": r.metadata,
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "error": r.error,
        }, indent=2))

    elif args.cmd == "nearby":
        r = c.send("nearby_active_friends",
                    json.dumps({"player_id": args.player_id,
                                  "geo_radius_km": args.radius_km}))
        print(json.dumps({
            "success": r.success,
            "metadata": r.metadata,
            "crystal": r.crystal_id[:24] if r.crystal_id else "",
            "error": r.error,
        }, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "env_vars": [
                "FB_APP_ID", "FB_APP_SECRET", "FB_USER_ACCESS_TOKEN",
                "FB_GRAPH_API_VERSION", "FB_GRAPH_API_BASE",
            ],
            "default_graph_version": DEFAULT_GRAPH_VERSION,
            "default_graph_host": DEFAULT_GRAPH_HOST,
            "default_page_limit": DEFAULT_PAGE_LIMIT,
            "max_pages": MAX_PAGES,
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
