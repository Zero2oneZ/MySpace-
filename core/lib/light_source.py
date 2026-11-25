#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        light_source
# role:        SUBSTRATE · DERIVED_LIGHT_FIELD
# tier:        L0
# substrate:   per-LightSource crystal + per-frame WorldLightField aggregations
# engine:      synthesis of svg_vector_embed + spatial_anchor + frame_clock
# storage:     none (stateless; caller persists via inference_logger or chain)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.light_source.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - svg_vector_embed.SvgPathRecord (provides shape + RGB attribute_signature)
#   - spatial_anchor.SpatialAnchor   (provides world coordinates)
#   - frame_clock.FrameClock          (provides frame indices at canonical FPS)
#   - (planned) workflow_card.layer_stack emission channel — auto-populate
#   - (planned) Godot/Blender material emission slot
# outbound:
#   - blake3 / blake2b for crystal
#   - stdlib only: math, json, hashlib, time
# substrate touch:
#   - reads:  shape records, spatial anchors, frame clocks (all caller-provided)
#   - writes: none (caller persists)
# the synthesis:
#   RGB (from attribute_signature) + POSITION (from spatial_anchor) +
#   FRAME (from frame_clock) → LightSource(crystal, intensity, hue,
#   sat, lightness, temperature_warmth, falloff, direction, active_frames)
# ============================================================================
"""light_source.py — every colored shape with a position and a frame index IS a light.

Synthesis substrate. Takes pre-existing substrate outputs and welds them into
one queryable light field:

  SHAPE   svg_vector_embed.SvgPathRecord
            - geometry_crystal  (the family)
            - attribute_signature  (fill RGB, stroke RGB, opacity, stroke-width, ...)

  SPACE   spatial_anchor.SpatialAnchor
            - position (x, y, z)
            - room_signature
            - affine matrix

  TIME    frame_clock.FrameClock
            - frame_index per canonical FPS
            - timestamp

  → LightSource:
        crystal             BLAKE3 over canonical synthesis
        rgb                 (r, g, b) ∈ [0, 1]³
        hsl                 (h ∈ [0,360°], s ∈ [0,1], l ∈ [0,1])
        temperature_warmth  -1.0 (cool/blue) → +1.0 (warm/red)
        intensity           opacity-derived ∈ [0, 1]
        position            (x, y, z) world coords
        falloff             "quadratic" | "linear" | "none"
        active_frames       dict[fps] → frame_index (when this light is ON)

Queryable via:
  find_lights_at_frame(frame, fps, corpus)   — what's on at this moment
  find_lights_by_hue(target_hue, corpus, k)  — color-matching lights
  find_lights_near(xyz, radius, corpus, k)   — spatial proximity
  find_lights_by_warmth(min_w, max_w, corpus) — warm/cool bucket
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


# ---------------------------------------------------------------------------
# Color math (pure-Python, no colorsys reliance for determinism)
# ---------------------------------------------------------------------------

def rgb_to_hsl(r: float, g: float, b: float) -> Tuple[float, float, float]:
    """RGB ∈ [0, 1]³ → HSL with H ∈ [0, 360], S, L ∈ [0, 1]."""
    mx = max(r, g, b)
    mn = min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        return (0.0, 0.0, l)
    delta = mx - mn
    s = delta / (2.0 - mx - mn) if l > 0.5 else delta / (mx + mn)
    if mx == r:
        h_seg = ((g - b) / delta) % 6.0
    elif mx == g:
        h_seg = (b - r) / delta + 2.0
    else:
        h_seg = (r - g) / delta + 4.0
    h = h_seg * 60.0
    if h < 0:
        h += 360.0
    return (h, s, l)


def rgb_to_warmth(r: float, g: float, b: float) -> float:
    """Simple warm/cool axis: +1 fully warm (red dominant), -1 fully cool (blue dominant).
    A useful proxy when full McCamy CCT is overkill."""
    # weighted: red − blue, modulated by green to avoid pure greens registering as warm
    return max(-1.0, min(1.0, (r - b) * (1.0 - 0.5 * (g - (r + b) / 2.0))))


def estimated_color_temperature_k(r: float, g: float, b: float) -> float:
    """Crude correlated color temperature via McCamy-ish approximation.
    For deeper accuracy use a proper CCT lib; this is good enough for bucket queries."""
    # Convert to XYZ (sRGB → XYZ, simplified D65)
    # then compute n = (x - 0.3320) / (0.1858 - y)
    R = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    G = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    B = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    s = R + G + B
    if s <= 1e-9:
        return 6500.0
    x = R / s
    y = G / s
    # McCamy
    try:
        n = (x - 0.3320) / (0.1858 - y)
    except ZeroDivisionError:
        return 6500.0
    cct = 449.0 * n**3 + 3525.0 * n**2 + 6823.3 * n + 5520.33
    return max(1000.0, min(40000.0, cct))


# ---------------------------------------------------------------------------
# LightSource — the synthesis
# ---------------------------------------------------------------------------

@dataclass
class LightSource:
    # identity
    crystal: str = ""
    source_geometry_crystal: str = ""  # ties to svg shape family
    source_spatial_crystal: str = ""    # ties to spatial_anchor
    # color
    rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    hsl: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    temperature_warmth: float = 0.0
    color_temp_k: float = 6500.0
    # geometry
    intensity: float = 1.0
    falloff: str = "quadratic"            # quadratic | linear | none
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    direction: Tuple[float, float, float] = (0.0, -1.0, 0.0)  # default: pointing down
    # time
    active_frames: Dict[int, int] = field(default_factory=dict)  # fps → frame_index
    timestamp: float = 0.0

    @classmethod
    def from_shape_at_position_at_frame(
        cls,
        rgb: Tuple[float, float, float],
        opacity: float = 1.0,
        stroke_width: float = 0.0,
        has_gradient: bool = False,
        position: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        direction: Tuple[float, float, float] = (0.0, -1.0, 0.0),
        active_frames: Optional[Dict[int, int]] = None,
        timestamp: Optional[float] = None,
        source_geometry_crystal: str = "",
        source_spatial_crystal: str = "",
        falloff: str = "quadratic",
    ) -> "LightSource":
        ts = timestamp if timestamp is not None else time.time()
        r, g, b = rgb
        # Clamp
        r = max(0.0, min(1.0, r))
        g = max(0.0, min(1.0, g))
        b = max(0.0, min(1.0, b))

        hsl = rgb_to_hsl(r, g, b)
        warmth = rgb_to_warmth(r, g, b)
        cct = estimated_color_temperature_k(r, g, b)

        # Intensity model: opacity-driven, scaled down for gradient (more diffuse),
        # boosted slightly by stroke width up to a cap.
        gradient_factor = 0.5 if has_gradient else 1.0
        stroke_boost = min(1.0 + (stroke_width / 20.0), 1.5)
        intensity = max(0.0, min(1.0, opacity * gradient_factor * stroke_boost))

        active = dict(active_frames or {})

        instance = cls(
            source_geometry_crystal=source_geometry_crystal,
            source_spatial_crystal=source_spatial_crystal,
            rgb=(r, g, b),
            hsl=hsl,
            temperature_warmth=warmth,
            color_temp_k=cct,
            intensity=intensity,
            falloff=falloff,
            position=tuple(position),
            direction=tuple(direction),
            active_frames=active,
            timestamp=ts,
        )
        instance.crystal = instance._compute_crystal()
        return instance

    @classmethod
    def from_svg_attribute_signature(
        cls,
        attribute_signature: List[float],
        position: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        active_frames: Optional[Dict[int, int]] = None,
        source_geometry_crystal: str = "",
        source_spatial_crystal: str = "",
        prefer_stroke: bool = False,
    ) -> "LightSource":
        """Convenience constructor wired to svg_vector_embed.attribute_signature.

        attribute_signature schema (10 floats):
          [0:3]   fill RGB
          [3:6]   stroke RGB
          [6]     opacity
          [7]     stroke_width / 10 (clamped)
          [8]     has_gradient (0/1)
          [9]     has_pattern (0/1)
        """
        if len(attribute_signature) < 10:
            # pad
            attribute_signature = list(attribute_signature) + [0.0] * (10 - len(attribute_signature))

        if prefer_stroke and any(attribute_signature[3:6]):
            rgb = tuple(attribute_signature[3:6])
        elif any(attribute_signature[0:3]):
            rgb = tuple(attribute_signature[0:3])
        elif any(attribute_signature[3:6]):
            rgb = tuple(attribute_signature[3:6])
        else:
            rgb = (0.0, 0.0, 0.0)

        return cls.from_shape_at_position_at_frame(
            rgb=rgb,
            opacity=attribute_signature[6] if len(attribute_signature) > 6 else 1.0,
            stroke_width=attribute_signature[7] * 10.0 if len(attribute_signature) > 7 else 0.0,
            has_gradient=bool(attribute_signature[8]) if len(attribute_signature) > 8 else False,
            position=position,
            active_frames=active_frames,
            source_geometry_crystal=source_geometry_crystal,
            source_spatial_crystal=source_spatial_crystal,
        )

    # ---- determinism + introspection -----------------------------

    def _compute_crystal(self) -> str:
        canonical = json.dumps({
            "rgb":                  [round(x, 5) for x in self.rgb],
            "hsl":                  [round(x, 5) for x in self.hsl],
            "temperature_warmth":   round(self.temperature_warmth, 5),
            "color_temp_k":         round(self.color_temp_k, 1),
            "intensity":            round(self.intensity, 5),
            "falloff":              self.falloff,
            "position":             [round(x, 4) for x in self.position],
            "direction":            [round(x, 4) for x in self.direction],
            "active_frames":        {str(k): v for k, v in sorted(self.active_frames.items())},
            "source_geometry_crystal": self.source_geometry_crystal,
            "source_spatial_crystal":  self.source_spatial_crystal,
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))

    def is_active_at_frame(self, frame: int, fps: int) -> bool:
        return self.active_frames.get(fps) == frame

    def color_band(self) -> str:
        """Coarse hue band: red/orange/yellow/green/cyan/blue/purple/magenta."""
        h = self.hsl[0]
        if self.hsl[1] < 0.1:
            return "neutral"
        bands = [
            (0,    "red"),    (15,   "red-orange"),
            (45,   "orange"), (60,   "yellow"),
            (90,   "green"),  (180,  "cyan"),
            (210,  "blue"),   (270,  "purple"),
            (300,  "magenta"),(345,  "red"),
        ]
        for lo, name in reversed(bands):
            if h >= lo:
                return name
        return "red"


# ---------------------------------------------------------------------------
# WorldLightField — aggregation at a moment in time
# ---------------------------------------------------------------------------

@dataclass
class WorldLightField:
    """All LightSources active at a specific (frame, fps) pair."""
    frame: int
    fps: int
    sources: List[LightSource] = field(default_factory=list)
    crystal: str = ""

    @classmethod
    def at(cls, frame: int, fps: int, corpus: List[LightSource]) -> "WorldLightField":
        active = [s for s in corpus if s.is_active_at_frame(frame, fps)]
        field = cls(frame=frame, fps=fps, sources=active)
        field.crystal = field._compute_crystal()
        return field

    def _compute_crystal(self) -> str:
        canonical = json.dumps({
            "frame": self.frame, "fps": self.fps,
            "source_crystals": sorted([s.crystal for s in self.sources]),
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return _hash(canonical.encode("utf-8"))

    def dominant_warmth(self) -> float:
        if not self.sources:
            return 0.0
        # intensity-weighted average warmth
        total_i = sum(s.intensity for s in self.sources)
        if total_i < 1e-9:
            return 0.0
        return sum(s.temperature_warmth * s.intensity for s in self.sources) / total_i

    def color_palette(self) -> List[Tuple[float, float, float]]:
        return [s.rgb for s in self.sources]


# ---------------------------------------------------------------------------
# Retrieval primitives
# ---------------------------------------------------------------------------

def find_lights_at_frame(frame: int, fps: int,
                          corpus: List[LightSource]) -> List[LightSource]:
    return [s for s in corpus if s.is_active_at_frame(frame, fps)]


def find_lights_by_hue(target_hue: float,
                        corpus: List[LightSource],
                        k: int = 5,
                        max_delta: float = 30.0) -> List[Dict[str, Any]]:
    """Nearest-hue retrieval. target_hue ∈ [0, 360]. max_delta = max acceptable
    hue distance in degrees (circular)."""
    scored = []
    for s in corpus:
        h = s.hsl[0]
        delta = min(abs(h - target_hue), 360 - abs(h - target_hue))
        if delta > max_delta:
            continue
        scored.append({
            "crystal": s.crystal[:16],
            "hue": h,
            "delta_hue": round(delta, 3),
            "rgb": [round(x, 4) for x in s.rgb],
            "color_band": s.color_band(),
            "intensity": s.intensity,
            "position": list(s.position),
        })
    scored.sort(key=lambda x: x["delta_hue"])
    return scored[:k]


def find_lights_near(xyz: Tuple[float, float, float],
                      corpus: List[LightSource],
                      radius: float = 5.0,
                      k: int = 10) -> List[Dict[str, Any]]:
    """Spatial-proximity retrieval. Returns top-k closest within radius (meters)."""
    scored = []
    for s in corpus:
        dx = s.position[0] - xyz[0]
        dy = s.position[1] - xyz[1]
        dz = s.position[2] - xyz[2]
        d = math.sqrt(dx*dx + dy*dy + dz*dz)
        if d > radius:
            continue
        scored.append({
            "crystal": s.crystal[:16],
            "distance_m": round(d, 4),
            "position": list(s.position),
            "rgb": [round(x, 4) for x in s.rgb],
            "intensity": s.intensity,
        })
    scored.sort(key=lambda x: x["distance_m"])
    return scored[:k]


def find_lights_by_warmth(min_w: float, max_w: float,
                            corpus: List[LightSource]) -> List[Dict[str, Any]]:
    """Filter by warmth band. [-1, 1]: -1 cool, +1 warm."""
    out = []
    for s in corpus:
        if min_w <= s.temperature_warmth <= max_w:
            out.append({
                "crystal": s.crystal[:16],
                "warmth": round(s.temperature_warmth, 4),
                "color_temp_k": round(s.color_temp_k, 1),
                "color_band": s.color_band(),
                "rgb": [round(x, 4) for x in s.rgb],
                "intensity": s.intensity,
            })
    out.sort(key=lambda x: -x["warmth"])
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    import argparse, sys

    ap = argparse.ArgumentParser(description="light_source — derived light-field CLI")
    sub = ap.add_subparsers(dest="cmd")

    p_from_rgb = sub.add_parser("from-rgb", help="build LightSource from RGB triple")
    p_from_rgb.add_argument("r", type=float)
    p_from_rgb.add_argument("g", type=float)
    p_from_rgb.add_argument("b", type=float)
    p_from_rgb.add_argument("--opacity", type=float, default=1.0)
    p_from_rgb.add_argument("--x", type=float, default=0.0)
    p_from_rgb.add_argument("--y", type=float, default=0.0)
    p_from_rgb.add_argument("--z", type=float, default=0.0)
    p_from_rgb.add_argument("--frame", type=int, default=0)
    p_from_rgb.add_argument("--fps", type=int, default=60)

    p_demo = sub.add_parser("demo", help="end-to-end synthesis demo")

    args = ap.parse_args()

    if args.cmd == "from-rgb":
        ls = LightSource.from_shape_at_position_at_frame(
            rgb=(args.r, args.g, args.b),
            opacity=args.opacity,
            position=(args.x, args.y, args.z),
            active_frames={args.fps: args.frame},
        )
        print(json.dumps({
            "crystal": ls.crystal[:32],
            "rgb": list(ls.rgb),
            "hsl": [round(x, 3) for x in ls.hsl],
            "warmth": round(ls.temperature_warmth, 4),
            "color_temp_k": round(ls.color_temp_k, 1),
            "color_band": ls.color_band(),
            "intensity": ls.intensity,
            "position": list(ls.position),
            "active_frames": ls.active_frames,
        }, indent=2))

    elif args.cmd == "demo":
        # Build 4 light sources to demo the retrieval surface
        # (mimicking what svg_harvest + spatial_anchor + frame_clock would produce)
        print("--- (1) Synthesize 4 LightSources from synthetic SVG attribute_signatures ---")

        # Warm orange light at (1, 0, 2) active at frame 60 @ 60fps
        warm = LightSource.from_svg_attribute_signature(
            attribute_signature=[1.0, 0.5, 0.1, 0, 0, 0, 0.9, 0.2, 0, 0],
            position=(1.0, 0.0, 2.0),
            active_frames={60: 60, 30: 30, 24: 24},
            source_geometry_crystal="geom_square_fill",
            source_spatial_crystal="anchor_room_001",
        )
        # Cool blue light at (-2, 0, 1) active at frame 60
        cool = LightSource.from_svg_attribute_signature(
            attribute_signature=[0.1, 0.3, 1.0, 0, 0, 0, 0.7, 0.1, 0, 0],
            position=(-2.0, 0.0, 1.0),
            active_frames={60: 60, 30: 30, 24: 24},
        )
        # Green ambient at (0, 3, 0)
        green = LightSource.from_svg_attribute_signature(
            attribute_signature=[0.2, 0.9, 0.3, 0, 0, 0, 0.5, 0.05, 0, 0],
            position=(0.0, 3.0, 0.0),
            active_frames={60: 60},
        )
        # Red flash at (4, 1, 0) only active at frame 120
        red = LightSource.from_svg_attribute_signature(
            attribute_signature=[1.0, 0.05, 0.05, 0, 0, 0, 1.0, 0.0, 0, 0],
            position=(4.0, 1.0, 0.0),
            active_frames={60: 120},
        )

        corpus = [warm, cool, green, red]
        for ls in corpus:
            print(f"  {ls.color_band():<8}  warmth={ls.temperature_warmth:+.3f}  "
                  f"K={ls.color_temp_k:>6.0f}  intensity={ls.intensity:.2f}  "
                  f"pos={ls.position}  active={ls.active_frames}")

        print("\n--- (2) WorldLightField at frame 60 @ 60fps ---")
        wf = WorldLightField.at(60, 60, corpus)
        print(json.dumps({
            "frame": wf.frame, "fps": wf.fps,
            "active_count": len(wf.sources),
            "dominant_warmth": round(wf.dominant_warmth(), 4),
            "active_color_bands": [s.color_band() for s in wf.sources],
            "field_crystal": wf.crystal[:32],
        }, indent=2))

        print("\n--- (3) WorldLightField at frame 120 @ 60fps (only the red flash) ---")
        wf2 = WorldLightField.at(120, 60, corpus)
        print(json.dumps({
            "frame": wf2.frame, "fps": wf2.fps,
            "active_count": len(wf2.sources),
            "active_color_bands": [s.color_band() for s in wf2.sources],
        }, indent=2))

        print("\n--- (4) find_lights_by_hue(target=30°, max_delta=60°) — warm matches ---")
        matches = find_lights_by_hue(30.0, corpus, k=4, max_delta=60.0)
        for m in matches:
            print(f"  hue={m['hue']:>7.2f}°  Δ={m['delta_hue']:>6.2f}°  "
                  f"band={m['color_band']:<14}  rgb={m['rgb']}")

        print("\n--- (5) find_lights_near((0,0,0), radius=3.0) ---")
        near = find_lights_near((0.0, 0.0, 0.0), corpus, radius=3.0, k=5)
        for n in near:
            print(f"  d={n['distance_m']:.3f}m  pos={n['position']}  rgb={n['rgb']}")

        print("\n--- (6) find_lights_by_warmth(min=-1.0, max=-0.1)  cool lights only ---")
        cools = find_lights_by_warmth(-1.0, -0.1, corpus)
        for c in cools:
            print(f"  warmth={c['warmth']:+.3f}  K={c['color_temp_k']:>6.0f}  "
                  f"band={c['color_band']:<14}  rgb={c['rgb']}")

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
