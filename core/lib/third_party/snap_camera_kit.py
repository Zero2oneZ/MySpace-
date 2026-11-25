#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        snap_camera_kit
# role:        CONNECTOR · SNAP_AR_LENS_SURFACE
# tier:        L0
# substrate:   AR camera surface — Snapchat Lens (deeplink + Lens Studio bridge)
# storage:     ~/.cc/third_party_logs/snap_camera_kit_sends.jsonl + crystal chain
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.snap_camera_kit.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/dapp/server.py /dapp/api/snap_event (external POST → record_lens_event)
#   - core/cc.sh::cmd_snap_test  /  cmd_snap_publish
#   - studio_runtime (when pass.engine='cloud' and provider='snap_camera_kit')
#   - identity_resolver (per-persona lens routing → lens_deeplink_url)
# outbound:
#   - https://kit.snapchat.com/v1/lenses?group_id=<id>   (list)
#   - snapchat://camera?lens=<id>&hint=<persona>          (deeplink — client-side)
#   - subprocess `lenstudio-cli publish` (when binary in PATH)
#   - inference_logger.log (tier='social_event', model='snap_camera_kit')
# substrate touch:
#   - reads:  SNAP_LENS_GROUP_ID + SNAP_LENS_API_KEY via keys.load_env
#   - reads:  LENSSTUDIO_CLI_PATH env (optional override for Lens Studio CLI)
#   - writes: send_log entries + crystal chain social_event records
# ----------------------------------------------------------------------------
# EVENT KINDS (record_lens_event)
# ----------------------------------------------------------------------------
#   lens_opened    — user tapped the deeplink, Snap launched with our lens
#   snap_recorded  — user recorded a snap with the lens applied
#   snap_shared    — user shared the recorded snap (story/dm)
#   lens_swiped    — user swiped the lens away (engagement signal)
# ============================================================================
"""snap_camera_kit.py — Snap Camera Kit Lens connector.

Mirrors third_party/stripe_mcp.py + third_party/deepseek_mcp.py shape exactly.
SERVICE = "snap_camera_kit". Stdlib only — urllib for HTTPS, subprocess for the
optional lenstudio-cli probe.

Snap Camera Kit lets our app open Snapchat's AR Lens via a deeplink (or wrapped
iframe). The user sees their camera + the lens overlay. From our backend we
manage: lens metadata, Lens Studio publish bridge, per-viewer lens routing
(one lens variant per identity_resolver persona), and event-pickup when the
user records / shares / swipes the lens.

Tools (via send(recipient=tool_name, message=json_args, **kwargs)):
  - lens_deeplink_url(lens_id, viewer_persona_id='')
  - list_lenses(group_id)
  - publish_lens(lens_json_path, group_id)
  - record_lens_event(lens_id, viewer_id, event_kind, payload)
  - verify_credentials()

Every record_lens_event call crystal-anchors via inference_logger.log with
tier='social_event', model='snap_camera_kit', scope='snap_lens_event'. The
viewer_persona_id is folded into source_file so later queries can compute
per-persona engagement (e.g. which persona variant of a lens drives the most
snap_recorded events).

lenstudio-cli install path: download Lens Studio from
https://ar.snap.com/download (macOS/Win desktop app). The CLI is bundled in
the app's resources dir; symlink or add to PATH, or set LENSSTUDIO_CLI_PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

SNAP_API_ROOT = "https://kit.snapchat.com"
SNAP_DEEPLINK_SCHEME = "snapchat://camera"
EXPECTED_TOOLS = (
    "lens_deeplink_url",
    "list_lenses",
    "publish_lens",
    "record_lens_event",
    "verify_credentials",
    "live_mocap_stream",
    "face_track_frame",
)

# ---------------------------------------------------------------------------
# Mocap sink config (Snap Lens → local relay → JSONL → this connector)
# ---------------------------------------------------------------------------
SNAP_MOCAP_SINK_ENV = "SNAP_MOCAP_SINK"
SNAP_MOCAP_SINK_DEFAULT = str(Path.home() / ".cc" / "snap_lens_mocap.jsonl")


def _resolve_mocap_sink() -> Path:
    """Path the local relay writes Snap Lens mocap frames to. Override via
    SNAP_MOCAP_SINK env."""
    override = os.environ.get(SNAP_MOCAP_SINK_ENV, "").strip()
    return Path(override) if override else Path(SNAP_MOCAP_SINK_DEFAULT)


# ---------------------------------------------------------------------------
# TEXT-PLACEHOLDER — Snap Studio Lens + local relay (Tom: wire this up later)
# ---------------------------------------------------------------------------
# The runtime hop for live_mocap_stream / face_track_frame is:
#
#   [Snap Lens Studio Lens] --fetch()--> [local relay HTTP] --append--> [JSONL sink]
#                                                                          ^
#                                                                          |
#                                                       this connector reads here
#
# 1. SNAP STUDIO LENS (to be authored in Lens Studio desktop app)
#    -------------------------------------------------------------
#    Add a Snap Studio Lens project named "mspc_mocap_relay" that:
#      a. Enables BodyTracking + FaceTracking components.
#      b. On each Tick, builds a row:
#           {
#             "ts": getTime(),                      // seconds since lens start
#             "pose_keypoints": {                   // SNAP_BODYTRACK joint names
#               "pelvis": [x,y,z], "spine":[...], "chest":[...], "neck":[...],
#               "head":[...], "leftShoulder":[...], "leftElbow":[...],
#               "leftWrist":[...], "rightShoulder":[...], "rightElbow":[...],
#               "rightWrist":[...], "leftHip":[...], "leftKnee":[...],
#               "leftAnkle":[...], "rightHip":[...], "rightKnee":[...],
#               "rightAnkle":[...]
#             },
#             "face_blendshapes": {                 // ARKit blendshape names
#               "jawOpen": 0..1, "eyeBlinkLeft": 0..1, ...
#             },
#             "lens_id": "<this lens id>",
#             "anchor_uuids": [<XR_FB_spatial_entity 32-hex strings>]
#           }
#      c. Posts the row via fetch() to the LOCAL RELAY:
#           POST http://127.0.0.1:7787/snap_mocap
#           Content-Type: application/json
#         (network permission in the Lens project settings: allow
#          http://127.0.0.1:7787 in the connected-domains list.)
#
# 2. LOCAL RELAY (tiny Python/Node HTTP listener — separate process)
#    --------------------------------------------------------------
#    Listens on 127.0.0.1:7787, appends each posted JSON row as one line to
#    the path returned by _resolve_mocap_sink() (default
#    ~/.cc/snap_lens_mocap.jsonl). The relay is intentionally NOT part of
#    this connector — keep the hop explicit so a relay restart doesn't
#    crash the connector and vice versa.
#
# 3. THIS CONNECTOR
#    --------------
#    live_mocap_stream(p) tails the sink from p["cursor"] (or beginning)
#    and returns {frames: [...], cursor: <last_ts>}.
#    face_track_frame(p) returns just the latest face_blendshapes dict.
#
# Until the Lens + relay are wired, both tools return empty frames lists —
# they are sink-shape agnostic and degrade gracefully on a missing file.
# ---------------------------------------------------------------------------
EVENT_KINDS = ("lens_opened", "snap_recorded", "snap_shared", "lens_swiped")


# ---------------------------------------------------------------------------
# Key + path resolution
# ---------------------------------------------------------------------------

def _load_env() -> Dict[str, str]:
    """Resolve env via studio/auth/keys.load_env (mirrored .env)."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import load_env  # type: ignore
        return dict(load_env())
    except Exception:
        return {}


def _load_group_id() -> str:
    env = _load_env()
    return env.get("SNAP_LENS_GROUP_ID", "") or os.environ.get("SNAP_LENS_GROUP_ID", "")


def _load_api_key() -> str:
    env = _load_env()
    return env.get("SNAP_LENS_API_KEY", "") or os.environ.get("SNAP_LENS_API_KEY", "")


def _resolve_lenstudio_cli() -> str:
    """Return path to lenstudio-cli, or '' if not found.
    Order: $LENSSTUDIO_CLI_PATH env → which('lenstudio-cli') → empty."""
    override = os.environ.get("LENSSTUDIO_CLI_PATH", "").strip()
    if override and Path(override).is_file() and os.access(override, os.X_OK):
        return override
    found = shutil.which("lenstudio-cli")
    return found or ""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_get(url: str, headers: Dict[str, str], timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_social_event(tool: str, params: Dict[str, Any], result: Dict[str, Any],
                       latency_ms: int, status_code: int) -> str:
    """Append one InferenceRecord with tier='social_event', model='snap_camera_kit'.
    viewer_persona_id (when present) is folded into source_file for per-persona
    engagement queries. Returns crystal_id (empty string if logger unavailable)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        persona_id = (params.get("viewer_persona_id", "")
                      or params.get("payload", {}).get("viewer_persona_id", "")
                      if isinstance(params.get("payload"), dict) else "") or ""
        viewer_id = params.get("viewer_id", "")
        # source_file folds persona+viewer for per-persona engagement aggregation.
        source_file = f"snap:{params.get('lens_id', '')}|persona:{persona_id}|viewer:{viewer_id}"
        crystal_id = il.log(
            original_prompt=f"snap_camera_kit.{tool}",
            enhanced_prompt=json.dumps({k: v for k, v in params.items()
                                          if k in ("lens_id", "viewer_id",
                                                    "viewer_persona_id",
                                                    "event_kind", "group_id")},
                                         separators=(",", ":"))[:512],
            output_text=json.dumps({k: v for k, v in result.items()
                                      if k in ("id", "status", "event_kind",
                                                "deeplink", "lens_count")},
                                     separators=(",", ":"))[:512],
            tier="social_event", model="snap_camera_kit",
            scope="snap_lens_event",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_file=source_file,
            source_action=f"snap_camera_kit.{tool}",
            done_flag=(200 <= status_code < 300),
            rc=0 if 200 <= status_code < 300 else 1,
        )
        return crystal_id or ""
    except Exception as e:
        sys.stderr.write(f"warn: snap_camera_kit crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Snap-row → canonical MocapFrame helper
# ---------------------------------------------------------------------------

def frames_to_mocap(jsonl_rows: list, source_id: str) -> list:
    """Convert a list of Snap-side JSONL rows (the shape posted by the Snap
    Studio Lens — see TEXT-PLACEHOLDER at module top) into canonical
    MocapFrame objects using mocap_frame.frame_from_raw with
    mapping_kind='snap_bodytrack'.

    Each row is expected to look like:
      {"ts": <float>, "pose_keypoints": {<snap joint>: [x,y,z], ...},
       "face_blendshapes": {<arkit name>: 0..1, ...},
       "lens_id": <str>, "anchor_uuids": [<32-hex or dashed-uuid>, ...]}

    Rows missing pose_keypoints are skipped. The capture_method is fixed to
    'snap_lens_bodytrack' so downstream registries can route correctly.
    """
    # Local import — keep module import cheap when the caller only needs
    # the connector (not the canonical frames).
    from mocap_frame import frame_from_raw  # type: ignore

    out: list = []
    for row in jsonl_rows or []:
        if not isinstance(row, dict):
            continue
        raw = row.get("pose_keypoints") or {}
        if not isinstance(raw, dict) or not raw:
            continue
        try:
            ts_val = float(row.get("ts", 0.0) or 0.0)
        except (TypeError, ValueError):
            ts_val = 0.0
        fb = row.get("face_blendshapes") or {}
        if not isinstance(fb, dict):
            fb = {}
        anchors = row.get("anchor_uuids") or []
        if not isinstance(anchors, list):
            anchors = []
        try:
            frame = frame_from_raw(
                raw,
                source_id=source_id,
                capture_method="snap_lens_bodytrack",
                mapping_kind="snap_bodytrack",
                anchor_uuids=[str(a) for a in anchors],
                face_blendshapes={str(k): float(v) for k, v in fb.items()
                                    if isinstance(v, (int, float))},
                ts=ts_val if ts_val > 0 else None,
            )
            out.append(frame)
        except Exception as e:
            sys.stderr.write(
                f"warn: frames_to_mocap skipped row: {type(e).__name__}: {e}\n")
            continue
    return out


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------

class SnapCameraKitConnector(ThirdPartyConnector):
    """Snap Camera Kit AR Lens connector — deeplink, Lens Studio bridge, event pickup."""

    SERVICE = "snap_camera_kit"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="snap_camera_kit_default",
                action="ar_lens_surface",
            )
        super().__init__(config)
        self._api_key = ""
        self._group_id = ""
        self._connected = False

    # ---- lifecycle ------------------------------------------------------

    def connect(self) -> bool:
        """Resolve keys + group id. We do NOT call the Snap API on connect()
        because record_lens_event + lens_deeplink_url work without an API key
        (the dApp posts events to us; we build local deeplinks). Returns True
        when at least a group id is present OR the connector is usable in
        stub mode."""
        self._api_key = _load_api_key()
        self._group_id = _load_group_id()
        # Always connectable — deeplink + record_lens_event work without keys.
        # list_lenses / publish_lens degrade gracefully when keys/cli missing.
        self._connected = True
        return True

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        """recipient = tool name; message = JSON args (preferred) or empty if kwargs."""
        if not self._connected and not self.connect():
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                crystal_id="",
                error="snap_camera_kit_not_connected",
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
        if recipient == "lens_deeplink_url":
            status, body = self._lens_deeplink_url(params)
        elif recipient == "list_lenses":
            status, body = self._list_lenses(params)
        elif recipient == "publish_lens":
            status, body = self._publish_lens(params)
        elif recipient == "record_lens_event":
            status, body = self._record_lens_event(params)
        elif recipient == "verify_credentials":
            status, body = self._verify_credentials()
        elif recipient == "live_mocap_stream":
            status, body = self._live_mocap_stream(params)
        elif recipient == "face_track_frame":
            status, body = self._face_track_frame(params)
        else:
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.time(),
                crystal_id="",
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )

        latency_ms = int((time.time() - t0) * 1000)
        success = 200 <= status < 300

        # Crystal-anchor every record_lens_event (success or not — engagement
        # is observable even when the event handler 4xx's).
        crystal_id = ""
        if recipient == "record_lens_event":
            crystal_id = _log_social_event(recipient, params, body, latency_ms, status)

        preview = (
            body.get("deeplink", "")
            or body.get("id", "")
            or body.get("status", "")
            or body.get("event_kind", "")
            or str(body)[:200]
        )

        return SendResult(
            success=success, service=self.SERVICE, recipient=recipient,
            message_preview=str(preview)[:200], timestamp=time.time(),
            crystal_id=crystal_id,
            error="" if success else (body.get("_error", "") or f"snap_status_{status}"),
            metadata={
                "status_code": status, "latency_ms": latency_ms,
                "lens_id": params.get("lens_id", ""),
                "viewer_id": params.get("viewer_id", ""),
                "viewer_persona_id": params.get("viewer_persona_id", ""),
                "event_kind": params.get("event_kind", ""),
                "group_id": params.get("group_id", "") or self._group_id,
                "deeplink": body.get("deeplink", ""),
                "lens_count": body.get("lens_count", 0),
            },
        )

    def history(self, limit: int = 20) -> list:
        log_path = Path.home() / ".cc" / "third_party_logs" / "snap_camera_kit_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Tool implementations ------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

    def _lens_deeplink_url(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Build snapchat://camera?lens=<id>&hint=<persona> deeplink. No HTTP call."""
        lens_id = p.get("lens_id", "")
        if not lens_id:
            return 400, {"_error": "missing lens_id"}
        viewer_persona_id = p.get("viewer_persona_id", "")
        qs: Dict[str, str] = {"lens": lens_id}
        if viewer_persona_id:
            qs["hint"] = viewer_persona_id
        deeplink = f"{SNAP_DEEPLINK_SCHEME}?{urllib.parse.urlencode(qs)}"
        return 200, {"deeplink": deeplink, "lens_id": lens_id,
                       "viewer_persona_id": viewer_persona_id}

    def _list_lenses(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """GET /v1/lenses?group_id=<id>. Returns stub when no key configured."""
        group_id = p.get("group_id", "") or self._group_id
        if not group_id:
            return 400, {"_error": "missing group_id"}
        if not self._api_key:
            # Stub mode — no key, return deterministic empty-but-shaped payload.
            return 200, {"lens_count": 0, "lenses": [], "group_id": group_id,
                           "_stub": "no SNAP_LENS_API_KEY"}
        url = f"{SNAP_API_ROOT}/v1/lenses?{urllib.parse.urlencode({'group_id': group_id})}"
        status, body = _http_get(url, self._auth_headers(), timeout=15)
        if 200 <= status < 300 and isinstance(body, dict):
            body.setdefault("lens_count", len(body.get("lenses", []) or []))
            body.setdefault("group_id", group_id)
        return status, body

    def _publish_lens(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Subprocess `lenstudio-cli publish <json> --group <id>`. Returns
        404-style error when the CLI is not on PATH (graceful degrade)."""
        lens_json_path = p.get("lens_json_path", "")
        group_id = p.get("group_id", "") or self._group_id
        if not lens_json_path:
            return 400, {"_error": "missing lens_json_path"}
        if not group_id:
            return 400, {"_error": "missing group_id"}
        if not Path(lens_json_path).exists():
            return 400, {"_error": f"lens_json_path not found: {lens_json_path}"}
        cli = _resolve_lenstudio_cli()
        if not cli:
            return 404, {"_error": "lenstudio_cli_not_found",
                          "hint": "install Lens Studio + symlink lenstudio-cli, or set LENSSTUDIO_CLI_PATH"}
        try:
            proc = subprocess.run(
                [cli, "publish", lens_json_path, "--group", group_id],
                capture_output=True, timeout=120,
            )
            out_txt = proc.stdout.decode("utf-8", errors="replace")
            err_txt = proc.stderr.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                return 500, {"_error": "lenstudio_cli_failed",
                              "exit": proc.returncode,
                              "stderr": err_txt[-2048:],
                              "stdout": out_txt[-512:]}
            # Try to parse JSON tail (CLI typically prints {"id": "lens_..."} last)
            tail_json: Dict[str, Any] = {}
            for ln in reversed(out_txt.strip().splitlines()):
                ln = ln.strip()
                if ln.startswith("{") and ln.endswith("}"):
                    try:
                        tail_json = json.loads(ln)
                        break
                    except json.JSONDecodeError:
                        continue
            result = {"status": "published", "group_id": group_id,
                       "stdout_tail": out_txt[-512:]}
            result.update(tail_json)
            return 200, result
        except subprocess.TimeoutExpired:
            return 504, {"_error": "lenstudio_cli_timeout"}
        except Exception as e:
            return 500, {"_error": f"{type(e).__name__}: {e}"}

    def _record_lens_event(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """External POST from our dApp (/dapp/api/snap_event) lands here.
        We do NOT call Snap — we crystal-anchor the event and return a receipt.
        The crystal anchor is created in send() after this returns."""
        lens_id = p.get("lens_id", "")
        viewer_id = p.get("viewer_id", "")
        event_kind = p.get("event_kind", "")
        payload = p.get("payload", {})
        if not lens_id:
            return 400, {"_error": "missing lens_id"}
        if not viewer_id:
            return 400, {"_error": "missing viewer_id"}
        if event_kind not in EVENT_KINDS:
            return 400, {"_error": f"unknown event_kind: {event_kind}",
                          "expected": list(EVENT_KINDS)}
        if payload is not None and not isinstance(payload, dict):
            return 400, {"_error": "payload must be object"}
        # Receipt — crystal_id stamped by send() wrapper.
        return 200, {
            "status": "recorded",
            "lens_id": lens_id,
            "viewer_id": viewer_id,
            "event_kind": event_kind,
            "payload_keys": sorted(list((payload or {}).keys())),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _verify_credentials(self) -> Tuple[int, Dict[str, Any]]:
        """Keys-present check. Does NOT call Snap (free, deterministic)."""
        return 200, {
            "status": "checked",
            "has_group_id": bool(self._group_id),
            "has_api_key": bool(self._api_key),
            "has_lenstudio_cli": bool(_resolve_lenstudio_cli()),
            "group_id": self._group_id,
        }

    # ---- Live mocap tools ----------------------------------------------
    # See TEXT-PLACEHOLDER at module top for the runtime hop:
    #   Snap Lens --fetch()--> local relay --append--> JSONL sink --> here
    # Both tools read the JSONL sink at _resolve_mocap_sink(); the relay is
    # a separate, out-of-process daemon (not part of this connector).

    def _read_sink_rows(self) -> Tuple[Path, list]:
        """Load every JSONL row from the sink. Missing file → []. Bad lines
        are skipped silently so a half-written tail doesn't poison the read."""
        sink = _resolve_mocap_sink()
        if not sink.exists():
            return sink, []
        rows: list = []
        try:
            for ln in sink.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
        except Exception:
            return sink, []
        return sink, rows

    def _live_mocap_stream(self, p: Dict[str, Any]) -> Tuple[int, Any]:
        """Return all sink rows whose ts > cursor (default 0.0). Result shape:
          {frames: [<raw row dict>...], cursor: <last_ts seen>, sink: <path>}
        Callers feed `frames` into frames_to_mocap() to get MocapFrame objects.
        """
        try:
            cursor = float(p.get("cursor", 0.0) or 0.0)
        except (TypeError, ValueError):
            cursor = 0.0
        sink, rows = self._read_sink_rows()
        out: list = []
        last_ts = cursor
        for r in rows:
            try:
                ts = float(r.get("ts", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if ts > cursor:
                out.append(r)
                if ts > last_ts:
                    last_ts = ts
        return 200, {
            "frames": out,
            "cursor": last_ts,
            "sink": str(sink),
            "frame_count": len(out),
        }

    def _face_track_frame(self, p: Dict[str, Any]) -> Tuple[int, Any]:
        """Return the most recent ARKit-normalized face_blendshapes dict
        from the sink. Empty dict when sink missing or has no face data.
        Shape:
          {face_blendshapes: {<arkit name>: 0..1, ...}, ts: <float>,
           lens_id: <str>, sink: <path>}
        """
        sink, rows = self._read_sink_rows()
        latest_ts = -1.0
        latest_face: Dict[str, float] = {}
        latest_lens = ""
        for r in rows:
            fb = r.get("face_blendshapes")
            if not isinstance(fb, dict):
                continue
            try:
                ts = float(r.get("ts", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if ts > latest_ts:
                latest_ts = ts
                latest_face = {str(k): float(v) for k, v in fb.items()
                                if isinstance(v, (int, float))}
                latest_lens = str(r.get("lens_id", "") or "")
        return 200, {
            "face_blendshapes": latest_face,
            "ts": latest_ts if latest_ts >= 0 else 0.0,
            "lens_id": latest_lens,
            "sink": str(sink),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="snap_camera_kit — Snap AR Lens connector smoke")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")
    sub.add_parser("verify")

    p_dl = sub.add_parser("deeplink")
    p_dl.add_argument("--lens-id", required=True)
    p_dl.add_argument("--persona", default="")

    p_ls = sub.add_parser("list-lenses")
    p_ls.add_argument("--group-id", default="")

    p_pub = sub.add_parser("publish")
    p_pub.add_argument("--lens-json", required=True)
    p_pub.add_argument("--group-id", default="")

    p_ev = sub.add_parser("event")
    p_ev.add_argument("--lens-id", required=True)
    p_ev.add_argument("--viewer-id", required=True)
    p_ev.add_argument("--kind", required=True, choices=list(EVENT_KINDS))
    p_ev.add_argument("--payload", default="{}", help="JSON object")

    sub.add_parser("providers", help="list expected tools + event kinds")

    args = ap.parse_args()
    c = SnapCameraKitConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({
            "connected": ok,
            "has_group_id": bool(c._group_id),
            "has_api_key": bool(c._api_key),
            "has_lenstudio_cli": bool(_resolve_lenstudio_cli()),
        }, indent=2))

    elif args.cmd == "verify":
        c.connect()
        r = c.send("verify_credentials", "")
        print(json.dumps({"success": r.success, "preview": r.message_preview,
                            "metadata": r.metadata, "error": r.error}, indent=2))

    elif args.cmd == "deeplink":
        c.connect()
        r = c.send("lens_deeplink_url",
                    json.dumps({"lens_id": args.lens_id,
                                  "viewer_persona_id": args.persona}))
        print(json.dumps({"success": r.success, "deeplink": r.message_preview,
                            "error": r.error}, indent=2))

    elif args.cmd == "list-lenses":
        c.connect()
        r = c.send("list_lenses", json.dumps({"group_id": args.group_id}))
        print(json.dumps({"success": r.success, "preview": r.message_preview,
                            "lens_count": r.metadata.get("lens_count", 0),
                            "error": r.error}, indent=2))

    elif args.cmd == "publish":
        c.connect()
        r = c.send("publish_lens",
                    json.dumps({"lens_json_path": args.lens_json,
                                  "group_id": args.group_id}))
        print(json.dumps({"success": r.success, "preview": r.message_preview,
                            "error": r.error}, indent=2))

    elif args.cmd == "event":
        c.connect()
        try:
            payload = json.loads(args.payload)
        except json.JSONDecodeError:
            payload = {"raw": args.payload}
        r = c.send("record_lens_event",
                    json.dumps({"lens_id": args.lens_id,
                                  "viewer_id": args.viewer_id,
                                  "event_kind": args.kind,
                                  "payload": payload}))
        print(json.dumps({"success": r.success, "preview": r.message_preview,
                            "crystal": r.crystal_id[:24] if r.crystal_id else "",
                            "error": r.error}, indent=2))

    elif args.cmd == "providers":
        print(json.dumps({
            "expected_tools": list(EXPECTED_TOOLS),
            "event_kinds": list(EVENT_KINDS),
            "api_root": SNAP_API_ROOT,
            "deeplink_scheme": SNAP_DEEPLINK_SCHEME,
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
