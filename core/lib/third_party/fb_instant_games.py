#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        fb_instant_games
# role:        CONNECTOR · FB_INSTANT_GAMES_JS_SDK_COMPANION
# tier:        L0
# substrate:   Server-side companion to the Facebook Instant Games JavaScript
#              SDK. Records every event the JS SDK reports via the dApp
#              /dapp/api/fb_event POST surface, verifies signedPlayerInfo HMAC,
#              and crystal-anchors every recorded event.
# storage:     ~/.cc/fb_instant_events.jsonl (event sink)
#              ~/.cc/third_party_logs/fb_instant_games_sends.jsonl (history)
#              ~/.cc/inference_master_chain.jsonl (crystal-anchored fb_event)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.fb_instant_games.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/dapp/server.py /dapp/api/fb_event POST (JS SDK callback)
#   - Godot HTML5 build → /dapp/api/fb_event (in-game events)
#   - core/cc.sh (future: cmd_fb_instant_stats)
# outbound:
#   - inference_logger.log (tier='fb_event', model='fb_instant_games')
#   - core/lib/third_party/facebook_friends_graph (agent B harvester) when
#     event_name == 'instant.friends.list_pulled'
# substrate touch:
#   - reads:  FB_APP_ID + FB_APP_SECRET from .env (via studio/auth/keys.load_env)
#   - writes: ~/.cc/fb_instant_events.jsonl (append-only event sink)
#   - writes: send_log entries + crystal_chain fb_event records
# ----------------------------------------------------------------------------
# THE TWO ROLES
# ----------------------------------------------------------------------------
# 1. Event sink     — record_event() ingests every JS SDK callback POST
# 2. Surface manifest — SDK_MANIFEST documents the ~20 wrapped FBInstant calls
#                        so studio/dapp + the Godot HTML5 build know what to call
# ============================================================================
"""fb_instant_games.py — Facebook Instant Games JS SDK server companion.

Companion to core/lib/third_party/facebook_games_sdk.py (the Graph API REST
connector). Where facebook_games_sdk talks to graph.facebook.com from the
server, fb_instant_games sits behind the dApp HTTP surface and:

  1. Records every event the in-browser JS SDK reports (via /dapp/api/fb_event).
  2. Verifies the `signed_player_info` HMAC so we can trust the player_id.
  3. Documents the full FBInstant SDK surface so the Godot HTML5 build + the
     studio dApp know which JS calls to wire to which server event.

The JS SDK runs inside the FB-embedded iframe (Messenger / News Feed). It
calls our dApp on every meaningful surface action, e.g.::

    fetch('/dapp/api/fb_event', {
        method: 'POST',
        headers: {'Authorization': 'Bearer <freetier-token>'},
        body: JSON.stringify({
            event_name: 'instant.player.id_read',
            player_id: FBInstant.player.getID(),
            context_id: FBInstant.context.getID(),
            signed_data: '<signed_player_info from getSignedPlayerInfoAsync>',
            payload: {...}
        })
    })

The dApp handler verifies the freetier token (core/lib/freetier_gate.py
verify_token), then calls FBInstantGamesConnector.record_event(...). Every
recorded event is appended to ~/.cc/fb_instant_events.jsonl and crystal
anchored via inference_logger.log(tier='fb_event', model='fb_instant_games').

When event_name == 'instant.friends.list_pulled', the payload is also handed
off to the facebook_friends_graph harvester (agent B) for connection-graph
persistence. The handoff is wrapped in try/except so this module remains
useful even if the harvester is not yet installed.

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - record_event(event_name, player_id, context_id, signed_data, payload)
  - verify_signed_data(signed_player_info, fb_app_secret)  — pure stdlib hmac
  - manifest()                                              — returns SDK_MANIFEST
  - event_stats(since_ts=None)                              — count by event_name

Env vars (handled gracefully when absent):
  FB_APP_ID         — Facebook App ID (used for connect-status check)
  FB_APP_SECRET     — App Secret (used to verify signed_player_info HMACs)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402


# ---------------------------------------------------------------------------
# SDK surface manifest — documents every FBInstant JS call we wrap
# ---------------------------------------------------------------------------
# Each entry shape:
#   {
#       "js_call":           "FBInstant.<path>(args)",
#       "scope_required":    "<FB permission scope or 'none'>",
#       "server_event_name": "instant.<dotted>",
#       "description":       "one-line behavior",
#       "body_schema":       {<expected POST body keys>: "<type>"}
#   }
SDK_MANIFEST: Dict[str, Dict[str, Any]] = {
    "initializeAsync": {
        "js_call":           "FBInstant.initializeAsync()",
        "scope_required":    "none",
        "server_event_name": "instant.initialized",
        "description":       "Boot the SDK; resolves once Messenger/News-Feed iframe is ready.",
        "body_schema":       {"event_name": "str", "player_id": "str?", "context_id": "str?"},
    },
    "startGameAsync": {
        "js_call":           "FBInstant.startGameAsync()",
        "scope_required":    "none",
        "server_event_name": "instant.game_started",
        "description":       "Signal that the loading screen is dismissed and gameplay begins.",
        "body_schema":       {"event_name": "str", "player_id": "str", "context_id": "str"},
    },
    "player_getID": {
        "js_call":           "FBInstant.player.getID()",
        "scope_required":    "none",
        "server_event_name": "instant.player.id_read",
        "description":       "Read the FB-scoped player ID (PSID-equivalent, app-scoped).",
        "body_schema":       {"event_name": "str", "player_id": "str"},
    },
    "player_getName": {
        "js_call":           "FBInstant.player.getName()",
        "scope_required":    "public_profile",
        "server_event_name": "instant.player.name_read",
        "description":       "Read the player's FB display name.",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"name": "str"}},
    },
    "player_getPhoto": {
        "js_call":           "FBInstant.player.getPhoto()",
        "scope_required":    "public_profile",
        "server_event_name": "instant.player.photo_read",
        "description":       "Read the player's FB profile photo URL.",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"photo_url": "str"}},
    },
    "player_getSignedPlayerInfoAsync": {
        "js_call":           "FBInstant.player.getSignedPlayerInfoAsync(requestPayload)",
        "scope_required":    "none",
        "server_event_name": "instant.signed_player_info",
        "description":       "Server-validated identity: returns {signature, signedPlayerInfo} that we HMAC-verify with FB_APP_SECRET.",
        "body_schema":       {"event_name": "str", "player_id": "str", "signed_data": "str(base64url.base64url)"},
    },
    "player_getConnectedPlayersAsync": {
        "js_call":           "FBInstant.player.getConnectedPlayersAsync()",
        "scope_required":    "user_friends",
        "server_event_name": "instant.friends.list_pulled",
        "description":       "FRIENDS HARVEST. Returns the list of the player's FB friends who also play this game. Handed off to facebook_friends_graph (agent B) for social-graph persistence.",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"friends": "list[{id,name,photo}]"}},
    },
    "context_getID": {
        "js_call":           "FBInstant.context.getID()",
        "scope_required":    "none",
        "server_event_name": "instant.context.id_read",
        "description":       "Read the current context ID (chat thread or SOLO).",
        "body_schema":       {"event_name": "str", "player_id": "str", "context_id": "str"},
    },
    "context_getType": {
        "js_call":           "FBInstant.context.getType()",
        "scope_required":    "none",
        "server_event_name": "instant.context.type_read",
        "description":       "Read the context type: SOLO | THREAD | GROUP | POST.",
        "body_schema":       {"event_name": "str", "context_id": "str", "payload": {"type": "str"}},
    },
    "context_switchAsync": {
        "js_call":           "FBInstant.context.switchAsync(contextID)",
        "scope_required":    "none",
        "server_event_name": "instant.context.switched",
        "description":       "Switch into a specific context the player already shares with.",
        "body_schema":       {"event_name": "str", "player_id": "str", "context_id": "str"},
    },
    "context_chooseAsync": {
        "js_call":           "FBInstant.context.chooseAsync(opts)",
        "scope_required":    "none",
        "server_event_name": "instant.context.chosen",
        "description":       "Open the FB chat picker so the player can drop the game into a friend chat.",
        "body_schema":       {"event_name": "str", "player_id": "str", "context_id": "str"},
    },
    "context_createAsync": {
        "js_call":           "FBInstant.context.createAsync(playerID)",
        "scope_required":    "none",
        "server_event_name": "instant.context.created",
        "description":       "Programmatically create a 1:1 context with a specific connected player.",
        "body_schema":       {"event_name": "str", "player_id": "str", "context_id": "str"},
    },
    "shareAsync": {
        "js_call":           "FBInstant.shareAsync(payload)",
        "scope_required":    "none",
        "server_event_name": "instant.shared",
        "description":       "Open the FB share sheet with a custom image+text payload.",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"text": "str", "image": "str?"}},
    },
    "updateAsync": {
        "js_call":           "FBInstant.updateAsync(payload)",
        "scope_required":    "none",
        "server_event_name": "instant.update_posted",
        "description":       "Post a CUSTOM update card into the current chat context.",
        "body_schema":       {"event_name": "str", "player_id": "str", "context_id": "str", "payload": {"action": "str", "template": "str"}},
    },
    "payments_purchaseAsync": {
        "js_call":           "FBInstant.payments.purchaseAsync(payload)",
        "scope_required":    "none",
        "server_event_name": "instant.payment_attempted",
        "description":       "Trigger an FB Payments purchase flow; returns a signed receipt.",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"productID": "str", "developerPayload": "str?"}},
    },
    "payments_consumePurchaseAsync": {
        "js_call":           "FBInstant.payments.consumePurchaseAsync(purchaseToken)",
        "scope_required":    "none",
        "server_event_name": "instant.payment_consumed",
        "description":       "Mark a previously purchased consumable as consumed.",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"purchase_token": "str"}},
    },
    "getLeaderboardAsync": {
        "js_call":           "FBInstant.getLeaderboardAsync(name)",
        "scope_required":    "none",
        "server_event_name": "instant.leaderboard_read",
        "description":       "Fetch leaderboard entries by api name.",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"leaderboard_name": "str", "entry_count": "int?"}},
    },
    "getEntryPointAsync": {
        "js_call":           "FBInstant.getEntryPointAsync()",
        "scope_required":    "none",
        "server_event_name": "instant.entry_point_read",
        "description":       "Where did the player launch from? (POST_PAYLOAD | MESSENGER_INBOX | FEED | ADMIN_MESSAGE | ...).",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"entry_point": "str"}},
    },
    "getEntryPointDataAsync": {
        "js_call":           "FBInstant.getEntryPointData()",
        "scope_required":    "none",
        "server_event_name": "instant.entry_data_read",
        "description":       "Read the JSON payload attached when the entry-point was created (e.g. shared challenge card).",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"entry_data": "object"}},
    },
    "matchPlayerAsync": {
        "js_call":           "FBInstant.matchPlayerAsync(matchTag, switchContext)",
        "scope_required":    "none",
        "server_event_name": "instant.match_requested",
        "description":       "Request that FB matchmake the player with another player on the same matchTag.",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"match_tag": "str?", "switch_context": "bool?"}},
    },
    "logEvent": {
        "js_call":           "FBInstant.logEvent(eventName, valueToSum, parameters)",
        "scope_required":    "none",
        "server_event_name": "instant.app_event_logged",
        "description":       "Log an FB Analytics App Event from inside the game.",
        "body_schema":       {"event_name": "str", "player_id": "str", "payload": {"name": "str", "value_to_sum": "number?", "parameters": "object?"}},
    },
}

EXPECTED_TOOLS = (
    "record_event",
    "verify_signed_data",
    "manifest",
    "event_stats",
)

# Event sink — single append-only JSONL.
EVENT_SINK_PATH = Path.home() / ".cc" / "fb_instant_events.jsonl"


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


# ---------------------------------------------------------------------------
# signed_player_info verification — stdlib hmac
# ---------------------------------------------------------------------------
# FB serves signed_player_info as `<sig_b64url>.<payload_b64url>` where:
#   sig     = HMAC_SHA256(app_secret, payload_b64url)
#   payload = base64url-decoded JSON containing:
#             { "algorithm": "HMAC-SHA256",
#               "issued_at":  <epoch>,
#               "player_id":  "<fb_player_id>",
#               "request_payload": "<echo of getSignedPlayerInfoAsync arg>" }

def _b64url_decode(s: str) -> bytes:
    """Decode base64url with missing-padding tolerance."""
    pad = 4 - (len(s) % 4)
    if pad and pad < 4:
        s = s + ("=" * pad)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def verify_signed_data(signed_player_info: str,
                       fb_app_secret: str) -> Dict[str, Any]:
    """Verify the FBInstant signed_player_info HMAC.

    Returns {valid: bool, player_id: str, request_payload: str, error: str?, issued_at: int?}.
    Never raises. Pure stdlib (hmac/hashlib/base64/json).
    """
    out: Dict[str, Any] = {
        "valid": False,
        "player_id": "",
        "request_payload": "",
    }
    if not signed_player_info or "." not in signed_player_info:
        out["error"] = "malformed: expected '<sig>.<payload>'"
        return out
    if not fb_app_secret:
        out["error"] = "missing fb_app_secret"
        return out
    try:
        sig_b64, payload_b64 = signed_player_info.split(".", 1)
        expected_sig = hmac.new(
            fb_app_secret.encode("utf-8"),
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).digest()
        provided_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            out["error"] = "signature_mismatch"
            return out
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
        algo = payload.get("algorithm", "")
        if algo.upper().replace("-", "") not in ("HMACSHA256",):
            out["error"] = f"unsupported_algorithm:{algo}"
            return out
        out["valid"] = True
        out["player_id"] = payload.get("player_id", "")
        out["request_payload"] = payload.get("request_payload", "")
        out["issued_at"] = int(payload.get("issued_at", 0))
        return out
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_fb_event(event_name: str, player_id: str, context_id: str,
                  payload_summary: Dict[str, Any], signed_valid: bool,
                  latency_ms: int) -> str:
    """Append one InferenceRecord with tier='fb_event', model='fb_instant_games'.
    Returns the crystal_id (or '' if logger unavailable)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        safe_payload = {
            k: v for k, v in payload_summary.items()
            if k not in ("signature", "signed_data", "signedPlayerInfo",
                          "access_token", "purchase_token", "developerPayload")
        }
        crystal_id = il.log(
            original_prompt=f"fb_instant.{event_name}",
            enhanced_prompt=json.dumps({
                "player_id": player_id,
                "context_id": context_id,
                "signed_valid": signed_valid,
            }, separators=(",", ":"))[:512],
            output_text=json.dumps(safe_payload, separators=(",", ":"))[:512],
            tier="fb_event",
            model="fb_instant_games",
            scope=f"fb_event_{event_name}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"fb_instant.{event_name}",
            done_flag=True, rc=0,
        )
        return crystal_id or ""
    except Exception as e:
        sys.stderr.write(
            f"warn: fb_instant_games crystal log failed: {type(e).__name__}: {e}\n"
        )
        return ""


def _append_event_sink(record: Dict[str, Any]) -> None:
    """Append one record to ~/.cc/fb_instant_events.jsonl (idempotent dir create)."""
    try:
        EVENT_SINK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_SINK_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    except Exception as e:
        sys.stderr.write(
            f"warn: fb_instant_games event sink write failed: {type(e).__name__}: {e}\n"
        )


def _summarize_payload(payload: Any) -> Dict[str, Any]:
    """Produce a small, redacted summary of a payload for the event-sink log.
    Strips secrets and trims long strings/lists to a single-line size."""
    if not isinstance(payload, dict):
        return {"_raw": str(payload)[:200]}
    out: Dict[str, Any] = {}
    for k, v in payload.items():
        if k in ("signature", "signed_data", "signedPlayerInfo",
                 "access_token", "purchase_token", "developerPayload"):
            continue
        if isinstance(v, str):
            out[k] = v[:200]
        elif isinstance(v, list):
            out[k] = {"_list_len": len(v),
                       "_first": str(v[0])[:200] if v else ""}
        elif isinstance(v, dict):
            out[k] = {"_keys": list(v.keys())[:12]}
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Friends-list hand-off — try/except, the harvester may not exist yet
# ---------------------------------------------------------------------------

def _handoff_friends_to_graph(player_id: str, payload: Dict[str, Any],
                              crystal_id: str) -> Dict[str, Any]:
    """When event_name == 'instant.friends.list_pulled', hand the payload to
    agent B's social_graph_persistence harvester. Never raises; returns a
    status dict for the metadata block."""
    try:
        # Preferred surface: a top-level facebook_friends_graph module.
        try:
            from third_party.facebook_friends_graph import (  # type: ignore
                ingest_friends_list,
            )
        except Exception:
            from facebook_friends_graph import (  # type: ignore
                ingest_friends_list,
            )
        result = ingest_friends_list(
            player_id=player_id,
            friends=payload.get("friends", []) if isinstance(payload, dict) else [],
            source_crystal=crystal_id,
        )
        return {"handoff": "facebook_friends_graph",
                "status": "ok",
                "result": result if isinstance(result, dict) else str(result)[:200]}
    except Exception as e:
        return {"handoff": "facebook_friends_graph",
                "status": "deferred",
                "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class FBInstantGamesConnector(ThirdPartyConnector):
    """Facebook Instant Games JS SDK server companion.

    Sits behind the dApp /dapp/api/fb_event POST surface and records every
    event the in-browser JS SDK reports. Verifies signed_player_info HMACs.
    Crystal-anchors every recorded event. Hands friends_list_pulled payloads
    off to facebook_friends_graph (agent B) for graph persistence.

    Connect status reflects whether FB_APP_ID + FB_APP_SECRET are present
    (so the verify_signed_data tool can actually verify). With keys absent,
    record_event still works (signed_valid=False), manifest/event_stats are
    always available.
    """

    SERVICE = "fb_instant_games"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="fb_instant_games_default",
                action="event_sink",
            )
        super().__init__(config)
        self._app_id = ""
        self._app_secret = ""
        self._connected = False

    # ---- lifecycle ------------------------------------------------------

    def connect(self) -> bool:
        """Returns True iff both FB_APP_ID and FB_APP_SECRET are present.
        No network call — this connector is purely the inbound sink."""
        self._app_id = _load_app_id()
        self._app_secret = _load_app_secret()
        self._connected = bool(self._app_id and self._app_secret)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False
        self._app_secret = ""

    # ---- dispatcher -----------------------------------------------------

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        ts = time.time()

        if recipient == "manifest":
            return self._tool_manifest(ts)
        if recipient == "event_stats":
            return self._tool_event_stats(ts, params)
        if recipient == "verify_signed_data":
            return self._tool_verify_signed_data(ts, params)
        if recipient == "record_event":
            return self._tool_record_event(ts, params)

        return SendResult(
            success=False, crystal_id="", service=self.SERVICE,
            recipient=recipient, message_preview="",
            timestamp=ts,
            error=f"unknown_tool:{recipient}",
            metadata={"expected_tools": list(EXPECTED_TOOLS)},
        )

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        log_path = Path.home() / ".cc" / "third_party_logs" / "fb_instant_games_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Tool implementations ------------------------------------------

    def _tool_manifest(self, ts: float) -> SendResult:
        """Return the SDK_MANIFEST as a compact JSON in message_preview."""
        entries = [
            {"key": k,
             "js_call": v["js_call"],
             "scope_required": v["scope_required"],
             "server_event_name": v["server_event_name"],
             "description": v["description"]}
            for k, v in SDK_MANIFEST.items()
        ]
        body = {
            "service": self.SERVICE,
            "entry_count": len(entries),
            "entries": entries,
        }
        return SendResult(
            success=True, crystal_id="", service=self.SERVICE,
            recipient="manifest",
            message_preview=json.dumps(body, separators=(",", ":"))[:8192],
            timestamp=ts,
            error="",
            metadata={"entry_count": len(entries),
                       "tool_keys": list(SDK_MANIFEST.keys())},
        )

    def _tool_event_stats(self, ts: float, params: Dict[str, Any]) -> SendResult:
        """Count events in the event sink by event_name (optionally since ts)."""
        since_ts = params.get("since_ts")
        try:
            since_ts_f = float(since_ts) if since_ts is not None else None
        except (TypeError, ValueError):
            since_ts_f = None
        counts: Dict[str, int] = {}
        total = 0
        first_ts: Optional[float] = None
        last_ts: Optional[float] = None
        if EVENT_SINK_PATH.exists():
            try:
                for ln in EVENT_SINK_PATH.read_text(encoding="utf-8").splitlines():
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        rec = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    rec_ts = rec.get("ts")
                    try:
                        rec_ts_f = float(rec_ts) if rec_ts is not None else None
                    except (TypeError, ValueError):
                        rec_ts_f = None
                    if since_ts_f is not None and rec_ts_f is not None and rec_ts_f < since_ts_f:
                        continue
                    name = rec.get("event_name", "_unknown")
                    counts[name] = counts.get(name, 0) + 1
                    total += 1
                    if rec_ts_f is not None:
                        if first_ts is None or rec_ts_f < first_ts:
                            first_ts = rec_ts_f
                        if last_ts is None or rec_ts_f > last_ts:
                            last_ts = rec_ts_f
            except Exception as e:
                return SendResult(
                    success=False, crystal_id="", service=self.SERVICE,
                    recipient="event_stats", message_preview="",
                    timestamp=ts,
                    error=f"{type(e).__name__}: {e}",
                    metadata={"sink_path": str(EVENT_SINK_PATH)},
                )
        body = {
            "total": total,
            "by_event_name": counts,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "sink_path": str(EVENT_SINK_PATH),
            "since_ts": since_ts_f,
        }
        return SendResult(
            success=True, crystal_id="", service=self.SERVICE,
            recipient="event_stats",
            message_preview=json.dumps(body, separators=(",", ":"))[:2048],
            timestamp=ts,
            error="",
            metadata={"total": total, "distinct_events": len(counts)},
        )

    def _tool_verify_signed_data(self, ts: float,
                                  params: Dict[str, Any]) -> SendResult:
        """Verify a signed_player_info string against an app secret."""
        signed = (params.get("signed_player_info")
                   or params.get("signed_data")
                   or "")
        secret = (params.get("fb_app_secret")
                   or self._app_secret
                   or _load_app_secret())
        result = verify_signed_data(signed, secret)
        ok = bool(result.get("valid"))
        return SendResult(
            success=ok, crystal_id="", service=self.SERVICE,
            recipient="verify_signed_data",
            message_preview=json.dumps(result, separators=(",", ":"))[:512],
            timestamp=ts,
            error="" if ok else result.get("error", "invalid"),
            metadata={
                "valid": ok,
                "player_id": result.get("player_id", ""),
                "request_payload_preview": str(result.get("request_payload", ""))[:120],
                "issued_at": result.get("issued_at"),
            },
        )

    def _tool_record_event(self, ts: float,
                            params: Dict[str, Any]) -> SendResult:
        """Primary entry — called by the JS SDK via /dapp/api/fb_event POST.
        Records the event, crystal-anchors it, optionally hands off friends list."""
        event_name = (params.get("event_name") or "").strip()
        player_id = (params.get("player_id") or "").strip()
        context_id = (params.get("context_id") or "").strip()
        signed_data = params.get("signed_data") or ""
        payload = params.get("payload") or {}

        if not event_name:
            return SendResult(
                success=False, crystal_id="", service=self.SERVICE,
                recipient="record_event", message_preview="",
                timestamp=ts,
                error="missing event_name",
                metadata={"expected_event_names":
                              [v["server_event_name"] for v in SDK_MANIFEST.values()]},
            )

        # Optional HMAC verify when both signed_data and app secret present.
        signed_valid = False
        signed_meta: Dict[str, Any] = {}
        if signed_data:
            secret = self._app_secret or _load_app_secret()
            if secret:
                v = verify_signed_data(signed_data, secret)
                signed_valid = bool(v.get("valid"))
                signed_meta = {
                    "signed_valid": signed_valid,
                    "signed_player_id": v.get("player_id", ""),
                    "signed_issued_at": v.get("issued_at"),
                    "signed_error": v.get("error", "") if not signed_valid else "",
                }
                # If FB tells us a player_id and the caller provided one, prefer
                # the FB-asserted one ONLY when it differs — and surface the diff.
                fb_pid = v.get("player_id", "")
                if signed_valid and fb_pid and player_id and fb_pid != player_id:
                    signed_meta["player_id_mismatch"] = {
                        "claimed": player_id, "signed": fb_pid,
                    }
            else:
                signed_meta = {"signed_valid": False,
                                 "signed_error": "no_app_secret_to_verify"}

        # Crystal-anchor.
        t0 = time.time()
        payload_summary = _summarize_payload(payload)
        crystal_id = _log_fb_event(
            event_name=event_name,
            player_id=player_id,
            context_id=context_id,
            payload_summary=payload_summary,
            signed_valid=signed_valid,
            latency_ms=int((time.time() - t0) * 1000),
        )

        # Friends-list hand-off (agent B).
        handoff_meta: Dict[str, Any] = {}
        if event_name == "instant.friends.list_pulled":
            handoff_meta = _handoff_friends_to_graph(
                player_id=player_id,
                payload=payload if isinstance(payload, dict) else {},
                crystal_id=crystal_id,
            )

        # Append to event sink.
        record = {
            "ts": ts,
            "event_name": event_name,
            "player_id": player_id,
            "context_id": context_id,
            "signed_valid": signed_valid,
            "payload_summary": payload_summary,
            "crystal_id": crystal_id,
        }
        if handoff_meta:
            record["handoff"] = handoff_meta
        _append_event_sink(record)

        # Build SendResult.
        preview = {
            "event_name": event_name,
            "player_id": player_id[:32],
            "context_id": context_id[:32],
            "signed_valid": signed_valid,
            "crystal": crystal_id[:24],
        }
        metadata: Dict[str, Any] = {
            "event_name": event_name,
            "in_manifest": event_name in {v["server_event_name"]
                                              for v in SDK_MANIFEST.values()},
            "sink_path": str(EVENT_SINK_PATH),
        }
        metadata.update(signed_meta)
        if handoff_meta:
            metadata["friends_handoff"] = handoff_meta

        return SendResult(
            success=True, crystal_id=crystal_id, service=self.SERVICE,
            recipient="record_event",
            message_preview=json.dumps(preview, separators=(",", ":"))[:512],
            timestamp=ts,
            error="",
            metadata=metadata,
        )

    # ---- Free-tier token gate helper -----------------------------------

    @staticmethod
    def verify_dapp_token(token: str,
                           expected_domain: Optional[str] = None) -> bool:
        """Wrapper around core/lib/freetier_gate.verify_token so the dApp
        handler can bearer-gate every /dapp/api/fb_event POST with one call.

        Returns True iff the token is valid + non-expired (+ optionally
        scoped to expected_domain). Never raises.
        """
        try:
            from freetier_gate import verify_token  # type: ignore
            claims = verify_token(token, expected_domain=expected_domain)
            return claims is not None
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Public helpers — also usable without instantiating the connector
# ---------------------------------------------------------------------------

def manifest() -> Dict[str, Any]:
    """Return the SDK_MANIFEST as a plain dict (for studio/dapp + Godot HTML5)."""
    return dict(SDK_MANIFEST)


def event_stats(since_ts: Optional[float] = None) -> Dict[str, Any]:
    """Count events in ~/.cc/fb_instant_events.jsonl by event_name."""
    c = FBInstantGamesConnector()
    r = c.send("event_stats", json.dumps({"since_ts": since_ts}))
    try:
        return json.loads(r.message_preview)
    except Exception:
        return {"_error": r.error or "stats_failed"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="fb_instant_games — Facebook Instant Games JS SDK companion")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect", help="report connect status (keys present?)")
    sub.add_parser("manifest", help="print the SDK_MANIFEST")
    sub.add_parser("stats", help="event-sink counts by event_name")
    p_rec = sub.add_parser("record", help="manually record one event")
    p_rec.add_argument("event_name")
    p_rec.add_argument("--player-id", default="cli_player")
    p_rec.add_argument("--context-id", default="SOLO")
    p_rec.add_argument("--signed-data", default="")
    p_rec.add_argument("--payload", default="{}",
                          help="JSON-encoded payload dict")
    p_ver = sub.add_parser("verify-signed",
                              help="verify a signed_player_info string locally")
    p_ver.add_argument("signed_data")
    p_ver.add_argument("--app-secret", default="")
    sub.add_parser("providers", help="list expected tools + env vars")

    args = ap.parse_args()
    c = FBInstantGamesConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({
            "connected": ok,
            "has_app_id": bool(c._app_id),
            "has_app_secret": bool(c._app_secret),
            "sink_path": str(EVENT_SINK_PATH),
            "manifest_entries": len(SDK_MANIFEST),
        }, indent=2))

    elif args.cmd == "manifest":
        r = c.send("manifest", "")
        try:
            body = json.loads(r.message_preview)
        except Exception:
            body = {"_error": "manifest decode failed"}
        print(json.dumps(body, indent=2))

    elif args.cmd == "stats":
        r = c.send("event_stats", "")
        print(r.message_preview)

    elif args.cmd == "record":
        try:
            pl = json.loads(args.payload)
        except json.JSONDecodeError:
            pl = {"_raw": args.payload}
        r = c.send("record_event", json.dumps({
            "event_name": args.event_name,
            "player_id": args.player_id,
            "context_id": args.context_id,
            "signed_data": args.signed_data,
            "payload": pl,
        }))
        print(json.dumps({"success": r.success,
                            "preview": r.message_preview,
                            "metadata": r.metadata,
                            "crystal": r.crystal_id[:24],
                            "error": r.error}, indent=2))

    elif args.cmd == "verify-signed":
        secret = args.app_secret or _load_app_secret()
        r = c.send("verify_signed_data", json.dumps({
            "signed_player_info": args.signed_data,
            "fb_app_secret": secret,
        }))
        print(json.dumps({"success": r.success,
                            "preview": r.message_preview,
                            "metadata": r.metadata,
                            "error": r.error}, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "env_vars": ["FB_APP_ID", "FB_APP_SECRET"],
            "manifest_entries": len(SDK_MANIFEST),
            "manifest_keys": list(SDK_MANIFEST.keys()),
            "sink_path": str(EVENT_SINK_PATH),
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
