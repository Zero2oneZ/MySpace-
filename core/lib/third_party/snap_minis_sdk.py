#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        snap_minis_sdk
# role:        CONNECTOR · SNAP_MINIS_JS_SDK_COMPANION
# tier:        L0
# substrate:   Server-side companion to the Snapchat Snap Minis JavaScript
#              SDK. Snap Minis is Snapchat's HTML5 mini-app container; the
#              mini loads inside the Snapchat app and accesses host
#              functionality through the `window.snap` global. This connector
#              records every event the JS bridge reports via the dApp
#              /dapp/api/snap_mini_event POST surface, verifies the
#              signedUserInfo HMAC against SNAP_MINI_APP_SECRET, and
#              crystal-anchors every recorded event.
# storage:     ~/.cc/snap_minis_events.jsonl (event sink)
#              ~/.cc/third_party_logs/snap_minis_sends.jsonl (history)
#              ~/.cc/inference_master_chain.jsonl (crystal-anchored mini event)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.snap_minis_sdk.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/dapp/server.py /dapp/api/snap_mini_event POST (JS bridge callback)
#   - Godot HTML5 build embedded in a Snap Mini → same POST surface
#   - core/cc.sh (future: cmd_snap_mini_stats)
# outbound:
#   - inference_logger.log (tier='social_event', model='snap_minis')
#   - core/lib/third_party/facebook_friends_graph (agent B harvester) when
#     event_name == 'mini.friends.list_pulled' — payload is normalized to the
#     FB-instant connected_players shape and forwarded via
#     ingest_friends_list(...) or harvest_for(source='fb_instant', ...).
# substrate touch:
#   - reads:  SNAP_MINI_APP_ID + SNAP_MINI_APP_SECRET from .env (via
#             studio/auth/keys.load_env)
#   - writes: ~/.cc/snap_minis_events.jsonl (append-only event sink)
#   - writes: send_log entries + crystal_chain social_event records
# ----------------------------------------------------------------------------
# THE TWO ROLES
# ----------------------------------------------------------------------------
# 1. Event sink     — record_event() ingests every JS bridge callback POST
# 2. Surface manifest — SDK_MANIFEST documents the ~15 wrapped window.snap.*
#                        calls so studio/dapp + the embedded Godot HTML5 build
#                        know what to call and which server event to expect.
# ============================================================================
"""snap_minis_sdk.py — Snapchat Snap Minis JS SDK server companion.

Mirror of core/lib/third_party/fb_instant_games.py but for Snapchat's Snap
Minis container. Snap Minis are HTML5 mini-apps that load inside Snapchat
via deep-link; they access host functionality (user identity, Bitmoji,
friends, payments, camera lenses, Spectacles AR cast) through the
`window.snap` global. The bridge runs in-browser; this module sits behind
the dApp HTTP surface and:

  1. Records every event the JS bridge reports (via /dapp/api/snap_mini_event).
  2. Verifies the `signed_user_info` HMAC so we can trust the external_id.
  3. Documents the full window.snap.* surface so the embedded Godot HTML5
     build + the studio dApp know which JS calls to wire to which server
     event.

The JS bridge calls our dApp on every meaningful surface action, e.g.::

    fetch('/dapp/api/snap_mini_event', {
        method: 'POST',
        headers: {'Authorization': 'Bearer <freetier-token>'},
        body: JSON.stringify({
            event_name: 'mini.user.identified',
            user_id:    (await snap.user.getUserAsync()).externalId,
            signed_data: '<signedUserInfo from getUserAsync>',
            payload: {...}
        })
    })

The dApp handler verifies the freetier token (core/lib/freetier_gate.py
verify_token), then calls SnapMinisSDKConnector.record_event(...). Every
recorded event is appended to ~/.cc/snap_minis_events.jsonl and crystal
anchored via inference_logger.log(tier='social_event',
model='snap_minis').

When event_name == 'mini.friends.list_pulled', the payload is normalized
to the FB-Instant connected_players shape (Snap returns identical
structural data: id + name + avatar) and handed off to the
facebook_friends_graph harvester (agent B). The handoff is wrapped in
try/except so this module remains useful even if the harvester is not yet
installed — and the friends payload is preserved in the JSONL sink for
later replay.

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - record_event(event_name, user_id, payload, signed_data)
  - verify_signed_data(signed_user_info, app_secret) — pure stdlib hmac
  - manifest()                                       — returns SDK_MANIFEST
  - event_stats(since_ts=None)                       — count by event_name

Env vars (handled gracefully when absent):
  SNAP_MINI_APP_ID     — Snap Kit App ID (used for connect-status check)
  SNAP_MINI_APP_SECRET — App Secret (used to verify signed_user_info HMACs)
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
# SDK surface manifest — documents every window.snap.* JS call we wrap
# ---------------------------------------------------------------------------
# Each entry shape:
#   {
#       "js_call":           "snap.<path>(args)",
#       "scope_required":    "<Snap permission scope or 'none'>",
#       "server_event_name": "mini.<dotted>",
#       "description":       "one-line behavior",
#       "body_schema":       {<expected POST body keys>: "<type>"}
#   }
SDK_MANIFEST: Dict[str, Dict[str, Any]] = {
    "app_initializeAsync": {
        "js_call":           "snap.app.initializeAsync()",
        "scope_required":    "none",
        "server_event_name": "mini.initialized",
        "description":       "Boot the JS bridge; resolves once the Snap container is ready and window.snap is wired.",
        "body_schema":       {"event_name": "str", "user_id": "str?"},
    },
    "app_exitAsync": {
        "js_call":           "snap.app.exitAsync()",
        "scope_required":    "none",
        "server_event_name": "mini.exited",
        "description":       "Request the host to dismiss the mini and return the user to the camera screen.",
        "body_schema":       {"event_name": "str", "user_id": "str?"},
    },
    "user_getUserAsync": {
        "js_call":           "snap.user.getUserAsync()",
        "scope_required":    "user.external_id",
        "server_event_name": "mini.user.identified",
        "description":       "Read the Snap-scoped externalId for this mini (app-scoped, stable per user/mini pair). May include signedUserInfo for HMAC verify.",
        "body_schema":       {"event_name": "str", "user_id": "str", "signed_data": "str?(base64url.base64url)"},
    },
    "user_getFriendListAsync": {
        "js_call":           "snap.user.getFriendListAsync()",
        "scope_required":    "user.friends",
        "server_event_name": "mini.friends.list_pulled",
        "description":       "FRIENDS HARVEST. Returns Snap friends who also use this mini — each entry has externalId + displayName + Bitmoji avatar URL. Handed off to facebook_friends_graph (agent B) via the fb_instant source path.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"friends": "list[{external_id,display_name,bitmoji_avatar_url}]"}},
    },
    "bitmoji_fetchAvatar2D": {
        "js_call":           "snap.bitmoji.fetchAvatar2DAsync(externalId)",
        "scope_required":    "bitmoji.avatar",
        "server_event_name": "mini.bitmoji.fetched",
        "description":       "Fetch the 2D Bitmoji avatar PNG for a given externalId (typically the current user).",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"target_external_id": "str", "avatar_url": "str?"}},
    },
    "bitmoji_presentStickerPicker": {
        "js_call":           "snap.bitmoji.presentStickerPickerAsync()",
        "scope_required":    "bitmoji.avatar",
        "server_event_name": "mini.bitmoji.sticker_picked",
        "description":       "Open the host Bitmoji sticker picker; resolves with the chosen sticker URL once the user taps one.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"sticker_url": "str?"}},
    },
    "context_getEntryAsync": {
        "js_call":           "snap.context.getEntryAsync()",
        "scope_required":    "none",
        "server_event_name": "mini.context.entry_read",
        "description":       "Where did the user launch from? (CAMERA | CHAT | SEARCH | SNAPCODE | SHARED_FROM_FRIEND | …) plus optional entry payload from a shared card.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"entry_point": "str", "entry_data": "object?"}},
    },
    "context_shareAsync": {
        "js_call":           "snap.context.shareAsync(payload)",
        "scope_required":    "none",
        "server_event_name": "mini.shared",
        "description":       "Open the Snap share sheet with a custom image+text payload so the user can send the mini to a friend chat.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"text": "str?", "image": "str?", "deep_link": "str?"}},
    },
    "payments_purchaseAsync": {
        "js_call":           "snap.payments.purchaseAsync(productId)",
        "scope_required":    "payments",
        "server_event_name": "mini.payment_attempted",
        "description":       "Trigger a Snap Payments purchase flow; resolves with a signed receipt.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"product_id": "str", "developer_payload": "str?"}},
    },
    "camera_openLensAsync": {
        "js_call":           "snap.camera.openLensAsync(lensId)",
        "scope_required":    "camera.lens",
        "server_event_name": "mini.camera.lens_opened",
        "description":       "Hand off to the Snap camera with a specific Lens preloaded so the user can capture a Snap in-context.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"lens_id": "str"}},
    },
    "spectacles_castAsync": {
        "js_call":           "snap.spectacles.castAsync(payload)",
        "scope_required":    "spectacles.cast",
        "server_event_name": "mini.spectacles.cast",
        "description":       "Cast an AR payload (Lens scene / overlay) to a paired pair of Spectacles AR glasses for in-world rendering.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"lens_id": "str?", "scene_url": "str?"}},
    },
    "session_getDeviceClass": {
        "js_call":           "snap.session.getDeviceClass()",
        "scope_required":    "none",
        "server_event_name": "mini.session.device_class_read",
        "description":       "Read the perf class of the device hosting the mini: LOW | MID | HIGH. Drives Godot quality tier selection.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"device_class": "str"}},
    },
    "session_onResume": {
        "js_call":           "snap.session.onResume(callback)",
        "scope_required":    "none",
        "server_event_name": "mini.session.resumed",
        "description":       "Lifecycle event — the mini was foregrounded (user returned from camera / chat).",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"resumed_at": "float"}},
    },
    "session_onPause": {
        "js_call":           "snap.session.onPause(callback)",
        "scope_required":    "none",
        "server_event_name": "mini.session.paused",
        "description":       "Lifecycle event — the mini was backgrounded. Persist state before this resolves.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"paused_at": "float"}},
    },
    "creativekit_shareToCamera": {
        "js_call":           "snap.creativekit.shareToCameraAsync(payload)",
        "scope_required":    "creativekit.share",
        "server_event_name": "mini.creative.shared",
        "description":       "Push a media payload (image + caption + attachment URL) directly into the Snap camera composer for the user to send.",
        "body_schema":       {"event_name": "str", "user_id": "str", "payload": {"image": "str?", "caption": "str?", "attachment_url": "str?"}},
    },
}

EXPECTED_TOOLS = (
    "record_event",
    "verify_signed_data",
    "manifest",
    "event_stats",
)

# Event sink — single append-only JSONL.
EVENT_SINK_PATH = Path.home() / ".cc" / "snap_minis_events.jsonl"


# ---------------------------------------------------------------------------
# .env loaders — mirror fb_instant_games pattern
# ---------------------------------------------------------------------------

def _load_env_var(name: str) -> str:
    """Resolve a Snap Minis env var via studio/auth/keys.load_env, then os.environ."""
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
    return _load_env_var("SNAP_MINI_APP_ID")


def _load_app_secret() -> str:
    return _load_env_var("SNAP_MINI_APP_SECRET")


# ---------------------------------------------------------------------------
# signed_user_info verification — stdlib hmac
# ---------------------------------------------------------------------------
# Snap Minis serves signed_user_info as `<sig_b64url>.<payload_b64url>` where:
#   sig     = HMAC_SHA256(app_secret, payload_b64url)
#   payload = base64url-decoded JSON containing:
#             { "algorithm":      "HMAC-SHA256",
#               "issued_at":      <epoch>,
#               "external_id":    "<snap_external_id>",
#               "request_payload": "<echo of getUserAsync arg>" }
#
# This mirrors the Facebook Instant Games signed_player_info wire format
# precisely so both verifiers can share the same parse/verify code path.

def _b64url_decode(s: str) -> bytes:
    """Decode base64url with missing-padding tolerance."""
    pad = 4 - (len(s) % 4)
    if pad and pad < 4:
        s = s + ("=" * pad)
    return base64.urlsafe_b64decode(s.encode("ascii"))


def verify_signed_data(signed_user_info: str,
                       app_secret: str) -> Dict[str, Any]:
    """Verify the Snap Minis signed_user_info HMAC.

    Returns {valid: bool, external_id: str, request_payload: str,
             issued_at: int?, error: str?}.
    Never raises. Pure stdlib (hmac/hashlib/base64/json).
    """
    out: Dict[str, Any] = {
        "valid": False,
        "external_id": "",
        "request_payload": "",
    }
    if not signed_user_info or "." not in signed_user_info:
        out["error"] = "malformed: expected '<sig>.<payload>'"
        return out
    if not app_secret:
        out["error"] = "missing app_secret"
        return out
    try:
        sig_b64, payload_b64 = signed_user_info.split(".", 1)
        expected_sig = hmac.new(
            app_secret.encode("utf-8"),
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
        # Snap uses external_id; some payloads alias it as player_id —
        # accept either, prefer external_id.
        out["external_id"] = (
            payload.get("external_id")
            or payload.get("user_id")
            or payload.get("player_id")
            or ""
        )
        out["request_payload"] = payload.get("request_payload", "")
        out["issued_at"] = int(payload.get("issued_at", 0))
        return out
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_mini_event(event_name: str, user_id: str,
                    payload_summary: Dict[str, Any], signed_valid: bool,
                    latency_ms: int) -> str:
    """Append one InferenceRecord with tier='social_event', model='snap_minis'.
    Returns the crystal_id (or '' if logger unavailable)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        safe_payload = {
            k: v for k, v in payload_summary.items()
            if k not in ("signature", "signed_data", "signed_user_info",
                          "access_token", "purchase_token", "developer_payload",
                          "developerPayload")
        }
        crystal_id = il.log(
            original_prompt=f"snap_mini.{event_name}",
            enhanced_prompt=json.dumps({
                "user_id": user_id,
                "signed_valid": signed_valid,
            }, separators=(",", ":"))[:512],
            output_text=json.dumps(safe_payload, separators=(",", ":"))[:512],
            tier="social_event",
            model="snap_minis",
            scope=f"snap_mini_{event_name}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"snap_mini.{event_name}",
            done_flag=True, rc=0,
        )
        return crystal_id or ""
    except Exception as e:
        sys.stderr.write(
            f"warn: snap_minis crystal log failed: {type(e).__name__}: {e}\n"
        )
        return ""


def _append_event_sink(record: Dict[str, Any]) -> None:
    """Append one record to ~/.cc/snap_minis_events.jsonl (idempotent dir create)."""
    try:
        EVENT_SINK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_SINK_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    except Exception as e:
        sys.stderr.write(
            f"warn: snap_minis event sink write failed: {type(e).__name__}: {e}\n"
        )


def _summarize_payload(payload: Any) -> Dict[str, Any]:
    """Produce a small, redacted summary of a payload for the event-sink log.
    Strips secrets and trims long strings/lists to a single-line size."""
    if not isinstance(payload, dict):
        return {"_raw": str(payload)[:200]}
    out: Dict[str, Any] = {}
    for k, v in payload.items():
        if k in ("signature", "signed_data", "signed_user_info",
                 "access_token", "purchase_token", "developer_payload",
                 "developerPayload"):
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
# Friends-list hand-off — normalize Snap shape → FB-instant shape
# ---------------------------------------------------------------------------
# Snap returns:    [{external_id, display_name, bitmoji_avatar_url}, ...]
# FB Instant uses: [{id, name, picture}, ...]                  (connected_players)
# These are structurally identical — only the key names differ. The friends
# harvester (facebook_friends_graph) accepts source='fb_instant' which
# consumes payload.connected_players. So we normalize and forward.

def _normalize_snap_friends_to_fb_shape(snap_friends: List[Any]
                                          ) -> List[Dict[str, Any]]:
    """Convert [{external_id, display_name, bitmoji_avatar_url}, ...] →
    [{id, name, picture: {data: {url}}}, ...] (FB-Instant connected_players shape)."""
    out: List[Dict[str, Any]] = []
    if not isinstance(snap_friends, list):
        return out
    for f in snap_friends:
        if not isinstance(f, dict):
            continue
        fid = (f.get("external_id") or f.get("externalId")
               or f.get("id") or "")
        fname = (f.get("display_name") or f.get("displayName")
                  or f.get("name") or "")
        favatar = (f.get("bitmoji_avatar_url") or f.get("bitmojiAvatarUrl")
                    or f.get("avatar_url") or f.get("avatarUrl") or "")
        if not fid:
            continue
        entry: Dict[str, Any] = {"id": str(fid), "name": str(fname)}
        if favatar:
            entry["picture"] = {"data": {"url": str(favatar)}}
        out.append(entry)
    return out


def _handoff_friends_to_graph(user_id: str, payload: Dict[str, Any],
                              crystal_id: str) -> Dict[str, Any]:
    """When event_name == 'mini.friends.list_pulled', hand the payload to
    agent B's social_graph harvester. Never raises; returns a status dict
    for the metadata block.

    Two strategies are attempted in order:
      1. ingest_friends_list(player_id, friends, source_crystal) — if exported
         at module top-level (mirrors the fb_instant_games path exactly).
      2. FacebookFriendsGraphConnector.send('harvest_for', ...) with the Snap
         payload normalized to source='fb_instant' connected_players shape
         (since the friends harvester already supports that source kind).
    """
    snap_friends = payload.get("friends") if isinstance(payload, dict) else []
    fb_shape_friends = _normalize_snap_friends_to_fb_shape(snap_friends or [])

    # --- strategy 1: top-level ingest_friends_list (if it exists) ----------
    try:
        try:
            from third_party.facebook_friends_graph import (  # type: ignore
                ingest_friends_list,
            )
        except Exception:
            from facebook_friends_graph import (  # type: ignore
                ingest_friends_list,
            )
        result = ingest_friends_list(
            player_id=user_id,
            friends=fb_shape_friends,
            source_crystal=crystal_id,
        )
        return {"handoff": "facebook_friends_graph",
                "strategy": "ingest_friends_list",
                "status": "ok",
                "source_kind": "snap_mini→fb_instant",
                "friend_count": len(fb_shape_friends),
                "result": result if isinstance(result, dict) else str(result)[:200]}
    except Exception as e1:
        ingest_err = f"{type(e1).__name__}: {e1}"

    # --- strategy 2: FacebookFriendsGraphConnector.send('harvest_for') ----
    try:
        try:
            from third_party.facebook_friends_graph import (  # type: ignore
                FacebookFriendsGraphConnector,
            )
        except Exception:
            from facebook_friends_graph import (  # type: ignore
                FacebookFriendsGraphConnector,
            )
        ffg = FacebookFriendsGraphConnector()
        try:
            ffg.connect()
        except Exception:
            pass
        r = ffg.send("harvest_for", json.dumps({
            "player_id": user_id,
            "source": "fb_instant",
            "payload": {"connected_players": fb_shape_friends},
            "source_crystal": crystal_id,
        }))
        return {"handoff": "facebook_friends_graph",
                "strategy": "harvest_for(source=fb_instant)",
                "status": "ok" if getattr(r, "success", False) else "errored",
                "source_kind": "snap_mini→fb_instant",
                "friend_count": len(fb_shape_friends),
                "crystal": getattr(r, "crystal_id", "")[:24],
                "error": getattr(r, "error", "") or "",
                "ingest_friends_list_error": ingest_err}
    except Exception as e2:
        return {"handoff": "facebook_friends_graph",
                "status": "deferred",
                "source_kind": "snap_mini→fb_instant",
                "friend_count": len(fb_shape_friends),
                "ingest_friends_list_error": ingest_err,
                "harvest_for_error": f"{type(e2).__name__}: {e2}"}


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class SnapMinisSDKConnector(ThirdPartyConnector):
    """Snapchat Snap Minis JS SDK server companion.

    Sits behind the dApp /dapp/api/snap_mini_event POST surface and records
    every event the in-browser JS bridge reports. Verifies signed_user_info
    HMACs. Crystal-anchors every recorded event. Hands friends_list_pulled
    payloads off to facebook_friends_graph (agent B) for graph persistence
    via the source='fb_instant' path after a Snap→FB-shape normalization.

    Connect status reflects whether SNAP_MINI_APP_ID + SNAP_MINI_APP_SECRET
    are present (so verify_signed_data can actually verify). With keys
    absent, record_event still works (signed_valid=False); manifest +
    event_stats are always available.
    """

    SERVICE = "snap_minis"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="snap_minis_default",
                action="event_sink",
            )
        super().__init__(config)
        self._app_id = ""
        self._app_secret = ""
        self._connected = False

    # ---- lifecycle ------------------------------------------------------

    def connect(self) -> bool:
        """Returns True iff both SNAP_MINI_APP_ID and SNAP_MINI_APP_SECRET
        are present. No network call — this connector is purely the inbound
        sink."""
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
        log_path = Path.home() / ".cc" / "third_party_logs" / "snap_minis_sends.jsonl"
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
        """Verify a signed_user_info string against an app secret."""
        signed = (params.get("signed_user_info")
                   or params.get("signed_data")
                   or "")
        secret = (params.get("app_secret")
                   or params.get("snap_mini_app_secret")
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
                "external_id": result.get("external_id", ""),
                "request_payload_preview": str(result.get("request_payload", ""))[:120],
                "issued_at": result.get("issued_at"),
            },
        )

    def _tool_record_event(self, ts: float,
                            params: Dict[str, Any]) -> SendResult:
        """Primary entry — called by the JS bridge via /dapp/api/snap_mini_event
        POST. Records the event, crystal-anchors it, optionally hands off the
        friends list to facebook_friends_graph."""
        event_name = (params.get("event_name") or "").strip()
        user_id = (params.get("user_id")
                    or params.get("external_id")
                    or "").strip()
        signed_data = (params.get("signed_data")
                        or params.get("signed_user_info")
                        or "")
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
                    "signed_external_id": v.get("external_id", ""),
                    "signed_issued_at": v.get("issued_at"),
                    "signed_error": v.get("error", "") if not signed_valid else "",
                }
                # If Snap tells us an external_id and the caller provided one,
                # surface the diff when they don't agree.
                snap_eid = v.get("external_id", "")
                if signed_valid and snap_eid and user_id and snap_eid != user_id:
                    signed_meta["external_id_mismatch"] = {
                        "claimed": user_id, "signed": snap_eid,
                    }
            else:
                signed_meta = {"signed_valid": False,
                                 "signed_error": "no_app_secret_to_verify"}

        # Crystal-anchor.
        t0 = time.time()
        payload_summary = _summarize_payload(payload)
        crystal_id = _log_mini_event(
            event_name=event_name,
            user_id=user_id,
            payload_summary=payload_summary,
            signed_valid=signed_valid,
            latency_ms=int((time.time() - t0) * 1000),
        )

        # Friends-list hand-off (agent B).
        handoff_meta: Dict[str, Any] = {}
        if event_name == "mini.friends.list_pulled":
            handoff_meta = _handoff_friends_to_graph(
                user_id=user_id,
                payload=payload if isinstance(payload, dict) else {},
                crystal_id=crystal_id,
            )

        # Append to event sink.
        record = {
            "ts": ts,
            "event_name": event_name,
            "user_id": user_id,
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
            "user_id": user_id[:32],
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
        handler can bearer-gate every /dapp/api/snap_mini_event POST with one
        call.

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
    """Count events in ~/.cc/snap_minis_events.jsonl by event_name."""
    c = SnapMinisSDKConnector()
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
        description="snap_minis_sdk — Snapchat Snap Minis JS SDK companion")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect", help="report connect status (keys present?)")
    sub.add_parser("manifest", help="print the SDK_MANIFEST")
    sub.add_parser("stats", help="event-sink counts by event_name")
    p_rec = sub.add_parser("record", help="manually record one event")
    p_rec.add_argument("event_name")
    p_rec.add_argument("--user-id", default="cli_user")
    p_rec.add_argument("--signed-data", default="")
    p_rec.add_argument("--payload", default="{}",
                          help="JSON-encoded payload dict")
    p_ver = sub.add_parser("verify-signed",
                              help="verify a signed_user_info string locally")
    p_ver.add_argument("signed_data")
    p_ver.add_argument("--app-secret", default="")
    sub.add_parser("providers", help="list expected tools + env vars")

    args = ap.parse_args()
    c = SnapMinisSDKConnector()

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
            "user_id": args.user_id,
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
            "signed_user_info": args.signed_data,
            "app_secret": secret,
        }))
        print(json.dumps({"success": r.success,
                            "preview": r.message_preview,
                            "metadata": r.metadata,
                            "error": r.error}, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "env_vars": ["SNAP_MINI_APP_ID", "SNAP_MINI_APP_SECRET"],
            "manifest_entries": len(SDK_MANIFEST),
            "manifest_keys": list(SDK_MANIFEST.keys()),
            "sink_path": str(EVENT_SINK_PATH),
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
