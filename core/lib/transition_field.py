#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        transition_field
# role:        SUBSTRATE · MEASUREMENT_FIRST_DELTA_FIELD
# tier:        L0
# substrate:   per-Transition crystal + per-TransitionField aperture aggregations
# engine:      gradient measurement across spatial radius × temporal frame window
# storage:     none (stateless transform; caller persists)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.transition_field.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - any caller with crystal-chain events that have (position, frame, value)
#   - light_source.WorldLightField (frame-to-frame light delta = optical flow)
#   - svg_vector_embed (shape morphing: square → blue square as measured trans)
#   - spatial_anchor (room signature drift over time)
#   - moe_router (planned: find_similar_flows axis — flow signature retrieval)
# outbound:
#   - blake3 / blake2b for Transition / TransitionField crystals
#   - stdlib only: math, json, hashlib
# substrate touch:
#   - reads:  caller-provided event corpus
#   - writes: none (caller persists Transition crystals via inference_logger)
# the inversion of forward_projector:
#   - forward_projector  → PREDICTS what comes next (uses LLM, posthoc)
#   - transition_field   → MEASURES what already happened (uses chain data)
#   - if you have the data, measure. if not, project. both first-class.
# ============================================================================
"""transition_field.py — measurement-first delta substrate.

You don't need to PREDICT what's already in the chain. You need to MEASURE.

For each event with (position, frame, value) — where value can be RGB, geometry
hash, attribute_signature, light field — this substrate measures gradients
within a 4D aperture:

  spatial sphere:  events within radius R of the query position
  temporal disk:   events within ±N frames of the query frame

The transitions across that aperture are OPTICAL FLOW for pixel/color data,
SHAPE MORPHING for geometry, LIGHT-FIELD EVOLUTION for emission, and
POSE TRAJECTORIES for spatial events — all measured, none predicted.

Provides:
  Transition     — one measured src→dst delta (position, value, time)
  TransitionField — all transitions in the aperture (divergence, curl, mean_velocity, flow_signature)

flow_signature is a 64-d DCT-II of the magnitude sequence → joinable with
the wave / wave-antithesis axes already in the MoE retrieval substrate.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


FLOW_SIG_COEFFS = 64  # match wave_emb dim — flow signature joins wave axis


# ---------------------------------------------------------------------------
# DCT-II (same math as tri_modal_embedder; flow signatures join wave axis)
# ---------------------------------------------------------------------------
def _dct_ii(samples: List[float], n_coeffs: int = FLOW_SIG_COEFFS) -> List[float]:
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
# Vector math helpers (pure Python; 3-tuples)
# ---------------------------------------------------------------------------
def _sub3(a: Tuple[float, float, float],
          b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mag3(v: Tuple[float, float, float]) -> float:
    return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])


def _normalize3(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    m = _mag3(v)
    if m < 1e-12:
        return (0.0, 0.0, 0.0)
    return (v[0] / m, v[1] / m, v[2] / m)


def _cross3(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0])


def _dot3(a: Tuple[float, float, float],
           b: Tuple[float, float, float]) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


# ---------------------------------------------------------------------------
# Transition — one measured src → dst delta
# ---------------------------------------------------------------------------

@dataclass
class Transition:
    src_crystal: str = ""
    dst_crystal: str = ""

    src_position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    dst_position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    spatial_delta: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    spatial_distance: float = 0.0
    direction: Tuple[float, float, float] = (0.0, 0.0, 0.0)

    # Optional value channel (RGB, attribute_signature, etc.)
    value_dim: int = 0
    value_delta: List[float] = field(default_factory=list)
    value_delta_magnitude: float = 0.0

    # Time
    frame_src: int = 0
    frame_dst: int = 0
    frame_delta: int = 0
    fps: int = 60
    duration_s: float = 0.0

    # Derived velocity
    velocity_magnitude: float = 0.0   # spatial_distance / duration_s
    color_velocity: float = 0.0       # value_delta_magnitude / duration_s

    crystal: str = ""

    @classmethod
    def measure(cls,
                src: Dict[str, Any],
                dst: Dict[str, Any],
                fps: int = 60,
                value_key: Optional[str] = None) -> "Transition":
        """Measure a transition between two events. Each event dict must have:
          - 'crystal' (str)
          - 'position' (3-tuple)
          - 'frame' (int) at the given fps   OR 'frames' (dict[fps→frame])
          - optional value_key (e.g., 'rgb', 'attribute_signature') for value delta
        """
        src_pos = tuple(src.get("position") or (0.0, 0.0, 0.0))
        dst_pos = tuple(dst.get("position") or (0.0, 0.0, 0.0))

        spatial_delta = _sub3(dst_pos, src_pos)
        spatial_distance = _mag3(spatial_delta)
        direction = _normalize3(spatial_delta)

        # Frame extraction
        f_src = src.get("frame")
        f_dst = dst.get("frame")
        if f_src is None and "frames" in src:
            f_src = src["frames"].get(fps) or src["frames"].get(str(fps)) or 0
        if f_dst is None and "frames" in dst:
            f_dst = dst["frames"].get(fps) or dst["frames"].get(str(fps)) or 0
        f_src = int(f_src or 0)
        f_dst = int(f_dst or 0)
        frame_delta = f_dst - f_src
        duration_s = frame_delta / fps if fps > 0 else 0.0

        # Value delta
        value_delta: List[float] = []
        if value_key:
            v_src = src.get(value_key)
            v_dst = dst.get(value_key)
            if isinstance(v_src, (list, tuple)) and isinstance(v_dst, (list, tuple)):
                n = min(len(v_src), len(v_dst))
                value_delta = [float(v_dst[i]) - float(v_src[i]) for i in range(n)]

        value_mag = math.sqrt(sum(x * x for x in value_delta)) if value_delta else 0.0

        # Velocities
        velocity = spatial_distance / abs(duration_s) if duration_s != 0 else 0.0
        color_v = value_mag / abs(duration_s) if duration_s != 0 else 0.0

        t = cls(
            src_crystal=src.get("crystal", ""),
            dst_crystal=dst.get("crystal", ""),
            src_position=src_pos, dst_position=dst_pos,
            spatial_delta=spatial_delta, spatial_distance=spatial_distance,
            direction=direction,
            value_dim=len(value_delta), value_delta=value_delta,
            value_delta_magnitude=value_mag,
            frame_src=f_src, frame_dst=f_dst, frame_delta=frame_delta,
            fps=fps, duration_s=duration_s,
            velocity_magnitude=velocity, color_velocity=color_v,
        )
        t.crystal = t._compute_crystal()
        return t

    def _compute_crystal(self) -> str:
        canonical = json.dumps({
            "src": self.src_crystal, "dst": self.dst_crystal,
            "spatial_delta": [round(x, 4) for x in self.spatial_delta],
            "value_delta": [round(x, 4) for x in self.value_delta],
            "frame_delta": self.frame_delta, "fps": self.fps,
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))


# ---------------------------------------------------------------------------
# TransitionField — all transitions within a 4D aperture around a query
# ---------------------------------------------------------------------------

@dataclass
class TransitionField:
    query_crystal: str = ""
    query_position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    query_frame: int = 0
    fps: int = 60

    radius_m: float = 5.0
    frame_window: int = 30   # ±N frames
    value_key: Optional[str] = None

    transitions: List[Transition] = field(default_factory=list)

    # Derived aggregate metrics
    mean_velocity_vec: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    mean_velocity_mag: float = 0.0
    divergence: float = 0.0
    curl_vec: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    flow_signature: List[float] = field(default_factory=list)
    crystal: str = ""

    @classmethod
    def measure(cls,
                query: Dict[str, Any],
                corpus: List[Dict[str, Any]],
                radius_m: float = 5.0,
                frame_window: int = 30,
                fps: int = 60,
                value_key: Optional[str] = None,
                exclude_self: bool = True) -> "TransitionField":
        """Build a TransitionField by measuring all transitions from `query`
        to corpus events within (radius_m, frame_window) at the given fps."""
        q_pos = tuple(query.get("position") or (0.0, 0.0, 0.0))
        q_frame = int(query.get("frame") or 0)
        if not q_frame and "frames" in query:
            q_frame = int(query["frames"].get(fps) or query["frames"].get(str(fps)) or 0)

        q_crystal = query.get("crystal", "")
        transitions: List[Transition] = []

        for ev in corpus:
            if exclude_self and ev.get("crystal") == q_crystal:
                continue
            ev_pos = tuple(ev.get("position") or (0.0, 0.0, 0.0))
            d = _mag3(_sub3(ev_pos, q_pos))
            if d > radius_m:
                continue
            f = int(ev.get("frame") or (ev.get("frames", {}) or {}).get(fps) or 0)
            if abs(f - q_frame) > frame_window:
                continue
            transitions.append(Transition.measure(query, ev, fps=fps, value_key=value_key))

        field_ = cls(
            query_crystal=q_crystal, query_position=q_pos, query_frame=q_frame,
            fps=fps, radius_m=radius_m, frame_window=frame_window,
            value_key=value_key, transitions=transitions,
        )
        field_._compute_aggregates()
        field_.crystal = field_._compute_crystal()
        return field_

    def _compute_aggregates(self) -> None:
        if not self.transitions:
            return
        # Mean velocity vector — weighted by direction × velocity_magnitude
        vx = vy = vz = 0.0
        for t in self.transitions:
            if t.duration_s == 0:
                continue
            vx += t.spatial_delta[0] / abs(t.duration_s)
            vy += t.spatial_delta[1] / abs(t.duration_s)
            vz += t.spatial_delta[2] / abs(t.duration_s)
        n = max(1, len(self.transitions))
        self.mean_velocity_vec = (vx / n, vy / n, vz / n)
        self.mean_velocity_mag = _mag3(self.mean_velocity_vec)

        # Divergence — sum of (direction · outward) ; outward = position - query
        div = 0.0
        for t in self.transitions:
            outward = _sub3(t.dst_position, self.query_position)
            outward = _normalize3(outward)
            div += _dot3(t.direction, outward) * t.velocity_magnitude
        self.divergence = div / n

        # Curl — sum of cross(direction, outward)
        cx = cy = cz = 0.0
        for t in self.transitions:
            outward = _sub3(t.dst_position, self.query_position)
            outward = _normalize3(outward)
            c = _cross3(t.direction, outward)
            cx += c[0] * t.velocity_magnitude
            cy += c[1] * t.velocity_magnitude
            cz += c[2] * t.velocity_magnitude
        self.curl_vec = (cx / n, cy / n, cz / n)

        # Flow signature — DCT of velocity magnitudes in transition order
        mags = [t.velocity_magnitude for t in self.transitions]
        if mags:
            self.flow_signature = _l2_normalize(_dct_ii(mags, FLOW_SIG_COEFFS))

    def _compute_crystal(self) -> str:
        canonical = json.dumps({
            "query":       self.query_crystal,
            "radius_m":    round(self.radius_m, 3),
            "frame_window": self.frame_window,
            "fps":         self.fps,
            "transition_crystals_sorted": sorted([t.crystal for t in self.transitions]),
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))


# ---------------------------------------------------------------------------
# Retrieval — find similar flow patterns
# ---------------------------------------------------------------------------

def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        n = min(len(a), len(b))
        a = a[:n]; b = b[:n]
    return sum(x * y for x, y in zip(a, b))


def find_similar_flows(query_field: TransitionField,
                        corpus: List[TransitionField],
                        k: int = 5,
                        min_sim: float = 0.0) -> List[Dict[str, Any]]:
    """Cosine similarity over flow_signature — find chain regions with similar
    motion / change patterns. Joins the wave axis since flow_signature is DCT-shaped."""
    q_sig = query_field.flow_signature
    if not q_sig:
        return []
    scored = []
    for field_ in corpus:
        if not field_.flow_signature:
            continue
        sim = cosine_similarity(q_sig, field_.flow_signature)
        if sim < min_sim:
            continue
        scored.append({
            "field_crystal": field_.crystal[:16],
            "query_crystal": field_.query_crystal[:16],
            "flow_sim": round(sim, 6),
            "transitions": len(field_.transitions),
            "divergence": round(field_.divergence, 4),
            "mean_velocity_mag": round(field_.mean_velocity_mag, 4),
        })
    scored.sort(key=lambda x: -x["flow_sim"])
    return scored[:k]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse, sys

    ap = argparse.ArgumentParser(description="transition_field — measure don't predict")
    sub = ap.add_subparsers(dest="cmd")
    p_dem = sub.add_parser("demo", help="end-to-end synthetic demo")
    args = ap.parse_args()

    if args.cmd == "demo":
        # Synthetic chain: 5 events at varying positions + frames + RGB
        events = [
            {"crystal": "ev_A", "position": (0.0, 0.0, 0.0), "frame": 60, "rgb": [1.0, 0.0, 0.0]},
            {"crystal": "ev_B", "position": (1.0, 0.0, 0.0), "frame": 65, "rgb": [0.8, 0.2, 0.0]},
            {"crystal": "ev_C", "position": (2.0, 0.0, 0.0), "frame": 70, "rgb": [0.6, 0.4, 0.0]},
            {"crystal": "ev_D", "position": (3.0, 0.0, 0.0), "frame": 75, "rgb": [0.4, 0.6, 0.0]},
            {"crystal": "ev_E", "position": (0.0, 1.0, 0.0), "frame": 62, "rgb": [1.0, 0.1, 0.1]},
        ]
        print("=== (1) MEASURE a single Transition ev_A → ev_B ===")
        t = Transition.measure(events[0], events[1], fps=60, value_key="rgb")
        print(json.dumps({
            "spatial_delta": list(t.spatial_delta),
            "spatial_distance": round(t.spatial_distance, 4),
            "direction": [round(x, 4) for x in t.direction],
            "value_delta": [round(x, 4) for x in t.value_delta],
            "value_delta_magnitude": round(t.value_delta_magnitude, 4),
            "frame_delta": t.frame_delta,
            "duration_s": round(t.duration_s, 4),
            "velocity_magnitude": round(t.velocity_magnitude, 4),
            "color_velocity": round(t.color_velocity, 4),
            "crystal": t.crystal[:32],
        }, indent=2))

        print("\n=== (2) TransitionField around ev_A (radius=2.5m, frame_window=10, fps=60) ===")
        tf = TransitionField.measure(
            query=events[0], corpus=events, radius_m=2.5, frame_window=10,
            fps=60, value_key="rgb",
        )
        print(json.dumps({
            "transitions_count": len(tf.transitions),
            "mean_velocity_vec": [round(x, 4) for x in tf.mean_velocity_vec],
            "mean_velocity_mag": round(tf.mean_velocity_mag, 4),
            "divergence": round(tf.divergence, 4),
            "curl_vec": [round(x, 4) for x in tf.curl_vec],
            "flow_signature_head": [round(x, 4) for x in tf.flow_signature[:8]],
            "flow_signature_norm": round(math.sqrt(sum(x*x for x in tf.flow_signature)), 6),
            "field_crystal": tf.crystal[:32],
        }, indent=2))

        print("\n=== (3) widen aperture (radius=4m, frame_window=20) ===")
        tf2 = TransitionField.measure(
            query=events[0], corpus=events, radius_m=4.0, frame_window=20,
            fps=60, value_key="rgb",
        )
        print(json.dumps({
            "transitions_count": len(tf2.transitions),
            "captured_within_aperture": len(tf2.transitions) > len(tf.transitions),
        }, indent=2))

        print("\n=== (4) find_similar_flows across two queries ===")
        tf_from_E = TransitionField.measure(
            query=events[4], corpus=events, radius_m=4.0, frame_window=20,
            fps=60, value_key="rgb",
        )
        sims = find_similar_flows(tf, [tf, tf_from_E], k=2)
        for s in sims:
            print(f"  flow_sim={s['flow_sim']:.4f}  query={s['query_crystal']}  "
                  f"transitions={s['transitions']}  divergence={s['divergence']:+.3f}")

        print("\n=== (5) the principle: we MEASURED, we didn't PREDICT ===")
        print("All 5 events were in the chain. No LLM. No projector. Pure measurement.")
        print("Forward_projector is now the fallback when chain is SPARSE.")

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
