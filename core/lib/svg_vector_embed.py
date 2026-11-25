#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        svg_vector_embed
# role:        SUBSTRATE · GEOMETRIC_VECTOR_EMBEDDING_AXIS
# tier:        L0
# substrate:   64-dim DCT-II shape descriptor per SVG path (free, pure-Python)
# engine:      SVG path parser → normalize → arc-resample → DCT-II → L2-norm
# storage:     none (stateless; caller persists embeddings via svg_harvest.sh)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.svg_vector_embed.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/scripts/svg_harvest.sh         (every local SVG file)
#   - PinterestConnector.harvest_curated  (when pin source_url is an SVG)
#   - workflow_card pinterest_vector_motherload (harvest pipeline)
#   - moe_router.find_svg_neighbors       (the 5th retrieval axis)
# outbound:
#   - blake3 / blake2b for path crystal
#   - stdlib only: re, math, xml.etree.ElementTree
# substrate touch:
#   - reads: SVG files (any path provided by caller)
#   - writes: none — caller (svg_harvest.sh) persists to ~/.cc/svg_index.jsonl
# determinism:
#   - same SVG path string → same 64-d embedding, byte-exact
#   - normalization makes it translation + scale invariant (shape comparison)
# ============================================================================
"""svg_vector_embed.py — parse SVG paths into geometric vector embeddings.

Pipeline per SVG file:
  1. Parse XML, extract every <path d="..." /> attribute string
  2. Walk path commands (MmLlCcQqAaZzHhVvSsTt) → coordinate sequence
  3. Normalize: center on origin, scale to unit bounding box
  4. Resample to fixed N points (linear interpolation between input points)
  5. Interleave x,y → 1D signal of length 2N
  6. DCT-II → first K coefficients
  7. L2-normalize → cosine similarity = dot product

Shape-invariant under translation and uniform scale. Rotation NOT normalized
in v0 (would need PCA on point cloud — defer).
"""
from __future__ import annotations

import hashlib
import math
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


# Tuneable constants
RESAMPLE_N = 64       # points after arc-length resample
DCT_COEFFS = 64       # DCT-II output dim → final embedding length
MAX_PATH_CHARS = 200_000  # safety cap per path d attribute


# ---------------------------------------------------------------------------
# SVG path parser
# ---------------------------------------------------------------------------

_CMD_RE   = re.compile(r"([MmLlCcQqAaZzHhVvSsTt])([^MmLlCcQqAaZzHhVvSsTt]*)")
_COORD_RE = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_path(d: str) -> List[Tuple[float, float]]:
    """Walk an SVG path 'd' attribute → list of (x, y) waypoints.

    Supports M/L/C/Q/H/V/Z (upper + lower case for absolute vs relative).
    For C/Q (Bezier), only the endpoint is kept (sufficient for shape descriptors).
    A is approximated as the endpoint. S/T are treated as endpoints only.
    """
    if not d or len(d) > MAX_PATH_CHARS:
        return []

    pts: List[Tuple[float, float]] = []
    cx, cy = 0.0, 0.0
    start_x, start_y = 0.0, 0.0

    for cmd, args in _CMD_RE.findall(d):
        nums = [float(m) for m in _COORD_RE.findall(args)]
        cl = cmd.lower()
        rel = cmd.islower()
        i = 0

        if cl == "z":
            # close path → snap back to subpath start
            cx, cy = start_x, start_y
            pts.append((cx, cy))
            continue

        while i < len(nums):
            try:
                if cl == "m":
                    nx = nums[i] + (cx if rel else 0)
                    ny = nums[i + 1] + (cy if rel else 0)
                    cx, cy = nx, ny
                    start_x, start_y = cx, cy
                    pts.append((cx, cy))
                    i += 2
                    # implicit lineto for following coord pairs
                    cl = "l"
                elif cl == "l":
                    nx = nums[i] + (cx if rel else 0)
                    ny = nums[i + 1] + (cy if rel else 0)
                    cx, cy = nx, ny
                    pts.append((cx, cy))
                    i += 2
                elif cl == "h":
                    nx = nums[i] + (cx if rel else 0)
                    cx = nx
                    pts.append((cx, cy))
                    i += 1
                elif cl == "v":
                    ny = nums[i] + (cy if rel else 0)
                    cy = ny
                    pts.append((cx, cy))
                    i += 1
                elif cl == "c":
                    # cubic Bezier — endpoint only
                    nx = nums[i + 4] + (cx if rel else 0)
                    ny = nums[i + 5] + (cy if rel else 0)
                    cx, cy = nx, ny
                    pts.append((cx, cy))
                    i += 6
                elif cl == "s":
                    nx = nums[i + 2] + (cx if rel else 0)
                    ny = nums[i + 3] + (cy if rel else 0)
                    cx, cy = nx, ny
                    pts.append((cx, cy))
                    i += 4
                elif cl == "q":
                    nx = nums[i + 2] + (cx if rel else 0)
                    ny = nums[i + 3] + (cy if rel else 0)
                    cx, cy = nx, ny
                    pts.append((cx, cy))
                    i += 4
                elif cl == "t":
                    nx = nums[i] + (cx if rel else 0)
                    ny = nums[i + 1] + (cy if rel else 0)
                    cx, cy = nx, ny
                    pts.append((cx, cy))
                    i += 2
                elif cl == "a":
                    # arc — take endpoint (after 5 control numbers)
                    nx = nums[i + 5] + (cx if rel else 0)
                    ny = nums[i + 6] + (cy if rel else 0)
                    cx, cy = nx, ny
                    pts.append((cx, cy))
                    i += 7
                else:
                    i += 1
            except IndexError:
                break
    return pts


def normalize_points(pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Translate to centroid origin, scale by max bbox-dimension to unit."""
    if not pts:
        return []
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx_c, cy_c = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    scale = max(w, h)
    if scale < 1e-9:
        return [(0.0, 0.0)] * len(pts)
    return [((x - cx_c) / scale, (y - cy_c) / scale) for x, y in pts]


def resample_linear(pts: List[Tuple[float, float]], n: int) -> List[Tuple[float, float]]:
    """Resample the polyline to n points by arc-length (linear interp between waypoints)."""
    if not pts:
        return [(0.0, 0.0)] * n
    if len(pts) == 1:
        return [pts[0]] * n
    # Cumulative arc length
    cum = [0.0]
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        cum.append(cum[-1] + math.sqrt(dx * dx + dy * dy))
    total = cum[-1]
    if total < 1e-12:
        return [pts[0]] * n
    out = []
    step = total / (n - 1) if n > 1 else total
    j = 0
    for i in range(n):
        target = i * step
        while j < len(cum) - 1 and cum[j + 1] < target:
            j += 1
        if j >= len(pts) - 1:
            out.append(pts[-1])
            continue
        seg_len = cum[j + 1] - cum[j]
        if seg_len < 1e-12:
            t = 0.0
        else:
            t = (target - cum[j]) / seg_len
        x = pts[j][0] + t * (pts[j + 1][0] - pts[j][0])
        y = pts[j][1] + t * (pts[j + 1][1] - pts[j][1])
        out.append((x, y))
    return out


def _dct_ii(samples: List[float], n_coeffs: int) -> List[float]:
    N = len(samples)
    if N == 0:
        return [0.0] * n_coeffs
    out: List[float] = []
    limit = min(n_coeffs, N)
    for k in range(limit):
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


def svg_path_embedding(d: str,
                        resample_n: int = RESAMPLE_N,
                        dct_coeffs: int = DCT_COEFFS) -> List[float]:
    """End-to-end pipeline: SVG 'd' string → 64-dim shape descriptor."""
    pts = parse_path(d)
    pts = normalize_points(pts)
    samples = resample_linear(pts, resample_n)
    # Interleave x and y → 1D signal of length 2*resample_n
    signal: List[float] = []
    for x, y in samples:
        signal.append(x)
        signal.append(y)
    spectrum = _dct_ii(signal, dct_coeffs)
    return _l2_normalize(spectrum)


# ---------------------------------------------------------------------------
# SVG file walker — extract every <path> element
# ---------------------------------------------------------------------------

# Strip default XML namespace so .findall('path') works on any SVG
_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_RE.sub("", tag)


@dataclass
class SvgPathRecord:
    src_file: str
    path_index: int        # 0-based index within the file
    d: str                  # path 'd' attribute (truncated for storage)
    point_count: int        # waypoints after parsing
    embedding: List[float]
    crystal: str            # blake3 of (src_file + path_index + d_canonical)
    bbox: Tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax) before normalization
    # Shape-family tracking — same geometry_crystal + different attrs = same family
    geometry_crystal: str = ""    # blake3 of NORMALIZED resampled coordinates only
    attribute_signature: List[float] = field(default_factory=list)  # 10-d: fill rgb, stroke rgb, opacity, stroke-width, has_gradient, has_pattern
    fill: str = ""
    stroke: str = ""
    opacity: float = 1.0
    stroke_width: float = 0.0


def extract_paths_from_file(svg_path: str | Path) -> List[Dict[str, Any]]:
    """Parse an SVG file. Returns a list of {d, attrib} per <path> element."""
    p = Path(svg_path)
    try:
        tree = ET.parse(p)
    except (ET.ParseError, OSError):
        return []
    root = tree.getroot()
    out: List[Dict[str, Any]] = []
    for el in root.iter():
        if _strip_ns(el.tag) != "path":
            continue
        d = el.attrib.get("d") or el.attrib.get("D")
        if d:
            out.append({"d": d, "attrib": dict(el.attrib)})
    return out


_COLOR_RE = re.compile(r"#([0-9a-fA-F]{3,8})|rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")


def parse_color(s: str) -> Tuple[float, float, float]:
    """Parse a CSS color (#rrggbb or rgb()) → (r, g, b) in [0, 1]. None or 'none' → (0,0,0)."""
    if not s or s.lower() in ("none", "transparent", "inherit"):
        return (0.0, 0.0, 0.0)
    m = _COLOR_RE.search(s)
    if not m:
        return (0.0, 0.0, 0.0)
    if m.group(1):
        h = m.group(1)
        if len(h) == 3:    # #rgb
            h = "".join(c + c for c in h)
        if len(h) >= 6:
            r = int(h[0:2], 16) / 255.0
            g = int(h[2:4], 16) / 255.0
            b = int(h[4:6], 16) / 255.0
            return (r, g, b)
        return (0.0, 0.0, 0.0)
    return (int(m.group(2)) / 255.0, int(m.group(3)) / 255.0, int(m.group(4)) / 255.0)


def extract_attribute_signature(attrib: Dict[str, Any], style_str: str = "") -> Dict[str, Any]:
    """From an SVG <path> attribute dict (+ optional inline style),
    extract the shape-family attribute vector."""
    # Merge inline style with attributes (style overrides)
    style: Dict[str, str] = {}
    for k, v in (attrib or {}).items():
        if isinstance(v, str):
            style[k.lower()] = v
    for kv in (style_str or "").split(";"):
        if ":" in kv:
            kk, vv = kv.split(":", 1)
            style[kk.strip().lower()] = vv.strip()

    fill = style.get("fill", "")
    stroke = style.get("stroke", "")
    try:
        opacity = float(style.get("opacity", "1") or 1)
    except ValueError:
        opacity = 1.0
    try:
        stroke_width = float(style.get("stroke-width", "0") or 0)
    except ValueError:
        stroke_width = 0.0

    fr, fg, fb = parse_color(fill)
    sr, sg, sb = parse_color(stroke)
    has_gradient = 1.0 if ("url(#" in fill or "url(#" in stroke) else 0.0
    has_pattern = 1.0 if ("pattern" in fill.lower() or "pattern" in stroke.lower()) else 0.0

    return {
        "fill": fill,
        "stroke": stroke,
        "opacity": opacity,
        "stroke_width": stroke_width,
        "signature": [fr, fg, fb, sr, sg, sb,
                       opacity, min(stroke_width / 10.0, 1.0),
                       has_gradient, has_pattern],
    }


def embed_svg_file(svg_path: str | Path) -> List[SvgPathRecord]:
    """For each <path> in the SVG, produce an SvgPathRecord with embedding +
    attribute signature for shape-family tracking."""
    paths = extract_paths_from_file(svg_path)
    out: List[SvgPathRecord] = []
    for i, item in enumerate(paths):
        d = item["d"]
        attrib = item.get("attrib", {})
        pts_raw = parse_path(d)
        if not pts_raw:
            continue
        xs = [p[0] for p in pts_raw]
        ys = [p[1] for p in pts_raw]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        emb = svg_path_embedding(d)

        canonical = f"{svg_path}|{i}|{d[:1024]}".encode("utf-8")
        crystal = _hash(canonical)

        # geometry_crystal = blake3 of NORMALIZED resampled coordinates only.
        # Two paths with the same shape (regardless of fill/stroke/opacity) get
        # the same geometry_crystal → SHAPE FAMILY membership.
        pts_norm = normalize_points(pts_raw)
        samples = resample_linear(pts_norm, RESAMPLE_N)
        coord_str = "|".join(f"{x:.4f},{y:.4f}" for x, y in samples)
        geometry_crystal = _hash(coord_str.encode("utf-8"))

        attr = extract_attribute_signature(attrib, attrib.get("style", ""))

        out.append(SvgPathRecord(
            src_file=str(svg_path),
            path_index=i,
            d=d[:512],
            point_count=len(pts_raw),
            embedding=emb,
            crystal=crystal,
            bbox=bbox,
            geometry_crystal=geometry_crystal,
            attribute_signature=attr["signature"],
            fill=attr["fill"][:32],
            stroke=attr["stroke"][:32],
            opacity=attr["opacity"],
            stroke_width=attr["stroke_width"],
        ))
    return out


def find_shape_family(geometry_crystal: str, corpus: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Given a geometry_crystal, find ALL paths in the corpus with the same shape
    but potentially different attributes — the 'square vs blue square' lens."""
    family: List[Dict[str, Any]] = []
    for item in corpus:
        if item.get("geometry_crystal") == geometry_crystal:
            family.append(item)
    return family


# ---------------------------------------------------------------------------
# Retrieval — find similar SVG paths
# ---------------------------------------------------------------------------

def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        n = min(len(a), len(b))
        a = a[:n]; b = b[:n]
    return sum(x * y for x, y in zip(a, b))


def find_svg_neighbors(query_d: str,
                        corpus: List[Dict[str, Any]],
                        k: int = 5,
                        min_sim: float = 0.0) -> List[Dict[str, Any]]:
    """Each corpus entry: {embedding: List[float], ...}.
    Returns top-k by cosine similarity over the SVG-shape embedding."""
    q_emb = svg_path_embedding(query_d)
    scored = []
    for item in corpus:
        emb = item.get("embedding") or []
        if not emb:
            continue
        sim = cosine_similarity(q_emb, emb)
        if sim < min_sim:
            continue
        scored.append({**{k: v for k, v in item.items() if k != "embedding"},
                       "svg_sim": round(sim, 6)})
    scored.sort(key=lambda x: -x["svg_sim"])
    return scored[:k]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _compact_record(r: SvgPathRecord, head: int = 8) -> Dict[str, Any]:
    return {
        "src_file": r.src_file,
        "path_index": r.path_index,
        "point_count": r.point_count,
        "crystal": r.crystal[:16],
        "bbox": [round(v, 3) for v in r.bbox],
        "embedding_head": [round(x, 5) for x in r.embedding[:head]],
        "d_head": r.d[:80],
    }


def _main():
    import argparse, json
    ap = argparse.ArgumentParser(description="svg_vector_embed — geometric shape embeddings")
    sub = ap.add_subparsers(dest="cmd")

    p_emb = sub.add_parser("embed", help="parse a 'd' string and emit its 64-d embedding")
    p_emb.add_argument("d_string")

    p_file = sub.add_parser("file", help="extract + embed every <path> in an SVG file")
    p_file.add_argument("svg_path")
    p_file.add_argument("--full", action="store_true")

    p_cmp = sub.add_parser("compare", help="compare two SVG 'd' strings on the shape axis")
    p_cmp.add_argument("a"); p_cmp.add_argument("b")

    args = ap.parse_args()

    if args.cmd == "embed":
        emb = svg_path_embedding(args.d_string)
        print(json.dumps({
            "len": len(emb),
            "norm": round(math.sqrt(sum(x*x for x in emb)), 6),
            "head": [round(x, 5) for x in emb[:12]],
        }, indent=2))

    elif args.cmd == "file":
        recs = embed_svg_file(args.svg_path)
        if args.full:
            print(json.dumps([asdict(r) for r in recs], indent=2))
        else:
            print(json.dumps({
                "path_count": len(recs),
                "records": [_compact_record(r) for r in recs[:10]],
                "total": len(recs),
            }, indent=2))

    elif args.cmd == "compare":
        ea = svg_path_embedding(args.a)
        eb = svg_path_embedding(args.b)
        print(json.dumps({
            "cosine_sim": round(cosine_similarity(ea, eb), 6),
            "norm_a": round(math.sqrt(sum(x*x for x in ea)), 6),
            "norm_b": round(math.sqrt(sum(x*x for x in eb)), 6),
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
