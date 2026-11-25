"""unreal_live_link.py — stream MocapFrames over UDP to Unreal Engine 5's
Live Link plugin.

Live Link's wire format is documented at:
  https://docs.unrealengine.com/5.0/en-US/live-link-in-unreal-engine/
  + Engine/Source/Runtime/LiveLink (the open-source protocol bits)

This module speaks a simplified LiveLink JSON-over-UDP variant that the
"LiveLinkRemote" / "Live Link Free" plugin family accepts. Each datagram is
one frame:

    {
      "type":        "live_link_animation_frame",
      "subject_name": "MspcBlob",
      "skeleton":     ["Hips","SpineLower",...,"RightFootBall"],
      "frame_idx":    0,
      "ts":           1780050000.0,
      "transforms": [
        {"loc":[x,y,z],     "rot":[qx,qy,qz,qw], "scl":[1,1,1]},  # per joint
        ...
      ]
    }

UE5 maps subject_name → Live Link Subject; transforms[i] drives joint
skeleton[i] on the bound Animation Blueprint. Subjects auto-appear when the
first frame arrives.

We send at the card's declared fps (default 30) on UDP port 11111. The
Unreal side needs:
  - Plugin "Live Link" enabled
  - Plugin "Live Link Free" (optional, for plain UDP source) enabled
    OR a small UE blueprint that listens on the port and parses these JSON
    frames into LiveLinkAnimationFrameData.

Stdlib only (socket + json + struct).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "core" / "lib"))

try:
    from inference_logger import InferenceLogger
    _LOG = InferenceLogger()
except Exception:
    _LOG = None

try:
    from mocap_frame import META_BODY_JOINTS, MocapFrame  # type: ignore
except Exception as exc:
    print(f"[unreal_live_link] mocap_frame import failed: {exc}", file=sys.stderr)
    raise

DEFAULT_HOST = os.environ.get("MSPC_UNREAL_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("MSPC_UNREAL_PORT", "11111"))
DEFAULT_SUBJECT = os.environ.get("MSPC_UNREAL_SUBJECT", "MspcBlob")
DEFAULT_FPS = 30

# UDP datagrams over typical hardware are safe up to ~1400 bytes (MTU minus
# IP+UDP overhead). 24 joints × ~80 bytes per JSON transform ≈ 1.9 KB which
# fits a single jumbo-frame; on standard Ethernet we may need to fragment by
# splitting into half-skeletons. v0 sends the whole skeleton in one packet.
MAX_DATAGRAM_BYTES = 8192


# ── frame packing ──────────────────────────────────────────────────────────

@dataclass
class LiveLinkFrame:
    subject_name: str
    skeleton: List[str]
    frame_idx: int
    ts: float
    transforms: List[Dict]  # [{loc:[x,y,z], rot:[qx,qy,qz,qw], scl:[1,1,1]}]

    def to_wire(self) -> bytes:
        return json.dumps({
            "type": "live_link_animation_frame",
            "subject_name": self.subject_name,
            "skeleton": self.skeleton,
            "frame_idx": self.frame_idx,
            "ts": self.ts,
            "transforms": self.transforms,
        }, separators=(",", ":")).encode("utf-8")


def mocap_frame_to_live_link(frame: MocapFrame, frame_idx: int,
                              subject_name: str = DEFAULT_SUBJECT,
                              skeleton: Optional[List[str]] = None) -> LiveLinkFrame:
    """Convert one MocapFrame → LiveLinkFrame. Joints not present in
    frame.joints are emitted as identity transforms so the skeleton stays
    aligned with what UE5 binds to."""
    skel = skeleton or list(META_BODY_JOINTS)
    transforms = []
    for joint_name in skel:
        pose = frame.joints.get(joint_name)
        if pose is None:
            transforms.append({
                "loc": [0.0, 0.0, 0.0],
                "rot": [0.0, 0.0, 0.0, 1.0],  # identity quaternion
                "scl": [1.0, 1.0, 1.0],
            })
            continue
        # MocapFrame JointPose is (x, y, z, qx, qy, qz, qw)
        transforms.append({
            "loc": [float(pose[0]), float(pose[1]), float(pose[2])],
            "rot": [float(pose[3]), float(pose[4]),
                    float(pose[5]), float(pose[6])],
            "scl": [1.0, 1.0, 1.0],
        })
    return LiveLinkFrame(
        subject_name=subject_name,
        skeleton=skel,
        frame_idx=frame_idx,
        ts=frame.ts,
        transforms=transforms,
    )


# ── UDP streamer ───────────────────────────────────────────────────────────

@dataclass
class StreamSession:
    subject_name: str
    host: str
    port: int
    started_at: float
    ended_at: float = 0.0
    frames_sent: int = 0
    bytes_sent: int = 0
    last_error: str = ""
    crystal_anchor: str = ""


def _open_socket() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
    return s


def stream(frames: Iterator[MocapFrame], *,
            subject_name: str = DEFAULT_SUBJECT,
            host: str = DEFAULT_HOST,
            port: int = DEFAULT_PORT,
            fps: float = DEFAULT_FPS,
            verbose: bool = False,
            dry_run: bool = False) -> StreamSession:
    """Send each MocapFrame as one LiveLinkFrame UDP datagram at the given
    fps. dry_run=True validates packing without sending — useful for tests."""
    session = StreamSession(
        subject_name=subject_name, host=host, port=port,
        started_at=time.time(),
    )
    sock = _open_socket() if not dry_run else None
    interval = 1.0 / max(1.0, fps)
    next_send = time.time()
    crystal = _anchor_session(session, dry_run=dry_run)
    session.crystal_anchor = crystal
    try:
        for idx, frame in enumerate(frames):
            ll = mocap_frame_to_live_link(frame, idx, subject_name)
            payload = ll.to_wire()
            if len(payload) > MAX_DATAGRAM_BYTES:
                session.last_error = (
                    f"datagram too large ({len(payload)} > {MAX_DATAGRAM_BYTES}); "
                    f"frame {idx} dropped")
                if verbose:
                    print(f"[live_link] {session.last_error}", file=sys.stderr)
                continue
            if not dry_run and sock is not None:
                try:
                    sock.sendto(payload, (host, port))
                except Exception as exc:
                    session.last_error = repr(exc)[:200]
                    if verbose:
                        print(f"[live_link] sendto fail: {exc!r}", file=sys.stderr)
                    continue
            session.frames_sent += 1
            session.bytes_sent += len(payload)
            if verbose and idx % 30 == 0:
                print(f"[live_link] frame {idx} → {host}:{port} "
                      f"({len(payload)}B, {session.frames_sent} total)",
                      file=sys.stderr)
            # rate-limit
            next_send += interval
            sleep_for = next_send - time.time()
            if sleep_for > 0.001:
                time.sleep(sleep_for)
            elif sleep_for < -interval:
                next_send = time.time()  # caught up; reset clock
    finally:
        if sock is not None:
            sock.close()
        session.ended_at = time.time()
    return session


def _anchor_session(session: StreamSession, dry_run: bool) -> str:
    if _LOG is None:
        return ""
    scope = "dry_run" if dry_run else "live"
    try:
        return _LOG.log(
            original_prompt=f"live_link_session:{session.subject_name}",
            enhanced_prompt=json.dumps({
                "subject_name": session.subject_name,
                "host": session.host, "port": session.port,
                "dry_run": dry_run,
            }),
            output_text=f"streaming subject {session.subject_name} → {session.host}:{session.port}",
            tier="unreal_live_link",
            model="live_link_udp",
            scope=scope,
            source_action="unreal_live_link.stream",
        ) or ""
    except Exception:
        return ""


# ── jsonl reader (consumes pose.jsonl from the pipeline) ────────────────────

def iter_mocap_jsonl(path: Path) -> Iterator[MocapFrame]:
    if not path.exists():
        return
    from mocap_frame import MocapFrame as _MF  # type: ignore
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                yield _MF(
                    ts=float(d.get("ts", 0.0)),
                    source_id=str(d.get("source_id", "?")),
                    capture_method=str(d.get("capture_method", "?")),
                    joints={k: tuple(v) for k, v in (d.get("joints") or {}).items()},
                    face_blendshapes=d.get("face_blendshapes") or {},
                    anchor_uuids=list(d.get("anchor_uuids") or []),
                    confidence=d.get("confidence") or {},
                    crystal_anchor=str(d.get("crystal_anchor", "")),
                )
            except Exception as exc:
                print(f"[live_link] skipping malformed line: {exc!r}",
                      file=sys.stderr)


# ── synthetic frames (for smoke + when no real mocap exists) ────────────────

def synth_frames(n: int = 90, fps: float = DEFAULT_FPS) -> Iterator[MocapFrame]:
    """Generate N synthetic MocapFrames where the Hips translate in a circle
    and the rest sit at identity. Useful for testing the LiveLink wire
    without a real video → pose extraction."""
    import math
    from mocap_frame import MocapFrame as _MF  # type: ignore
    for i in range(n):
        t = i / fps
        ang = (i / max(1, n)) * (2 * math.pi)
        hips = (0.3 * math.cos(ang), 1.0, 0.3 * math.sin(ang),
                0.0, 0.0, 0.0, 1.0)
        head = (0.3 * math.cos(ang), 1.7, 0.3 * math.sin(ang),
                0.0, 0.0, 0.0, 1.0)
        yield _MF(
            ts=time.time() + t,
            source_id="synth",
            capture_method="synth_circle",
            joints={"Hips": hips, "Head": head},
        )


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="unreal_live_link — UDP MocapFrame streamer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="stream pose.jsonl → UE5 LiveLink")
    p_send.add_argument("pose_jsonl")
    p_send.add_argument("--subject", default=DEFAULT_SUBJECT)
    p_send.add_argument("--host", default=DEFAULT_HOST)
    p_send.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_send.add_argument("--fps", type=float, default=DEFAULT_FPS)
    p_send.add_argument("--dry-run", action="store_true",
                        help="validate packing without sending")
    p_send.add_argument("--quiet", action="store_true")

    p_synth = sub.add_parser("synth", help="stream synthetic frames (no real video needed)")
    p_synth.add_argument("--n", type=int, default=90)
    p_synth.add_argument("--subject", default=DEFAULT_SUBJECT)
    p_synth.add_argument("--host", default=DEFAULT_HOST)
    p_synth.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_synth.add_argument("--fps", type=float, default=DEFAULT_FPS)
    p_synth.add_argument("--dry-run", action="store_true")
    p_synth.add_argument("--quiet", action="store_true")

    args = ap.parse_args(argv)

    if args.cmd == "send":
        path = Path(args.pose_jsonl).expanduser()
        if not path.exists():
            print(f"pose.jsonl not found: {path}", file=sys.stderr)
            return 2
        session = stream(iter_mocap_jsonl(path),
                          subject_name=args.subject,
                          host=args.host, port=args.port, fps=args.fps,
                          verbose=not args.quiet, dry_run=args.dry_run)
        print(json.dumps(asdict(session), indent=2, default=str))
        return 0

    if args.cmd == "synth":
        session = stream(synth_frames(n=args.n, fps=args.fps),
                          subject_name=args.subject,
                          host=args.host, port=args.port, fps=args.fps,
                          verbose=not args.quiet, dry_run=args.dry_run)
        print(json.dumps(asdict(session), indent=2, default=str))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
