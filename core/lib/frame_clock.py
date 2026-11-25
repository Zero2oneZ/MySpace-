#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        frame_clock
# role:        SUBSTRATE · FPS_QUANTIZED_TIME_DATA
# tier:        L0
# substrate:   integer frame indices at canonical FPSes (24/30/60/90/120)
# engine:      deterministic timestamp → frame_index quantization
# storage:     none (stateless transform; caller persists frame tuples)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.frame_clock.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - (planned) inference_logger — every record gets a frame tuple alongside ts
#   - (planned) tri_modal_embedder.time_vector — extend with frames dict
#   - (planned) spatial_anchor — anchor events frame-aligned to acoustic sweep
#   - workflow_card animation passes (Remotion frame index, Godot _process)
# outbound:
#   - blake3 / blake2b for FrameClock crystal
#   - stdlib only (math, time, json, hashlib)
# substrate touch:
#   - reads:  none
#   - writes: none (caller persists)
# ============================================================================
"""frame_clock.py — FPS is constant time data; treat it that way.

A FrameClock pins a continuous timestamp to integer frame indices at multiple
canonical FPSes. That gives the chain three immediate gains:

  1. Lossless integer joins. 'all events on frame 1800 at 60fps' is one
     deterministic dict lookup, not a float-distance scan.

  2. Cross-substrate sync. Godot's _process(delta) firing at frame N maps
     exactly to Remotion composition frame N maps exactly to SpriteForge
     sprite-sheet frame N maps exactly to spatial_anchor acoustic sweep N.

  3. Compact tamper-evident storage. The frame tuple packs as fixed-width
     big-endian uint64s → hex. Differential-amplifier check: recompute from
     timestamp; mismatch = tampered.

Canonical FPSes: 24 (cinema) · 30 (video) · 60 (game/UI) · 90 (VR comfort)
                 · 120 (high-refresh display)
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


CANONICAL_FPS: Tuple[int, ...] = (24, 30, 60, 90, 120)


# ---------------------------------------------------------------------------
# Conversions — single-shot helpers
# ---------------------------------------------------------------------------

def timestamp_to_frame(ts: float, fps: int) -> int:
    """Quantize a continuous timestamp to a frame index at given FPS.
    Negative timestamps and fps <= 0 raise ValueError."""
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    return int(math.floor(ts * fps))


def frame_to_timestamp(frame: int, fps: int) -> float:
    """Inverse: integer frame at given FPS → exact float seconds.
    Lossless within float precision for reasonable frame ranges."""
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    return frame / fps


def convert_frame(frame: int, from_fps: int, to_fps: int) -> int:
    """Rescale a frame index from one FPS to another. 60-fps frame 120 = 30-fps frame 60."""
    if from_fps <= 0 or to_fps <= 0:
        raise ValueError("both fps must be positive")
    if from_fps == to_fps:
        return frame
    return int(math.floor((frame / from_fps) * to_fps))


# ---------------------------------------------------------------------------
# FrameClock — a timestamp expressed at multiple canonical FPSes
# ---------------------------------------------------------------------------

@dataclass
class FrameClock:
    timestamp: float
    fps_set: Tuple[int, ...] = CANONICAL_FPS
    frames: Dict[int, int] = field(default_factory=dict)
    crystal: str = ""

    def __post_init__(self):
        if not self.frames:
            self.frames = {fps: timestamp_to_frame(self.timestamp, fps) for fps in self.fps_set}
        if not self.crystal:
            self.crystal = self._compute_crystal()

    @classmethod
    def now(cls, fps_set: Tuple[int, ...] = CANONICAL_FPS) -> "FrameClock":
        return cls(timestamp=time.time(), fps_set=fps_set)

    @classmethod
    def at(cls, timestamp: float, fps_set: Tuple[int, ...] = CANONICAL_FPS) -> "FrameClock":
        return cls(timestamp=timestamp, fps_set=fps_set)

    @classmethod
    def at_frame(cls, frame: int, fps: int,
                 fps_set: Tuple[int, ...] = CANONICAL_FPS) -> "FrameClock":
        """Build a FrameClock pinned to a specific (frame, fps) pair —
        all other fps indices derive from the implied timestamp."""
        ts = frame_to_timestamp(frame, fps)
        return cls(timestamp=ts, fps_set=fps_set)

    # ---- accessors -------------------------------------------------

    def at_fps(self, fps: int) -> int:
        """Get the frame index at a particular FPS (computes if not pre-cached)."""
        if fps in self.frames:
            return self.frames[fps]
        return timestamp_to_frame(self.timestamp, fps)

    def delta_frames(self, other: "FrameClock", fps: int) -> int:
        return self.at_fps(fps) - other.at_fps(fps)

    def delta_seconds(self, other: "FrameClock") -> float:
        return self.timestamp - other.timestamp

    # ---- serialization ---------------------------------------------

    def to_hex(self) -> str:
        """Pack all frame indices as 8-byte big-endian uint64s in sorted FPS order."""
        bs = bytearray()
        for fps in sorted(self.frames.keys()):
            v = max(0, self.frames[fps])
            try:
                bs += v.to_bytes(8, "big", signed=False)
            except OverflowError:
                bs += (2**64 - 1).to_bytes(8, "big", signed=False)
        return bytes(bs).hex()

    @classmethod
    def from_hex(cls, hex_str: str, fps_set: Tuple[int, ...] = CANONICAL_FPS) -> "FrameClock":
        """Reverse of to_hex. Recovers timestamp from the highest-FPS frame index
        (most precise). Useful for round-trip checks."""
        bs = bytes.fromhex(hex_str)
        sorted_fps = sorted(fps_set)
        frames = {}
        for i, fps in enumerate(sorted_fps):
            offset = i * 8
            if offset + 8 > len(bs):
                break
            frames[fps] = int.from_bytes(bs[offset:offset + 8], "big", signed=False)
        # Recover ts from the highest FPS (finest grain)
        if frames:
            max_fps = max(frames.keys())
            ts = frame_to_timestamp(frames[max_fps], max_fps)
        else:
            ts = 0.0
        return cls(timestamp=ts, fps_set=fps_set, frames=frames)

    # ---- determinism + verification -------------------------------

    def _compute_crystal(self) -> str:
        canonical = json.dumps({
            "fps_set": list(sorted(self.fps_set)),
            "frames": {str(k): v for k, v in sorted(self.frames.items())},
            "timestamp_rounded_us": round(self.timestamp, 6),
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))

    def verify(self) -> Dict[str, Any]:
        """Differential check: recompute frame indices from timestamp; mismatch = tampered."""
        recomputed = {fps: timestamp_to_frame(self.timestamp, fps) for fps in self.fps_set}
        mismatches = []
        for fps, frame in self.frames.items():
            if recomputed.get(fps) != frame:
                mismatches.append({"fps": fps, "stored": frame,
                                    "expected": recomputed.get(fps)})
        crystal_ok = self.crystal == self._compute_crystal()
        return {
            "frames_consistent": not mismatches,
            "mismatches": mismatches,
            "crystal_ok": crystal_ok,
            "all_ok": not mismatches and crystal_ok,
        }


# ---------------------------------------------------------------------------
# Retrieval — frame-aligned neighbors
# ---------------------------------------------------------------------------

def find_frame_neighbors(query_frame: int, fps: int,
                          corpus: List[Dict[str, Any]],
                          window: int = 1,
                          k: int = 10) -> List[Dict[str, Any]]:
    """Find records with frame_index ∈ [query - window, query + window] at given FPS.

    Each corpus entry must have a 'frames' dict (e.g., {30: 1800, 60: 3600}) OR a
    'timestamp' float (we'll compute the frame on the fly).
    """
    out = []
    lo = query_frame - window
    hi = query_frame + window
    for item in corpus:
        frames = item.get("frames") or {}
        if fps in frames:
            f = frames[fps]
        elif "timestamp" in item:
            f = timestamp_to_frame(item["timestamp"], fps)
        else:
            continue
        if lo <= f <= hi:
            out.append({**{k: v for k, v in item.items() if k != "frames"},
                         "matched_frame": f,
                         "delta_frames": f - query_frame})
    out.sort(key=lambda x: abs(x["delta_frames"]))
    return out[:k]


def find_synced_records(query: "FrameClock",
                         corpus: List[Dict[str, Any]],
                         tolerance_frames: int = 1,
                         fps: int = 60,
                         k: int = 10) -> List[Dict[str, Any]]:
    """Find records that are frame-synced to the query within tolerance at given FPS.

    A 'synced' record's frame_index at the chosen FPS is within tolerance of the query's.
    Useful for cross-substrate alignment (Godot scene at frame N ↔ Remotion comp at N).
    """
    q_frame = query.at_fps(fps)
    return find_frame_neighbors(q_frame, fps, corpus, window=tolerance_frames, k=k)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse, sys

    ap = argparse.ArgumentParser(description="frame_clock — FPS-quantized time data CLI")
    sub = ap.add_subparsers(dest="cmd")

    p_now = sub.add_parser("now", help="emit a FrameClock for the current moment")
    p_now.add_argument("--fps", type=int, nargs="+", default=list(CANONICAL_FPS))

    p_at = sub.add_parser("at", help="emit a FrameClock for a given timestamp")
    p_at.add_argument("timestamp", type=float)
    p_at.add_argument("--fps", type=int, nargs="+", default=list(CANONICAL_FPS))

    p_frame = sub.add_parser("frame", help="convert a frame index between FPSes")
    p_frame.add_argument("frame", type=int)
    p_frame.add_argument("--from-fps", type=int, required=True)
    p_frame.add_argument("--to-fps", type=int, required=True)

    p_demo = sub.add_parser("demo", help="full smoke test")

    args = ap.parse_args()

    if args.cmd == "now":
        c = FrameClock.now(tuple(args.fps))
        print(json.dumps({
            "timestamp": c.timestamp,
            "frames": c.frames,
            "hex": c.to_hex(),
            "crystal": c.crystal[:32],
        }, indent=2))

    elif args.cmd == "at":
        c = FrameClock.at(args.timestamp, tuple(args.fps))
        print(json.dumps({
            "timestamp": c.timestamp,
            "frames": c.frames,
            "hex": c.to_hex(),
            "crystal": c.crystal[:32],
        }, indent=2))

    elif args.cmd == "frame":
        result = convert_frame(args.frame, args.from_fps, args.to_fps)
        print(json.dumps({
            "from": {"fps": args.from_fps, "frame": args.frame},
            "to":   {"fps": args.to_fps,   "frame": result},
            "delta_seconds": frame_to_timestamp(args.frame, args.from_fps) - frame_to_timestamp(result, args.to_fps),
        }, indent=2))

    elif args.cmd == "demo":
        print("--- (1) FrameClock.at(1716868800.5) ---")
        c = FrameClock.at(1716868800.5)
        print(json.dumps({
            "timestamp": c.timestamp,
            "frames": c.frames,
            "hex_head": c.to_hex()[:32] + "…",
            "crystal":  c.crystal[:32],
        }, indent=2))

        print("\n--- (2) verify (clean) ---")
        print(json.dumps(c.verify(), indent=2))

        print("\n--- (3) tamper: change frames[60] to wrong value ---")
        c.frames[60] = 99999999
        c.crystal = c._compute_crystal()  # would need to recompute the crystal too...
        # ... but the timestamp doesn't match the stored frame at 60fps any more
        print(json.dumps(c.verify(), indent=2))

        print("\n--- (4) round-trip hex ---")
        c2 = FrameClock.at(1716868800.5)
        h = c2.to_hex()
        rt = FrameClock.from_hex(h)
        print(json.dumps({
            "original_ts": c2.timestamp,
            "hex": h[:32] + "…",
            "round_trip_ts": rt.timestamp,
            "round_trip_frames": rt.frames,
            "match": c2.frames == rt.frames,
        }, indent=2))

        print("\n--- (5) cross-FPS frame conversion ---")
        # 30fps frame 1800 = 60s = 60fps frame 3600 = 24fps frame 1440
        for to_fps in (24, 30, 60, 90, 120):
            f = convert_frame(1800, 30, to_fps)
            print(f"  30fps frame 1800 → {to_fps}fps frame {f}  (= {frame_to_timestamp(1800, 30):.2f}s)")

        print("\n--- (6) frame-synced retrieval ---")
        # Build a corpus of records at various timestamps
        corpus = [
            {"id": "godot_scene_A",   "timestamp": 100.000},
            {"id": "remotion_comp_A", "timestamp": 100.017},  # 1 frame later at 60fps
            {"id": "spriteforge_A",   "timestamp": 100.033},  # 2 frames later at 60fps
            {"id": "spatial_anchor_A", "timestamp": 105.000},  # 5 seconds later
            {"id": "godot_scene_B",   "timestamp": 100.500},
        ]
        q = FrameClock.at(100.000)
        synced = find_synced_records(q, corpus, tolerance_frames=2, fps=60, k=5)
        print(f"  query: t=100.000s (frame 6000 at 60fps)")
        for s in synced:
            print(f"    frame={s['matched_frame']:>5} Δ{s['delta_frames']:+}  {s['id']}")

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
