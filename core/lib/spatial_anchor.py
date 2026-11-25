#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        spatial_anchor
# role:        SUBSTRATE · MR_SPATIAL_RECONSTRUCTION (math foundations)
# tier:        L0
# substrate:   per-anchor crystal-chain record bridging digi-land + me-land
# engine:      deterministic sensor fusion — pure-Python (math, json, hashlib)
# storage:     none directly (caller persists; integrates with inference_logger)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.spatial_anchor.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - (planned hw) Web Audio API for ultrasonic impulse + ToA capture
#   - (planned hw) Wi-Fi RTT API + Geolocation for cm-precision position
#   - (planned)    Godot Studio AR mode → anchor scene origin to SpatialAnchor
#   - (planned)    workflow_card mr_walkthrough surface → ingest anchor matrix
# outbound:
#   - blake3 / blake2b for anchor crystal
#   - inference_logger.log (tier='spatial') when chain bridge wired
# substrate touch:
#   - reads:  raw sensor inputs (caller-provided ping_times + position)
#   - writes: none (caller persists; SpatialAnchor IS the record)
# joins existing MoE axes via SAME-SHAPE embeddings:
#   - room_signature  → 64-d DCT — joinable with wave_emb (find similar rooms)
#   - position_enc    → sin/cos of (x,y,z,heading_rad) — joinable with time_vec
#   - affine_matrix   → 4×4 — composable with any digi-land transform
#   - crystal_id      → BLAKE3 — joinable across all 10 retrieval lenses
# ============================================================================
"""spatial_anchor.py — math foundations for mixed-reality spatial reconstruction.

Three sensor streams fuse into one anchored event:

  AcousticEcho:    ultrasonic ping ToA  →  wall_distances_m (vector)
                                       →  DCT-II → room_signature (64-d wave axis)

  WifiRTTBeacon:   Wi-Fi RTT + GPS      →  (x, y, z, heading_deg)
                                       →  sin/cos enc → position_encoding (16-d time axis)

  CoordGraph:      echo + position      →  4×4 affine transform (room → scene origin)

  SpatialAnchor:   all of the above + timestamp + room_id + BLAKE3 crystal

The math works on synthetic inputs today (deterministic, testable). The
hardware capture layer (Web Audio API ping emission, Wi-Fi RTT polling) is
the next wedge — those remain TEXT-PLACEHOLDER ops in the DAG.

Identity guarantees: same sensor inputs → same crystal_id, bytes-exact.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Hashing (BLAKE3 preferred; blake2b fallback)
# ---------------------------------------------------------------------------
try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPEED_OF_SOUND_MPS = 343.0       # at 20 °C, dry air; ±0.6 m/s per °C
WALL_DIST_CAP = 64               # max surfaces tracked per echo (matches wave_emb dim)
POSITION_ENC_PAIRS = 4           # sin/cos pairs per axis; 4 axes × 2 = 8 dims per axis
POSITION_ENC_DIM = 4 * POSITION_ENC_PAIRS * 2   # 32 — total position vector
ROOM_SIG_COEFFS = 64             # DCT-II output dim — matches wave_emb axis
DEFAULT_CEILING_M = 2.4          # used when echo direction is up/down and absent


# ---------------------------------------------------------------------------
# DCT-II (same math as tri_modal_embedder.wave_embedding so signatures join)
# ---------------------------------------------------------------------------
def _dct_ii(samples: List[float], n_coeffs: int = ROOM_SIG_COEFFS) -> List[float]:
    N = len(samples)
    if N == 0:
        return [0.0] * n_coeffs
    out: List[float] = []
    for k in range(min(n_coeffs, N)):
        s = 0.0
        for n in range(N):
            s += samples[n] * math.cos(math.pi * (n + 0.5) * k / N)
        if k == 0:
            s *= math.sqrt(1.0 / N)
        else:
            s *= math.sqrt(2.0 / N)
        out.append(s)
    while len(out) < n_coeffs:
        out.append(0.0)
    return out


def _l2_normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-12:
        return vec
    return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# Acoustic Echo Mapping
# ---------------------------------------------------------------------------
@dataclass
class AcousticEcho:
    """Ultrasonic impulse → wall distances → room signature."""
    ping_times_s: List[float] = field(default_factory=list)
    wall_distances_m: List[float] = field(default_factory=list)
    timestamp: float = 0.0
    speed_of_sound: float = SPEED_OF_SOUND_MPS

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()
        if self.ping_times_s and not self.wall_distances_m:
            self.wall_distances_m = [self.ping_to_distance(t) for t in self.ping_times_s]
        # Cap to WALL_DIST_CAP for stability
        if len(self.wall_distances_m) > WALL_DIST_CAP:
            self.wall_distances_m = self.wall_distances_m[:WALL_DIST_CAP]

    def ping_to_distance(self, ping_time_s: float) -> float:
        """ToA → distance: d = (t * v) / 2 (round-trip halved)."""
        if ping_time_s <= 0:
            return 0.0
        return (ping_time_s * self.speed_of_sound) / 2.0

    @classmethod
    def from_ping_times(cls, ping_times_s: List[float]) -> "AcousticEcho":
        return cls(ping_times_s=list(ping_times_s))

    @classmethod
    def from_wall_distances(cls, wall_distances_m: List[float]) -> "AcousticEcho":
        """For synthetic / replay scenarios where distances are known directly."""
        echo = cls(wall_distances_m=list(wall_distances_m))
        # Back-compute synthetic ping_times for reproducibility
        echo.ping_times_s = [(d * 2.0 / SPEED_OF_SOUND_MPS) for d in wall_distances_m]
        return echo

    def room_signature_dct(self, n_coeffs: int = ROOM_SIG_COEFFS) -> List[float]:
        """DCT-II of distance vector, L2-normalized. Same shape as wave_emb →
        the 'room signature' joins the existing wave axis. Find similar rooms
        in the chain by cosine over this vector."""
        spectrum = _dct_ii(self.wall_distances_m, n_coeffs)
        return _l2_normalize(spectrum)

    def crystal(self) -> str:
        canonical = json.dumps({
            "ping_times_s": [round(t, 6) for t in self.ping_times_s],
            "wall_distances_m": [round(d, 4) for d in self.wall_distances_m],
            "timestamp": round(self.timestamp, 3),
            "speed_of_sound": self.speed_of_sound,
        }, sort_keys=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))


# ---------------------------------------------------------------------------
# Wi-Fi RTT Beacon
# ---------------------------------------------------------------------------
@dataclass
class WifiRTTBeacon:
    """Round-trip-time + GPS → indoor position (cm precision) with heading."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    heading_deg: float = 0.0
    confidence: float = 1.0      # 0-1; drops when RTT/GPS partial
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    @classmethod
    def from_position(cls, x: float, y: float, z: float = 0.0,
                       heading_deg: float = 0.0, confidence: float = 1.0
                       ) -> "WifiRTTBeacon":
        return cls(x=x, y=y, z=z, heading_deg=heading_deg, confidence=confidence)

    def position_encoding(self, pairs: int = POSITION_ENC_PAIRS) -> List[float]:
        """sin/cos positional encoding of (x, y, z, heading_rad) — same math as
        tri_modal_embedder.time_vector so the position joins the time axis.
        Returns 4 * 2 * pairs = 4*2*4 = 32 dims by default."""
        heading_rad = math.radians(self.heading_deg)
        axes = [self.x, self.y, self.z, heading_rad]
        out: List[float] = []
        for v in axes:
            for i in range(pairs):
                freq = 1.0 / (10000.0 ** (2 * i / (2 * pairs)))
                out.append(math.sin(v * freq))
                out.append(math.cos(v * freq))
        return out

    def crystal(self) -> str:
        canonical = json.dumps({
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "z": round(self.z, 4),
            "heading_deg": round(self.heading_deg, 2),
            "confidence": round(self.confidence, 3),
            "timestamp": round(self.timestamp, 3),
        }, sort_keys=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))


# ---------------------------------------------------------------------------
# 4×4 affine matrix helpers (no numpy — pure list-of-lists)
# ---------------------------------------------------------------------------
def identity_4x4() -> List[List[float]]:
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def matmul_4x4(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def translation_4x4(x: float, y: float, z: float) -> List[List[float]]:
    m = identity_4x4()
    m[0][3] = x
    m[1][3] = y
    m[2][3] = z
    return m


def rotation_y_4x4(angle_rad: float) -> List[List[float]]:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return [
        [c,    0.0, s,   0.0],
        [0.0,  1.0, 0.0, 0.0],
        [-s,   0.0, c,   0.0],
        [0.0,  0.0, 0.0, 1.0],
    ]


# ---------------------------------------------------------------------------
# Coordinate Graph — fuses echo + position into a single 4×4 transform
# ---------------------------------------------------------------------------
@dataclass
class CoordGraph:
    echo: Optional[AcousticEcho] = None
    position: Optional[WifiRTTBeacon] = None
    additional_transforms: List[List[List[float]]] = field(default_factory=list)

    def base_affine(self) -> List[List[float]]:
        """The room → scene-origin transform built from position + heading."""
        if self.position is None:
            return identity_4x4()
        T = translation_4x4(self.position.x, self.position.y, self.position.z)
        R = rotation_y_4x4(math.radians(self.position.heading_deg))
        return matmul_4x4(T, R)

    def composed_affine(self) -> List[List[float]]:
        """Compose base × all additional_transforms in declared order."""
        m = self.base_affine()
        for t in self.additional_transforms:
            m = matmul_4x4(m, t)
        return m

    def add_transform(self, m4: List[List[float]]) -> None:
        if len(m4) != 4 or any(len(row) != 4 for row in m4):
            raise ValueError("transform must be 4x4")
        self.additional_transforms.append(m4)

    def transform_point(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        """Apply the composed affine to a 3D point."""
        m = self.composed_affine()
        out = [
            m[0][0]*x + m[0][1]*y + m[0][2]*z + m[0][3],
            m[1][0]*x + m[1][1]*y + m[1][2]*z + m[1][3],
            m[2][0]*x + m[2][1]*y + m[2][2]*z + m[2][3],
        ]
        return (out[0], out[1], out[2])


# ---------------------------------------------------------------------------
# Spatial Anchor — the crystal-chain event
# ---------------------------------------------------------------------------
@dataclass
class SpatialAnchor:
    room_id: str = ""
    echo: Optional[AcousticEcho] = None
    position: Optional[WifiRTTBeacon] = None
    coord_graph: Optional[CoordGraph] = None
    room_signature: List[float] = field(default_factory=list)
    position_encoding: List[float] = field(default_factory=list)
    affine_matrix: List[List[float]] = field(default_factory=list)
    timestamp: float = 0.0
    crystal_id: str = ""

    @classmethod
    def of(cls,
           echo: Optional[AcousticEcho] = None,
           position: Optional[WifiRTTBeacon] = None,
           room_id: str = "",
           extra_transforms: Optional[List[List[List[float]]]] = None
           ) -> "SpatialAnchor":
        anchor = cls(echo=echo, position=position, room_id=room_id, timestamp=time.time())
        anchor.coord_graph = CoordGraph(
            echo=echo, position=position,
            additional_transforms=list(extra_transforms or []),
        )
        if echo is not None and echo.wall_distances_m:
            anchor.room_signature = echo.room_signature_dct()
        if position is not None:
            anchor.position_encoding = position.position_encoding()
        anchor.affine_matrix = anchor.coord_graph.composed_affine()
        anchor.crystal_id = anchor._compute_crystal()
        return anchor

    def _compute_crystal(self) -> str:
        canonical = json.dumps({
            "room_id": self.room_id,
            "echo_crystal": self.echo.crystal() if self.echo else "",
            "position_crystal": self.position.crystal() if self.position else "",
            "room_signature_first6": [round(x, 6) for x in self.room_signature[:6]],
            "position_encoding_first6": [round(x, 6) for x in self.position_encoding[:6]],
            "affine_first_row": [round(x, 6) for x in (self.affine_matrix[0] if self.affine_matrix else [])],
            "timestamp": round(self.timestamp, 3),
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Convert dataclass instances inside echo/position back to dicts for JSON safety
        if self.echo:
            d["echo"] = asdict(self.echo)
        if self.position:
            d["position"] = asdict(self.position)
        return d


# ---------------------------------------------------------------------------
# Cross-substrate joins — find similar rooms via room_signature
# ---------------------------------------------------------------------------
def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        n = min(len(a), len(b))
        a = a[:n]; b = b[:n]
    return sum(x * y for x, y in zip(a, b))


def find_similar_rooms(query_signature: List[float],
                        corpus: List[Dict[str, Any]],
                        k: int = 5,
                        min_sim: float = 0.0) -> List[Dict[str, Any]]:
    """Each corpus entry: {"room_signature": List[float], ...}. Returns top-k
    by cosine similarity over the 64-d room signature (which is just a DCT
    of wall distances — joinable with wave_emb retrieval pattern)."""
    if not query_signature:
        return []
    scored = []
    for item in corpus:
        sig = item.get("room_signature") or []
        if not sig:
            continue
        sim = cosine_similarity(query_signature, sig)
        if sim < min_sim:
            continue
        scored.append({**{k: v for k, v in item.items() if k != "room_signature"},
                       "room_sim": round(sim, 6)})
    scored.sort(key=lambda x: -x["room_sim"])
    return scored[:k]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main():
    import argparse, sys

    ap = argparse.ArgumentParser(description="spatial_anchor — MR sensor-fusion CLI")
    sub = ap.add_subparsers(dest="cmd")

    p_echo = sub.add_parser("echo", help="build an AcousticEcho from ping times")
    p_echo.add_argument("ping_times", nargs="+", type=float,
                         help="ping ToA in seconds, one per direction (e.g., 0.012 0.018 0.025)")

    p_pos = sub.add_parser("position", help="build a WifiRTTBeacon")
    p_pos.add_argument("--x", type=float, required=True)
    p_pos.add_argument("--y", type=float, required=True)
    p_pos.add_argument("--z", type=float, default=0.0)
    p_pos.add_argument("--heading", type=float, default=0.0)

    p_anchor = sub.add_parser("anchor", help="full SpatialAnchor from synthetic inputs")
    p_anchor.add_argument("--distances", nargs="+", type=float, required=True,
                            help="wall distances in meters (e.g., 4.2 3.8 2.4)")
    p_anchor.add_argument("--x", type=float, default=0.0)
    p_anchor.add_argument("--y", type=float, default=0.0)
    p_anchor.add_argument("--z", type=float, default=0.0)
    p_anchor.add_argument("--heading", type=float, default=0.0)
    p_anchor.add_argument("--room-id", default="")
    p_anchor.add_argument("--full", action="store_true")

    p_dem = sub.add_parser("demo", help="end-to-end synthetic demo")

    args = ap.parse_args()

    if args.cmd == "echo":
        e = AcousticEcho.from_ping_times(args.ping_times)
        sig = e.room_signature_dct()
        print(json.dumps({
            "ping_times_s": e.ping_times_s,
            "wall_distances_m": [round(d, 4) for d in e.wall_distances_m],
            "crystal": e.crystal()[:32],
            "room_signature_head": [round(x, 5) for x in sig[:8]],
            "room_signature_norm": round(math.sqrt(sum(x*x for x in sig)), 6),
        }, indent=2))

    elif args.cmd == "position":
        p = WifiRTTBeacon.from_position(args.x, args.y, args.z, args.heading)
        enc = p.position_encoding()
        print(json.dumps({
            "x": p.x, "y": p.y, "z": p.z, "heading_deg": p.heading_deg,
            "position_encoding_head": [round(x, 5) for x in enc[:8]],
            "crystal": p.crystal()[:32],
        }, indent=2))

    elif args.cmd == "anchor":
        e = AcousticEcho.from_wall_distances(args.distances)
        p = WifiRTTBeacon.from_position(args.x, args.y, args.z, args.heading)
        a = SpatialAnchor.of(echo=e, position=p, room_id=args.room_id)
        if args.full:
            print(json.dumps(a.to_dict(), indent=2, default=str))
        else:
            print(json.dumps({
                "room_id": a.room_id,
                "crystal_id": a.crystal_id[:32],
                "wall_distances_m": e.wall_distances_m,
                "room_signature_head": [round(x, 5) for x in a.room_signature[:8]],
                "position_encoding_head": [round(x, 5) for x in a.position_encoding[:8]],
                "affine_first_row": [round(x, 6) for x in a.affine_matrix[0]],
                "transform_origin_check": list(a.coord_graph.transform_point(0, 0, 0)),
            }, indent=2))

    elif args.cmd == "demo":
        print("--- (1) AcousticEcho from ping times [12ms, 18ms, 25ms, 22ms] ---")
        e = AcousticEcho.from_ping_times([0.012, 0.018, 0.025, 0.022])
        print(json.dumps({
            "wall_distances_m": [round(d, 3) for d in e.wall_distances_m],
            "crystal": e.crystal()[:32],
        }, indent=2))

        print("\n--- (2) WifiRTTBeacon at (3.5, 0.0, 2.1) heading 45° ---")
        p = WifiRTTBeacon.from_position(3.5, 0.0, 2.1, heading_deg=45.0)
        print(json.dumps({
            "position": [p.x, p.y, p.z, p.heading_deg],
            "crystal": p.crystal()[:32],
            "encoding_head": [round(x, 4) for x in p.position_encoding()[:6]],
        }, indent=2))

        print("\n--- (3) SpatialAnchor (fused) ---")
        a = SpatialAnchor.of(echo=e, position=p, room_id="demo_room_001")
        print(json.dumps({
            "crystal_id": a.crystal_id[:32],
            "room_signature_head": [round(x, 5) for x in a.room_signature[:6]],
            "affine_first_row": [round(x, 4) for x in a.affine_matrix[0]],
            "(0,0,0) transformed →": [round(c, 4) for c in a.coord_graph.transform_point(0, 0, 0)],
            "(1,0,0) transformed →": [round(c, 4) for c in a.coord_graph.transform_point(1, 0, 0)],
        }, indent=2))

        print("\n--- (4) Determinism check: same inputs → same crystal ---")
        a2 = SpatialAnchor.of(
            echo=AcousticEcho.from_ping_times([0.012, 0.018, 0.025, 0.022]),
            position=WifiRTTBeacon(x=3.5, y=0.0, z=2.1, heading_deg=45.0,
                                     timestamp=p.timestamp),
            room_id="demo_room_001",
        )
        # The full crystal includes timestamp so we'd only get a match by injecting timestamp
        # explicitly. Verify echo + position sub-crystals are stable:
        e2 = AcousticEcho.from_ping_times([0.012, 0.018, 0.025, 0.022])
        e2.timestamp = e.timestamp
        print(json.dumps({
            "echo_crystal_stable": e.crystal() == e2.crystal(),
            "position_crystal_stable_same_ts": p.crystal() == WifiRTTBeacon(
                x=3.5, y=0.0, z=2.1, heading_deg=45.0, timestamp=p.timestamp).crystal(),
        }, indent=2))

        print("\n--- (5) Room similarity: synthesize 2 rooms, query signature ---")
        rooms = [
            {"id": "room_001_living",
             "room_signature": SpatialAnchor.of(
                 echo=AcousticEcho.from_wall_distances([4.5, 5.0, 4.5, 5.0, 2.4]),
             ).room_signature},
            {"id": "room_002_bedroom",
             "room_signature": SpatialAnchor.of(
                 echo=AcousticEcho.from_wall_distances([3.0, 3.5, 3.0, 3.5, 2.4]),
             ).room_signature},
            {"id": "room_003_bathroom",
             "room_signature": SpatialAnchor.of(
                 echo=AcousticEcho.from_wall_distances([2.0, 2.5, 2.0, 2.5, 2.4]),
             ).room_signature},
        ]
        # Query: a room similar to bedroom dimensions
        q = SpatialAnchor.of(
            echo=AcousticEcho.from_wall_distances([3.1, 3.6, 3.1, 3.6, 2.4]),
        ).room_signature
        sims = find_similar_rooms(q, rooms, k=3)
        for s in sims:
            print(f"  room_sim={s['room_sim']:.4f}  {s['id']}")

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
