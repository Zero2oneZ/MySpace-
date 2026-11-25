#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        dag_render
# role:        VISUALIZATION · FOUR_SUB_DAG_SVG_EMITTER
# tier:        L0
# substrate:   reads dag_loop graph → emits color-coded SVG of the infinite loop
# storage:     studio/docs/LOOP-FOUR-DAG.svg
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:  cc loop render
# outbound: writes studio/docs/LOOP-FOUR-DAG.svg
# substrate: imports dag_loop (build_loop_dag + partition_by_sub_dag)
# ----------------------------------------------------------------------------
# COLOR MAP
#   PLATFORMS    → #5b8def (blue)        — external services
#   DOCS         → #4caf50 (green)        — structured knowledge
#   INFERENCE    → #ff9800 (orange)       — routing tree
#   APPS         → #9c27b0 (purple)       — emergent products
#   ORCHESTRATION → #607d8b (slate)        — runtime spine (existing agents/passes)
# ============================================================================
"""dag_render.py — emit an SVG showing the four sub-DAGs in distinct quadrants
with the loop arrows tying them into a closed cycle."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from dag_loop import build_loop_dag, partition_by_sub_dag, LoopNode, LoopEdge  # noqa: E402


COLOR = {
    "PLATFORMS":            "#5b8def",
    "DOCS":                 "#4caf50",
    "INFERENCE":            "#ff9800",
    "APPS":                 "#9c27b0",
    "RECURSIVE_WORKFLOWS":  "#e53935",
    "ORCHESTRATION":        "#607d8b",
}

# Quadrant centers (in SVG coords). Width=1600, Height=1100.
QUADRANT_CENTER = {
    "PLATFORMS":            (380,  280),    # top-left
    "DOCS":                 (1220, 280),    # top-right
    "INFERENCE":            (1220, 800),    # bottom-right
    "APPS":                 (380,  800),    # bottom-left
    "RECURSIVE_WORKFLOWS":  (800,  540),    # center — the meta-DAG
    "ORCHESTRATION":        (800,  540),    # reserved, overlaps center
}

QUADRANT_RADIUS = 280   # how far nodes can splay from center

W, H = 1600, 1100


def _layout_quadrant(node_ids: List[str], center: Tuple[int, int]) -> Dict[str, Tuple[int, int]]:
    """Spiral-layout nodes inside a quadrant for readability."""
    cx, cy = center
    positions: Dict[str, Tuple[int, int]] = {}
    n = len(node_ids)
    if n == 0:
        return positions
    import math
    for i, nid in enumerate(sorted(node_ids)):
        # Concentric rings: every 12 nodes goes one ring out
        ring = i // 12
        slot = i % 12
        radius = 60 + ring * 80
        angle = (slot / 12.0) * 2 * math.pi
        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))
        positions[nid] = (x, y)
    return positions


def render_svg() -> str:
    nodes, edges = build_loop_dag()
    part = partition_by_sub_dag(nodes)

    positions: Dict[str, Tuple[int, int]] = {}
    for sub_dag, center in QUADRANT_CENTER.items():
        positions.update(_layout_quadrant(part.get(sub_dag, []), center))

    out: List[str] = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
                f'font-family="Inter, system-ui, sans-serif">')
    out.append('<style>')
    out.append('  .lbl { font-size: 10px; fill: #1a1a1a; }')
    out.append('  .quad { font-size: 22px; font-weight: 700; fill: #fff; }')
    out.append('  .count { font-size: 14px; fill: #fff; opacity: 0.85; }')
    out.append('  .loop { fill: none; stroke-width: 6; opacity: 0.55; }')
    out.append('</style>')
    out.append(f'<rect width="{W}" height="{H}" fill="#fafafa"/>')

    # Quadrant background panels
    panels = [
        ("PLATFORMS",            50,    50,  710,  470),
        ("DOCS",                 840,    50,  710,  470),
        ("INFERENCE",            840,   560,  710,  490),
        ("APPS",                  50,   560,  710,  490),
        # 5th panel: center overlay for RECURSIVE_WORKFLOWS — the meta-DAG
        ("RECURSIVE_WORKFLOWS",  590,   415,  420,  270),
    ]
    for sub_dag, x, y, w, h in panels:
        col = COLOR[sub_dag]
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                    f'fill="{col}" opacity="0.10" rx="14" ry="14"/>')
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="44" '
                    f'fill="{col}" rx="14" ry="14"/>')
        count = len(part.get(sub_dag, []))
        out.append(f'<text x="{x + 18}" y="{y + 30}" class="quad">{sub_dag} DAG</text>')
        out.append(f'<text x="{x + w - 18}" y="{y + 30}" class="count" '
                    f'text-anchor="end">{count} nodes</text>')

    # The 4 closing loop arrows around the perimeter (PLATFORMS → DOCS → INFERENCE → APPS → PLATFORMS)
    loop_arrows = [
        ("PLATFORMS", "DOCS",        760,  290,   840,  290),
        ("DOCS",      "INFERENCE",  1195,  525,  1195,  555),
        ("INFERENCE", "APPS",        840,  810,   760,  810),
        ("APPS",      "PLATFORMS",   405,  555,   405,  525),
    ]
    for src_sub, dst_sub, x1, y1, x2, y2 in loop_arrows:
        col_src = COLOR[src_sub]
        col_dst = COLOR[dst_sub]
        # Gradient line — just use src color for simplicity
        out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                    f'class="loop" stroke="{col_src}" '
                    f'marker-end="url(#arrow_{dst_sub.lower()})"/>')

    # Arrow markers (one per sub-DAG color)
    out.append('<defs>')
    for sub_dag, col in COLOR.items():
        out.append(f'<marker id="arrow_{sub_dag.lower()}" viewBox="0 0 10 10" '
                    f'refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
                    f'<path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    out.append('</defs>')

    # Edges within and across quadrants (intra+cross)
    for e in edges:
        src_pos = positions.get(e.src)
        dst_pos = positions.get(e.dst)
        if not src_pos or not dst_pos:
            continue
        src_node = nodes.get(e.src)
        if not src_node:
            continue
        col = COLOR.get(src_node.sub_dag, "#888")
        opacity = 0.25 if e.kind == "calls" else 0.55
        out.append(f'<line x1="{src_pos[0]}" y1="{src_pos[1]}" '
                    f'x2="{dst_pos[0]}" y2="{dst_pos[1]}" '
                    f'stroke="{col}" stroke-width="1" opacity="{opacity}"/>')

    # Nodes
    for nid, n in nodes.items():
        pos = positions.get(nid)
        if not pos:
            continue
        x, y = pos
        col = COLOR.get(n.sub_dag, "#888")
        status_alpha = {
            "ACTIVE":           1.0,
            "IN-FLIGHT":        0.7,
            "STUB":             0.5,
            "TEXT-PLACEHOLDER": 0.35,
        }.get(n.status, 0.65)
        out.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{col}" '
                    f'opacity="{status_alpha}" stroke="#1a1a1a" stroke-width="0.5"/>')
        # Truncate name; only show short label
        lbl = n.name[:16]
        out.append(f'<text x="{x + 9}" y="{y + 3}" class="lbl">{lbl}</text>')

    # Title
    out.append('<text x="800" y="38" text-anchor="middle" '
                'font-size="20" font-weight="700" fill="#1a1a1a">'
                'The Infinite Loop · Five Sub-DAGs · Recursion at the Center</text>')

    out.append('</svg>')
    return "\n".join(out)


def write_svg(out_path: Path = None) -> Path:
    if out_path is None:
        out_path = _HERE.parent.parent / "studio" / "docs" / "LOOP-FOUR-DAG.svg"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_svg(), encoding="utf-8")
    return out_path


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="dag_render — emit four-DAG loop SVG")
    ap.add_argument("--out", default=None, help="output SVG path (default: studio/docs/LOOP-FOUR-DAG.svg)")
    args = ap.parse_args()
    out_path = Path(args.out) if args.out else None
    path = write_svg(out_path)
    print(f"wrote {path}")


if __name__ == "__main__":
    _main()
