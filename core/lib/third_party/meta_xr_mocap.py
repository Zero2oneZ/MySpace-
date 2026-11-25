#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        meta_xr_mocap
# role:        CONNECTOR · META_OPENXR_MOCAP_TAIL
# tier:        L0
# substrate:   Meta OpenXR runtime — Quest 3 / Quest Pro / Ray-Ban Meta
# storage:     ~/.cc/meta_xr_mocap.jsonl (Godot-side append-only sink)
#              ~/.cc/third_party_logs/meta_xr_mocap_sends.jsonl (our log)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.spatial_anchor.active.json
# ----------------------------------------------------------------------------
# OPENXR EXTENSION MAPPING
# ----------------------------------------------------------------------------
#   body_track_frame()  → XR_FB_body_tracking  (Meta full-body skeleton)
#   face_track_frame()  → XR_FB_face_tracking2 (ARKit-52 blend shapes)
#   list_anchors()      → XR_FB_spatial_entity (persistent room anchors)
#   spatial_origin()    → XR_FB_passthrough    (headset → ME LAND origin)
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/godot/project/src/meta_xr_mocap_emit.gd writes the sink jsonl
#   - core/lib/mocap_rig_anchor (consumes MocapFrame stream)
#   - animation_registry (anchors frames to crystal chain)
# outbound:
#   - spatial_anchor.py CoordGraph (ME LAND origin updates)
#   - inference_logger.log (tier='mocap_event', model='meta_xr_mocap')
# ============================================================================
"""meta_xr_mocap.py — Meta XR mocap tail adapter.

Reads MocapFrames that Godot's meta_xr_bridge.gd / meta_xr_mocap_emit.gd
writes to ~/.cc/meta_xr_mocap.jsonl (append-only sink). Mirrors the
ThirdPartyConnector shape exactly (cf. snap_camera_kit.py).

OpenXR extension mapping (Meta Quest 3 / Quest Pro / Ray-Ban Meta):

  XR_FB_body_tracking     — 22-joint Meta Body skeleton (full body on
                            Quest 3/Pro, upper-body-only on Ray-Ban Meta).
                            Surfaces here as body_track_frame() → MocapFrame
                            with joints keyed by META_BODY_JOINTS.

  XR_FB_face_tracking2    — Meta's face tracking v2 (Quest Pro / Quest 3
                            with FaceTracking permission). Normalizes
                            internally to the ARKit 52 blendshape set.
                            Surfaces here as face_track_frame() → dict of
                            {arkit_name: 0..1}.

  XR_FB_spatial_entity    — Persistent spatial anchors (RFC 4122 UUIDs).
                            The "particles we placed long ago" that survive
                            across sessions. Surfaces here as list_anchors()
                            and as MocapFrame.anchor_uuids.

  XR_FB_passthrough       — Color passthrough; gives us the headset's
                            current spatial origin in the room. Surfaces
                            here as spatial_origin() → (x, y, z, heading).

Tools (via send(recipient=tool_name, ...)):
  - body_track_frame()
  - face_track_frame()
  - list_anchors()
  - spatial_origin()

Stdlib only. Reads JSONL by tailing the sink. Connection probe = file
exists AND mtime within the last 5 minutes. Otherwise graceful skip with
SendResult(error='meta_xr_offline'), mirroring comfyui_mcp's pattern.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402
from mocap_frame import (  # type: ignore  # noqa: E402
    MocapFrame,
    META_BODY_JOINTS,
    ARKIT_BLENDSHAPES,
    frame_from_raw,
    is_valid_xr_anchor_uuid,
)

# Default sink (Godot writes here from meta_xr_mocap_emit.gd).
DEFAULT_SINK_PATH = Path.home() / ".cc" / "meta_xr_mocap.jsonl"

# 5-minute liveness window for the "connected" probe.
LIVENESS_WINDOW_SECONDS = 300.0

EXPECTED_TOOLS = (
    "body_track_frame",
    "face_track_frame",
    "list_anchors",
    "spatial_origin",
)

SOURCE_ID = "meta_xr_runtime"
CAPTURE_METHOD = "meta_xr_body"  # identity remap in mocap_frame.remap_joints


# ---------------------------------------------------------------------------
# Tail adapter
# ---------------------------------------------------------------------------

class MetaXRMocapAdapter:
    """Tails the Godot-written JSONL sink and yields MocapFrames.

    Each line in the sink is a JSON object emitted by
    studio/godot/project/src/meta_xr_mocap_emit.gd with shape:

      {
        "ts":              <unix seconds>,
        "joints":          {"<MetaBodyJointName>": [x,y,z,qx,qy,qz,qw], ...},
        "face_blendshapes":{"<arkitName>": 0..1, ...},
        "anchor_uuids":    ["<XR_FB_spatial_entity UUID>", ...],
        "confidence":      {"<MetaBodyJointName>": 0..1, ...},
        "spatial_origin":  [x, y, z, heading]   # XR_FB_passthrough origin
      }

    The adapter is stateless across calls — each call to tail() re-reads
    from the requested ts cursor. Callers maintain their own cursor.
    """

    def __init__(self, sink_path: Optional[Path] = None) -> None:
        self.sink_path = Path(sink_path) if sink_path else DEFAULT_SINK_PATH

    def is_live(self) -> bool:
        """Connection probe: file exists AND modified within liveness window."""
        try:
            if not self.sink_path.exists():
                return False
            age = time.time() - self.sink_path.stat().st_mtime
            return age <= LIVENESS_WINDOW_SECONDS
        except OSError:
            return False

    def tail(self, jsonl_path: Optional[Path] = None,
             since_ts: float = 0.0) -> Iterator[MocapFrame]:
        """Yield MocapFrames for every line with ts > since_ts.

        Reads the file once start-to-finish (no fcntl, no follow). The
        caller drives cadence (poll every N seconds with the previous
        max ts as since_ts).
        """
        path = Path(jsonl_path) if jsonl_path else self.sink_path
        if not path.exists():
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = float(rec.get("ts", 0.0))
                    if ts <= since_ts:
                        continue
                    yield self._record_to_frame(rec, ts)
        except OSError:
            return

    def latest(self, jsonl_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
        """Return the most recent raw record dict, or None if sink is empty."""
        path = Path(jsonl_path) if jsonl_path else self.sink_path
        if not path.exists():
            return None
        last: Optional[Dict[str, Any]] = None
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        last = json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return None
        return last

    @staticmethod
    def _record_to_frame(rec: Dict[str, Any], ts: float) -> MocapFrame:
        """Build a MocapFrame from a raw sink record. Uses frame_from_raw
        with mapping_kind='meta_xr_body' (identity, since the Godot side
        already speaks Meta Body joint names)."""
        raw_joints: Dict[str, Any] = dict(rec.get("joints", {}) or {})
        anchors = list(rec.get("anchor_uuids", []) or [])
        fb = dict(rec.get("face_blendshapes", {}) or {})
        conf = dict(rec.get("confidence", {}) or {})
        return frame_from_raw(
            raw_joints,
            source_id=SOURCE_ID,
            capture_method=CAPTURE_METHOD,
            mapping_kind="meta_xr_body",
            anchor_uuids=anchors,
            face_blendshapes=fb,
            confidence=conf,
            ts=ts,
        )


# ---------------------------------------------------------------------------
# Connector — mirrors snap_camera_kit shape
# ---------------------------------------------------------------------------

class MetaXRMocapConnector(ThirdPartyConnector):
    """Meta OpenXR mocap connector. Surfaces XR_FB_body_tracking,
    XR_FB_face_tracking2, XR_FB_spatial_entity, XR_FB_passthrough as
    four ThirdPartyConnector tools."""

    SERVICE = "meta_xr_mocap"

    def __init__(self, config: Optional[ConnectionConfig] = None,
                 sink_path: Optional[Path] = None):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name="meta_xr_mocap_default",
                action="mocap_tail_surface",
            )
        super().__init__(config)
        self.adapter = MetaXRMocapAdapter(sink_path=sink_path)
        self._connected = False

    # ---- lifecycle ------------------------------------------------------

    def connect(self) -> bool:
        """Liveness probe — sink exists and was touched in the last 5 min.
        Returns True iff the OpenXR runtime is actively emitting."""
        self._connected = self.adapter.is_live()
        return self._connected

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        """recipient = tool name; message = JSON args (preferred) or empty."""
        # Refresh liveness on every send (cheap stat call).
        live = self.adapter.is_live()
        self._connected = live

        if not live:
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                crystal_id="",
                error="meta_xr_offline",
                metadata={
                    "sink_path": str(self.adapter.sink_path),
                    "exists": self.adapter.sink_path.exists(),
                    "expected_tools": list(EXPECTED_TOOLS),
                    "extension_map": _EXTENSION_MAP,
                },
            )

        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        t0 = time.time()
        if recipient == "body_track_frame":
            status, body = self._body_track_frame(params)
        elif recipient == "face_track_frame":
            status, body = self._face_track_frame(params)
        elif recipient == "list_anchors":
            status, body = self._list_anchors(params)
        elif recipient == "spatial_origin":
            status, body = self._spatial_origin(params)
        else:
            return SendResult(
                success=False, service=self.SERVICE, recipient=recipient,
                message_preview="", timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                crystal_id="",
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )

        latency_ms = int((time.time() - t0) * 1000)
        success = 200 <= status < 300

        preview = str(body.get("frame_hash", "")
                       or body.get("anchor_count", "")
                       or body.get("origin", "")
                       or body)[:200]

        return SendResult(
            success=success, service=self.SERVICE, recipient=recipient,
            message_preview=preview,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            crystal_id="",
            error="" if success else body.get("_error", f"meta_xr_status_{status}"),
            metadata={
                "status_code": status,
                "latency_ms": latency_ms,
                "sink_path": str(self.adapter.sink_path),
                "joint_count": body.get("joint_count", 0),
                "blendshape_count": body.get("blendshape_count", 0),
                "anchor_count": body.get("anchor_count", 0),
            },
        )

    def history(self, thread_id: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        log_path = Path.home() / ".cc" / "third_party_logs" / "meta_xr_mocap_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- Tool implementations -----------------------------------------

    def _body_track_frame(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """XR_FB_body_tracking — return latest MocapFrame (joints only).
        Sparse: only includes joints present in the latest sink record."""
        rec = self.adapter.latest()
        if rec is None:
            return 404, {"_error": "no_frames_in_sink"}
        ts = float(rec.get("ts", time.time()))
        frame = MetaXRMocapAdapter._record_to_frame(rec, ts)
        if not frame.joints:
            return 204, {"_error": "no_joints_in_latest_frame",
                          "ts": frame.ts}
        return 200, {
            "ts": frame.ts,
            "frame_hash": frame.frame_hash(),
            "joints": {k: list(v) for k, v in frame.joints.items()},
            "joint_count": len(frame.joints),
            "anchor_uuids": list(frame.anchor_uuids),
            "anchor_count": len(frame.anchor_uuids),
            "confidence": dict(frame.confidence),
            "capture_method": frame.capture_method,
            "extension": "XR_FB_body_tracking",
        }

    def _face_track_frame(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """XR_FB_face_tracking2 — return latest face blend shape dict
        (ARKit 52). Sparse: only the blend shapes the runtime emitted."""
        rec = self.adapter.latest()
        if rec is None:
            return 404, {"_error": "no_frames_in_sink"}
        raw_fb = dict(rec.get("face_blendshapes", {}) or {})
        # Clamp and filter to ARKit-52 vocabulary.
        fb: Dict[str, float] = {}
        for k, v in raw_fb.items():
            if k in ARKIT_BLENDSHAPES:
                fb[k] = max(0.0, min(1.0, float(v)))
        if not fb:
            return 204, {"_error": "no_blendshapes_in_latest_frame",
                          "ts": float(rec.get("ts", 0.0))}
        return 200, {
            "ts": float(rec.get("ts", time.time())),
            "face_blendshapes": fb,
            "blendshape_count": len(fb),
            "extension": "XR_FB_face_tracking2",
        }

    def _list_anchors(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """XR_FB_spatial_entity — return list of XR_FB anchor UUIDs from
        the most recent sink record. These survive across sessions and
        are the "particles we placed long ago" that ME LAND anchors to."""
        rec = self.adapter.latest()
        if rec is None:
            return 404, {"_error": "no_frames_in_sink", "anchors": []}
        raw = list(rec.get("anchor_uuids", []) or [])
        anchors: List[str] = []
        for u in raw:
            if isinstance(u, str) and is_valid_xr_anchor_uuid(u):
                anchors.append(u.strip().lower())
        return 200, {
            "anchors": anchors,
            "anchor_count": len(anchors),
            "ts": float(rec.get("ts", time.time())),
            "extension": "XR_FB_spatial_entity",
        }

    def _spatial_origin(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """XR_FB_passthrough — return current (x, y, z, heading) of the
        headset wearer. Feeds spatial_anchor.CoordGraph ME LAND origin."""
        rec = self.adapter.latest()
        if rec is None:
            return 404, {"_error": "no_frames_in_sink"}
        origin = rec.get("spatial_origin")
        if (not isinstance(origin, (list, tuple))) or len(origin) != 4:
            return 204, {"_error": "no_spatial_origin_in_latest_frame",
                          "ts": float(rec.get("ts", 0.0))}
        try:
            x, y, z, heading = (float(origin[0]), float(origin[1]),
                                 float(origin[2]), float(origin[3]))
        except (TypeError, ValueError):
            return 422, {"_error": "spatial_origin_not_numeric"}
        return 200, {
            "origin": [x, y, z, heading],
            "x": x, "y": y, "z": z, "heading": heading,
            "ts": float(rec.get("ts", time.time())),
            "extension": "XR_FB_passthrough",
        }


# ---------------------------------------------------------------------------
# Extension mapping reference (also embedded in offline SendResult metadata)
# ---------------------------------------------------------------------------

_EXTENSION_MAP: Dict[str, str] = {
    "body_track_frame": "XR_FB_body_tracking",
    "face_track_frame": "XR_FB_face_tracking2",
    "list_anchors": "XR_FB_spatial_entity",
    "spatial_origin": "XR_FB_passthrough",
}


# ---------------------------------------------------------------------------
# CLI sanity check
# ---------------------------------------------------------------------------

def _self_test() -> None:
    print(f"SERVICE = {MetaXRMocapConnector.SERVICE}")
    print(f"EXPECTED_TOOLS = {EXPECTED_TOOLS}")
    print(f"Extension map: {_EXTENSION_MAP}")
    print(f"Default sink: {DEFAULT_SINK_PATH}")
    conn = MetaXRMocapConnector()
    print(f"connect() (no sink): {conn.connect()}")
    res = conn.send("body_track_frame")
    print(f"offline send: success={res.success} error={res.error}")


if __name__ == "__main__":
    _self_test()
