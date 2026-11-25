#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        friend_graph_visualizer                                        =
# role:        VISUALIZATION · STATIC_SVG_SOCIAL_GRAPH_RENDERER               =
# tier:        L0                                                             =
# substrate:   stdlib SVG emission (xml.etree.ElementTree + string concat)    =
# engine:      equirectangular / orthographic projection + cubic-bezier edges =
# storage:     ~/.cc/planet_renders/<crystal_short>.svg                       =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.friend_graph_visualizer.active.j =
# ----------------------------------------------------------------------------=
# COMPLEMENT TO: studio/godot/project/scenes/planet_map.tscn (interactive 3D) =
# This file = server-side 2D static renderer for:                             =
#   - dApp OG / share preview images                                          =
#   - email reports                                                           =
#   - dialectic_walker visualizations                                         =
#   - crystal-chain audit reports                                             =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# inbound:                                                                    =
#   - cc -friend-graph-render <player_id>  (planned core/cc.sh dispatcher)    =
#   - dialectic_walker (renders walked-graph snapshots)                       =
#   - dapp_server /dapp/api/social_graph/png?player_id=<id> (planned)         =
# outbound:                                                                   =
#   - social_graph_persistence::export_for_planet_map / find_in_radius        =
#   - inference_logger.InferenceLogger.log (crystal anchor every render)      =
#   - svg_vector_embed.embed_svg_file (post-write geometry_crystal)           =
# ============================================================================
"""friend_graph_visualizer.py — server-side static SVG of the social graph.

Three modes, all stdlib (no matplotlib, no cairo):

  1. render_world_map     — equirectangular 1200x630 (OG / share preview shape)
  2. render_globe_view    — orthographic from a chosen longitude (Earth-from-space)
  3. render_progression   — N small globes side-by-side, one per snapshot dict

Color coding by graph distance from the source player:
  hop 0 (source) = red
  hop 1          = orange
  hop 2          = yellow
  hop 3+         = light yellow / grey

Edges are cubic bezier curves with a control point pulled toward the equator
in equirectangular mode, and toward the projected center in globe/orthographic.

Crystal anchor: every render appends an inference_logger row with tier
'visualization', model 'friend_graph_visualizer'.
"""

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# graceful import of social_graph_persistence (agent F may not be done yet)
# ---------------------------------------------------------------------------
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

_HAS_SOCIAL_GRAPH = False
try:
    import social_graph_persistence as sgp  # type: ignore
    _HAS_SOCIAL_GRAPH = True
except Exception:
    sgp = None  # type: ignore

# inference_logger — for crystal anchoring; optional so renderer still works in isolation
try:
    from inference_logger import InferenceLogger  # type: ignore
    _HAS_LOGGER = True
except Exception:
    InferenceLogger = None  # type: ignore
    _HAS_LOGGER = False


# ---------------------------------------------------------------------------
# Constants — canvas geometry, theme palettes, continent outlines
# ---------------------------------------------------------------------------
WORLD_WIDTH = 1200
WORLD_HEIGHT = 630
WORLD_MARGIN_X = 40
WORLD_MARGIN_Y = 70   # leave room for title + footer

GLOBE_WIDTH = 1200
GLOBE_HEIGHT = 630
GLOBE_RADIUS_PX = 280  # rendered globe radius

PROGRESSION_PANEL_W = 320
PROGRESSION_PANEL_H = 320

THEMES = {
    "dark": {
        "bg":             "#0a0e1a",
        "title":          "#e8eef9",
        "subtitle":       "#8893a8",
        "grid":           "#1a2238",
        "continent":      "#172033",
        "continent_edge": "#243149",
        "edge":           "#3a4a6a",
        "edge_self":      "#ff7a59",
        "footer":         "#5b6378",
        "hop":            ["#ff3b30", "#ff9500", "#ffcc00", "#ffe680", "#a8b0c0"],
        "node_stroke":    "#0a0e1a",
        "globe_fill":     "#0e1424",
    },
    "light": {
        "bg":             "#f5f7fb",
        "title":          "#11151c",
        "subtitle":       "#5b6378",
        "grid":           "#dde3ee",
        "continent":      "#e3e9f3",
        "continent_edge": "#c5cdd9",
        "edge":           "#a4b0c4",
        "edge_self":      "#ff5a36",
        "footer":         "#7d8595",
        "hop":            ["#d6342b", "#e67700", "#d9a300", "#b9a043", "#8893a8"],
        "node_stroke":    "#f5f7fb",
        "globe_fill":     "#dfe5f1",
    },
}

# Simple, generic continent rectangles (NOT real geo data — placeholders so the
# map reads as "a map" without shipping a GeoJSON). Each entry is a polygon of
# [lon, lat] vertices. Roughly: N America, S America, Europe, Africa, Asia,
# Oceania, Antarctica — plus a few sub-shapes to break up the geometry.
CONTINENT_POLYGONS: List[List[Tuple[float, float]]] = [
    # North America (main mass)
    [(-165, 70), (-130, 72), (-95, 72), (-75, 65), (-65, 50), (-70, 42),
     (-80, 28), (-97, 26), (-110, 28), (-125, 35), (-130, 52), (-155, 60), (-165, 70)],
    # Central America strip
    [(-105, 22), (-92, 18), (-85, 12), (-78, 9), (-82, 16), (-95, 20), (-105, 22)],
    # South America
    [(-78, 10), (-55, 8), (-40, 0), (-35, -10), (-42, -25), (-58, -38),
     (-72, -52), (-74, -38), (-78, -18), (-80, 0), (-78, 10)],
    # Europe (rough)
    [(-10, 60), (5, 62), (25, 65), (40, 60), (42, 50), (30, 42),
     (15, 40), (0, 42), (-10, 48), (-10, 60)],
    # Africa
    [(-17, 35), (10, 36), (32, 32), (38, 18), (45, 5), (40, -10),
     (32, -28), (20, -34), (10, -30), (8, -10), (0, 5), (-12, 18), (-17, 35)],
    # Asia (the big mass)
    [(40, 65), (75, 70), (110, 72), (140, 70), (165, 65), (155, 50),
     (135, 40), (122, 28), (105, 20), (95, 12), (78, 8),
     (68, 22), (50, 30), (38, 38), (40, 50), (40, 65)],
    # SE Asia / Indonesia clump
    [(95, 5), (115, 8), (135, 5), (140, -5), (125, -10),
     (108, -8), (98, -2), (95, 5)],
    # Oceania (Australia)
    [(115, -12), (140, -10), (153, -18), (152, -32), (138, -38),
     (118, -34), (112, -22), (115, -12)],
    # Antarctica strip
    [(-180, -68), (-90, -72), (0, -75), (90, -72), (180, -68),
     (180, -85), (-180, -85), (-180, -68)],
    # Greenland
    [(-55, 80), (-30, 82), (-22, 75), (-32, 60), (-50, 60), (-55, 70), (-55, 80)],
    # UK / Ireland blob
    [(-10, 60), (-2, 60), (2, 52), (-6, 49), (-12, 53), (-10, 60)],
    # Japan
    [(132, 42), (142, 42), (143, 35), (137, 32), (130, 35), (132, 42)],
    # Madagascar
    [(43, -12), (50, -16), (50, -24), (45, -25), (43, -18), (43, -12)],
    # New Zealand
    [(166, -40), (175, -38), (178, -45), (170, -47), (166, -42), (166, -40)],
]


# ---------------------------------------------------------------------------
# Projection helpers
# ---------------------------------------------------------------------------
def equirectangular(lon: float, lat: float,
                    width: int = WORLD_WIDTH,
                    height: int = WORLD_HEIGHT,
                    mx: int = WORLD_MARGIN_X,
                    my: int = WORLD_MARGIN_Y) -> Tuple[float, float]:
    """Map (lon, lat) → (x, y) in canvas coords. lat→ -y so north is up."""
    inner_w = width - 2 * mx
    inner_h = height - 2 * my
    x = mx + (lon + 180.0) / 360.0 * inner_w
    y = my + (90.0 - lat) / 180.0 * inner_h
    return x, y


def orthographic(lon: float, lat: float,
                 center_lon: float = 0.0,
                 center_lat: float = 0.0,
                 cx: float = GLOBE_WIDTH / 2,
                 cy: float = GLOBE_HEIGHT / 2,
                 r: float = GLOBE_RADIUS_PX) -> Optional[Tuple[float, float]]:
    """Standard orthographic projection. Returns None if the point is on the
    far side of the planet (back-face culled)."""
    lam = math.radians(lon - center_lon)
    phi = math.radians(lat)
    phi0 = math.radians(center_lat)
    # Visibility test: cos(c) >= 0
    cos_c = (math.sin(phi0) * math.sin(phi) +
             math.cos(phi0) * math.cos(phi) * math.cos(lam))
    if cos_c < 0:
        return None
    x = cx + r * math.cos(phi) * math.sin(lam)
    y = cy - r * (math.cos(phi0) * math.sin(phi) -
                  math.sin(phi0) * math.cos(phi) * math.cos(lam))
    return x, y


# ---------------------------------------------------------------------------
# BFS hop distance for color coding
# ---------------------------------------------------------------------------
def _hops_from(source_id: str,
               nodes_by_id: Dict[str, Dict[str, Any]],
               adjacency: Dict[str, List[str]],
               max_hops: int) -> Dict[str, int]:
    """Plain BFS — distance in hops from source to every reachable node."""
    dist: Dict[str, int] = {source_id: 0}
    frontier = [source_id]
    for h in range(1, max_hops + 1):
        next_frontier: List[str] = []
        for u in frontier:
            for v in adjacency.get(u, []):
                if v in dist:
                    continue
                if v not in nodes_by_id:
                    continue
                dist[v] = h
                next_frontier.append(v)
        if not next_frontier:
            break
        frontier = next_frontier
    return dist


# ---------------------------------------------------------------------------
# Graph fetch — calls into agent F if present, else returns a stub
# ---------------------------------------------------------------------------
def _fetch_graph(player_id: str, max_hops: int, max_nodes: int) -> Dict[str, Any]:
    """Returns: {players: [...], friendships: [...], _stub|_error: '...'}.

    If social_graph_persistence is missing OR the player isn't in the store,
    a degenerate single-node graph is returned so the renderer ALWAYS emits a
    meaningful SVG (and downstream pipelines never crash on empty payloads)."""
    if _HAS_SOCIAL_GRAPH and sgp is not None:
        try:
            data = sgp.export_for_planet_map(
                player_id, max_hops=max_hops, max_nodes=max_nodes
            )
            if not isinstance(data, dict):
                data = {"players": [], "friendships": []}
            players = data.get("players", []) or []
            ids = {p.get("player_id") for p in players if isinstance(p, dict)}
            # Edge case: store exists but the requested player isn't in it —
            # synthesize a stub node so the renderer still labels the subject.
            if player_id not in ids:
                data = dict(data)
                data["players"] = list(players) + [
                    {"player_id": player_id, "name": player_id,
                     "lat": 0.0, "lon": 0.0}
                ]
                data["_stub"] = f"player_id '{player_id}' not in social_graph store"
            return data
        except Exception as e:
            return {
                "players": [{"player_id": player_id, "name": player_id,
                             "lat": 0.0, "lon": 0.0}],
                "friendships": [],
                "_error": f"sgp export failed: {e!r}",
            }
    return {
        "players": [{"player_id": player_id, "name": player_id,
                     "lat": 0.0, "lon": 0.0}],
        "friendships": [],
        "_stub": "social_graph_persistence not yet built — stub render",
    }


# ---------------------------------------------------------------------------
# SVG element helpers (xml.etree — we use it for the document then a few
# string formatters for fast path/text emission inline)
# ---------------------------------------------------------------------------
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def _root(width: int, height: int, theme: Dict[str, str]) -> ET.Element:
    root = ET.Element(f"{{{SVG_NS}}}svg", {
        "viewBox": f"0 0 {width} {height}",
        "width": str(width),
        "height": str(height),
        "xmlns": SVG_NS,
    })
    ET.SubElement(root, f"{{{SVG_NS}}}rect", {
        "x": "0", "y": "0", "width": str(width), "height": str(height),
        "fill": theme["bg"],
    })
    return root


def _text(parent: ET.Element, x: float, y: float, content: str,
          fill: str, size: int = 14, anchor: str = "start",
          weight: str = "normal", family: str = "Inter,Helvetica,Arial,sans-serif") -> None:
    el = ET.SubElement(parent, f"{{{SVG_NS}}}text", {
        "x": f"{x:.1f}", "y": f"{y:.1f}",
        "fill": fill,
        "font-family": family,
        "font-size": str(size),
        "font-weight": weight,
        "text-anchor": anchor,
    })
    el.text = content


def _grid_lines_equirect(parent: ET.Element, theme: Dict[str, str]) -> None:
    """Light lat/lon grid lines for the equirectangular projection."""
    g = ET.SubElement(parent, f"{{{SVG_NS}}}g", {
        "stroke": theme["grid"], "stroke-width": "0.5",
        "fill": "none", "opacity": "0.6",
    })
    for lon in range(-180, 181, 30):
        x, y0 = equirectangular(lon, 90)
        _, y1 = equirectangular(lon, -90)
        ET.SubElement(g, f"{{{SVG_NS}}}line", {
            "x1": f"{x:.1f}", "y1": f"{y0:.1f}",
            "x2": f"{x:.1f}", "y2": f"{y1:.1f}",
        })
    for lat in range(-60, 61, 30):
        x0, y = equirectangular(-180, lat)
        x1, _ = equirectangular(180, lat)
        ET.SubElement(g, f"{{{SVG_NS}}}line", {
            "x1": f"{x0:.1f}", "y1": f"{y:.1f}",
            "x2": f"{x1:.1f}", "y2": f"{y:.1f}",
        })
    # equator a touch brighter
    x0, y_eq = equirectangular(-180, 0)
    x1, _ = equirectangular(180, 0)
    ET.SubElement(g, f"{{{SVG_NS}}}line", {
        "x1": f"{x0:.1f}", "y1": f"{y_eq:.1f}",
        "x2": f"{x1:.1f}", "y2": f"{y_eq:.1f}",
        "opacity": "0.9", "stroke-width": "0.8",
    })


def _continents_equirect(parent: ET.Element, theme: Dict[str, str]) -> None:
    g = ET.SubElement(parent, f"{{{SVG_NS}}}g", {
        "fill": theme["continent"], "stroke": theme["continent_edge"],
        "stroke-width": "0.7", "opacity": "0.95",
    })
    for poly in CONTINENT_POLYGONS:
        pts: List[str] = []
        for lon, lat in poly:
            x, y = equirectangular(lon, lat)
            pts.append(f"{x:.1f},{y:.1f}")
        ET.SubElement(g, f"{{{SVG_NS}}}polygon", {"points": " ".join(pts)})


def _continents_globe(parent: ET.Element, theme: Dict[str, str],
                      center_lon: float, center_lat: float) -> None:
    """Project continent polygons onto the globe; skip ones fully on the back."""
    g = ET.SubElement(parent, f"{{{SVG_NS}}}g", {
        "fill": theme["continent"], "stroke": theme["continent_edge"],
        "stroke-width": "0.7", "opacity": "0.95",
    })
    for poly in CONTINENT_POLYGONS:
        pts: List[str] = []
        # Densify the poly so projected curves look smoother on the globe
        for i in range(len(poly)):
            lon_a, lat_a = poly[i]
            lon_b, lat_b = poly[(i + 1) % len(poly)]
            steps = 6
            for k in range(steps):
                t = k / steps
                lon = lon_a + (lon_b - lon_a) * t
                lat = lat_a + (lat_b - lat_a) * t
                p = orthographic(lon, lat, center_lon, center_lat)
                if p is not None:
                    pts.append(f"{p[0]:.1f},{p[1]:.1f}")
        if len(pts) >= 3:
            ET.SubElement(g, f"{{{SVG_NS}}}polygon", {"points": " ".join(pts)})


def _draw_globe_disk(parent: ET.Element, theme: Dict[str, str]) -> None:
    """Background ocean disk for the orthographic globe."""
    ET.SubElement(parent, f"{{{SVG_NS}}}circle", {
        "cx": f"{GLOBE_WIDTH / 2:.1f}", "cy": f"{GLOBE_HEIGHT / 2:.1f}",
        "r": f"{GLOBE_RADIUS_PX:.1f}",
        "fill": theme["globe_fill"], "stroke": theme["continent_edge"],
        "stroke-width": "1.0",
    })


def _short_crystal(s: str) -> str:
    return s[:8] if s else "no_chain"


# ---------------------------------------------------------------------------
# render_world_map
# ---------------------------------------------------------------------------
def render_world_map(player_id: str,
                     output_path: Optional[str] = None,
                     max_hops: int = 2,
                     max_nodes: int = 200,
                     theme: str = "dark") -> Path:
    """Equirectangular 1200x630 social graph centered on player_id.

    Color codes by hop distance. Friendship edges are cubic-bezier curves with
    a control point pulled toward the equator.  Writes the SVG to output_path
    (default ~/.cc/planet_renders/<crystal_short>.svg) and crystal-anchors the
    render in the inference chain.
    """
    th = THEMES.get(theme, THEMES["dark"])

    data = _fetch_graph(player_id, max_hops, max_nodes)
    players = data.get("players", []) or []
    friendships = data.get("friendships", []) or []

    nodes_by_id: Dict[str, Dict[str, Any]] = {p["player_id"]: p for p in players if "player_id" in p}
    adjacency: Dict[str, List[str]] = {}
    for e in friendships:
        a, b = _edge_pair(e)
        if a and b:
            adjacency.setdefault(a, []).append(b)
            adjacency.setdefault(b, []).append(a)
    hop_dist = _hops_from(player_id, nodes_by_id, adjacency, max_hops)

    root = _root(WORLD_WIDTH, WORLD_HEIGHT, th)

    # Title
    _text(root, WORLD_WIDTH / 2, 36,
          f"MySpace++ Social Graph · {player_id}",
          th["title"], size=22, anchor="middle", weight="600")

    # subtitle (counts + stub note)
    sub_bits = [f"{len(nodes_by_id)} players",
                f"{len(friendships)} friendships",
                f"max_hops {max_hops}"]
    if data.get("_stub"):
        sub_bits.append(f"(stub: {data['_stub']})")
    elif data.get("_error"):
        sub_bits.append(f"(fallback: {data['_error']})")
    _text(root, WORLD_WIDTH / 2, 56, " · ".join(sub_bits),
          th["subtitle"], size=12, anchor="middle")

    _grid_lines_equirect(root, th)
    _continents_equirect(root, th)

    # Edges first so nodes draw on top
    g_edges = ET.SubElement(root, f"{{{SVG_NS}}}g", {
        "stroke": th["edge"], "stroke-width": "0.9",
        "fill": "none", "opacity": "0.7",
    })
    _, y_equator = equirectangular(0, 0)
    seen_pairs: set = set()
    for e in friendships:
        a, b = _edge_pair(e)
        if not (a and b) or a == b:
            continue
        key = tuple(sorted((a, b)))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        p_a = nodes_by_id.get(a)
        p_b = nodes_by_id.get(b)
        if not p_a or not p_b:
            continue
        x1, y1 = equirectangular(_lon(p_a), _lat(p_a))
        x2, y2 = equirectangular(_lon(p_b), _lat(p_b))
        # control point: midpoint, dragged 30% toward equator
        cx_mid = (x1 + x2) / 2
        cy_mid = (y1 + y2) / 2
        cy_ctrl = cy_mid + (y_equator - cy_mid) * 0.30
        stroke = th["edge_self"] if (a == player_id or b == player_id) else th["edge"]
        ET.SubElement(g_edges, f"{{{SVG_NS}}}path", {
            "d": f"M {x1:.1f} {y1:.1f} C {cx_mid:.1f} {cy_ctrl:.1f}, {cx_mid:.1f} {cy_ctrl:.1f}, {x2:.1f} {y2:.1f}",
            "stroke": stroke,
            "stroke-width": "1.4" if stroke == th["edge_self"] else "0.9",
        })

    # Nodes
    g_nodes = ET.SubElement(root, f"{{{SVG_NS}}}g", {})
    for pid, p in nodes_by_id.items():
        x, y = equirectangular(_lon(p), _lat(p))
        h = hop_dist.get(pid, max_hops + 1)
        color = th["hop"][min(h, len(th["hop"]) - 1)]
        r = 8.0 if h == 0 else max(3.0, 6.5 - h * 1.2)
        ET.SubElement(g_nodes, f"{{{SVG_NS}}}circle", {
            "cx": f"{x:.1f}", "cy": f"{y:.1f}", "r": f"{r:.1f}",
            "fill": color, "stroke": th["node_stroke"], "stroke-width": "1.0",
        })
        # source player carries a label
        if h == 0:
            label = str(p.get("name") or pid)
            _text(g_nodes, x + r + 4, y + 4, label, th["title"],
                  size=13, weight="600")

    # Crystal anchor + footer
    crystal_id = _crystal_anchor(player_id, "render_world_map", output_path)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _text(root, WORLD_MARGIN_X, WORLD_HEIGHT - 18,
          f"crystal {_short_crystal(crystal_id)} · generated {ts}",
          th["footer"], size=11)
    _text(root, WORLD_WIDTH - WORLD_MARGIN_X, WORLD_HEIGHT - 18,
          "friend_graph_visualizer · equirectangular",
          th["footer"], size=11, anchor="end")

    out = _resolve_output(output_path, crystal_id)
    _write_svg(root, out)
    return out


# ---------------------------------------------------------------------------
# render_globe_view
# ---------------------------------------------------------------------------
def render_globe_view(player_id: str,
                      output_path: Optional[str] = None,
                      orbit_lon: float = 0.0,
                      orbit_lat: float = 15.0,
                      max_hops: int = 2,
                      max_nodes: int = 200,
                      theme: str = "dark") -> Path:
    """Orthographic projection viewed from longitude `orbit_lon` at a slight
    northern tilt. Only nodes/edges on the near hemisphere are drawn."""
    th = THEMES.get(theme, THEMES["dark"])
    data = _fetch_graph(player_id, max_hops, max_nodes)
    players = data.get("players", []) or []
    friendships = data.get("friendships", []) or []
    nodes_by_id = {p["player_id"]: p for p in players if "player_id" in p}
    adjacency: Dict[str, List[str]] = {}
    for e in friendships:
        a, b = _edge_pair(e)
        if a and b:
            adjacency.setdefault(a, []).append(b)
            adjacency.setdefault(b, []).append(a)
    hop_dist = _hops_from(player_id, nodes_by_id, adjacency, max_hops)

    root = _root(GLOBE_WIDTH, GLOBE_HEIGHT, th)

    _text(root, GLOBE_WIDTH / 2, 36,
          f"MySpace++ Globe · {player_id} · view {orbit_lon:+.0f}°",
          th["title"], size=22, anchor="middle", weight="600")

    visible_count = 0
    for pid in nodes_by_id:
        p = nodes_by_id[pid]
        if orthographic(_lon(p), _lat(p), orbit_lon, orbit_lat) is not None:
            visible_count += 1
    _text(root, GLOBE_WIDTH / 2, 56,
          f"{visible_count}/{len(nodes_by_id)} visible · max_hops {max_hops}",
          th["subtitle"], size=12, anchor="middle")

    _draw_globe_disk(root, th)
    _continents_globe(root, th, orbit_lon, orbit_lat)

    # Edges (only if both endpoints visible)
    g_edges = ET.SubElement(root, f"{{{SVG_NS}}}g", {
        "stroke": th["edge"], "stroke-width": "0.9",
        "fill": "none", "opacity": "0.75",
    })
    cx, cy = GLOBE_WIDTH / 2, GLOBE_HEIGHT / 2
    seen_pairs: set = set()
    for e in friendships:
        a, b = _edge_pair(e)
        if not (a and b) or a == b:
            continue
        key = tuple(sorted((a, b)))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        p_a, p_b = nodes_by_id.get(a), nodes_by_id.get(b)
        if not p_a or not p_b:
            continue
        p1 = orthographic(_lon(p_a), _lat(p_a), orbit_lon, orbit_lat)
        p2 = orthographic(_lon(p_b), _lat(p_b), orbit_lon, orbit_lat)
        if p1 is None or p2 is None:
            continue
        x1, y1 = p1
        x2, y2 = p2
        # control point: pull midpoint toward globe center for a "great-circle-ish" arc
        mx_, my_ = (x1 + x2) / 2, (y1 + y2) / 2
        ctrl_x = mx_ + (cx - mx_) * 0.35
        ctrl_y = my_ + (cy - my_) * 0.35
        stroke = th["edge_self"] if (a == player_id or b == player_id) else th["edge"]
        ET.SubElement(g_edges, f"{{{SVG_NS}}}path", {
            "d": f"M {x1:.1f} {y1:.1f} Q {ctrl_x:.1f} {ctrl_y:.1f} {x2:.1f} {y2:.1f}",
            "stroke": stroke,
            "stroke-width": "1.4" if stroke == th["edge_self"] else "0.9",
        })

    # Nodes
    g_nodes = ET.SubElement(root, f"{{{SVG_NS}}}g", {})
    for pid, p in nodes_by_id.items():
        pt = orthographic(_lon(p), _lat(p), orbit_lon, orbit_lat)
        if pt is None:
            continue
        x, y = pt
        h = hop_dist.get(pid, max_hops + 1)
        color = th["hop"][min(h, len(th["hop"]) - 1)]
        r = 8.0 if h == 0 else max(3.0, 6.5 - h * 1.2)
        ET.SubElement(g_nodes, f"{{{SVG_NS}}}circle", {
            "cx": f"{x:.1f}", "cy": f"{y:.1f}", "r": f"{r:.1f}",
            "fill": color, "stroke": th["node_stroke"], "stroke-width": "1.0",
        })
        if h == 0:
            _text(g_nodes, x + r + 4, y + 4, str(p.get("name") or pid),
                  th["title"], size=13, weight="600")

    crystal_id = _crystal_anchor(player_id, "render_globe_view", output_path)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _text(root, WORLD_MARGIN_X, GLOBE_HEIGHT - 18,
          f"crystal {_short_crystal(crystal_id)} · generated {ts}",
          th["footer"], size=11)
    _text(root, GLOBE_WIDTH - WORLD_MARGIN_X, GLOBE_HEIGHT - 18,
          f"friend_graph_visualizer · orthographic · lon {orbit_lon:+.0f}° lat {orbit_lat:+.0f}°",
          th["footer"], size=11, anchor="end")

    out = _resolve_output(output_path, crystal_id)
    _write_svg(root, out)
    return out


# ---------------------------------------------------------------------------
# render_progression
# ---------------------------------------------------------------------------
def render_progression(player_id: str,
                       output_path: Optional[str] = None,
                       snapshots: Optional[List[Dict[str, Any]]] = None,
                       theme: str = "dark") -> Path:
    """N small globes side-by-side, one per snapshot dict.

    Each snapshot may carry:
        {'label': '2026-W18', 'players': [...], 'friendships': [...],
         'orbit_lon': 0.0, 'orbit_lat': 15.0}
    If snapshots is None or empty, falls back to a single live snapshot of the
    current graph (so the function never produces an empty file)."""
    th = THEMES.get(theme, THEMES["dark"])
    if not snapshots:
        live = _fetch_graph(player_id, 2, 200)
        snapshots = [{
            "label": time.strftime("%Y-%m-%d", time.gmtime()),
            "players": live.get("players", []),
            "friendships": live.get("friendships", []),
            "orbit_lon": 0.0,
            "orbit_lat": 15.0,
        }]

    n = len(snapshots)
    panel_w = PROGRESSION_PANEL_W
    panel_h = PROGRESSION_PANEL_H
    width = max(panel_w * n + 40 * (n + 1), 600)
    height = panel_h + 160  # title + footer + label band
    panel_globe_r = panel_w * 0.36

    root = _root(width, height, th)
    _text(root, width / 2, 40,
          f"MySpace++ Progression · {player_id}",
          th["title"], size=22, anchor="middle", weight="600")
    _text(root, width / 2, 60, f"{n} snapshots",
          th["subtitle"], size=12, anchor="middle")

    for i, snap in enumerate(snapshots):
        px = 40 + i * (panel_w + 40)
        py = 90
        cx_p = px + panel_w / 2
        cy_p = py + panel_h / 2
        # panel background
        ET.SubElement(root, f"{{{SVG_NS}}}rect", {
            "x": f"{px:.1f}", "y": f"{py:.1f}",
            "width": f"{panel_w:.1f}", "height": f"{panel_h:.1f}",
            "fill": th["grid"], "stroke": th["continent_edge"],
            "stroke-width": "0.6", "rx": "8",
        })
        # globe disk
        ET.SubElement(root, f"{{{SVG_NS}}}circle", {
            "cx": f"{cx_p:.1f}", "cy": f"{cy_p:.1f}",
            "r": f"{panel_globe_r:.1f}",
            "fill": th["globe_fill"], "stroke": th["continent_edge"],
            "stroke-width": "0.7",
        })
        orbit_lon = float(snap.get("orbit_lon", 0.0))
        orbit_lat = float(snap.get("orbit_lat", 15.0))

        # continents (in-panel orthographic with custom cx/cy/r)
        g_cont = ET.SubElement(root, f"{{{SVG_NS}}}g", {
            "fill": th["continent"], "stroke": th["continent_edge"],
            "stroke-width": "0.6", "opacity": "0.95",
        })
        for poly in CONTINENT_POLYGONS:
            pts: List[str] = []
            for k in range(len(poly)):
                lon_a, lat_a = poly[k]
                lon_b, lat_b = poly[(k + 1) % len(poly)]
                steps = 5
                for s in range(steps):
                    t = s / steps
                    lon = lon_a + (lon_b - lon_a) * t
                    lat = lat_a + (lat_b - lat_a) * t
                    p = orthographic(lon, lat, orbit_lon, orbit_lat,
                                     cx=cx_p, cy=cy_p, r=panel_globe_r)
                    if p is not None:
                        pts.append(f"{p[0]:.1f},{p[1]:.1f}")
            if len(pts) >= 3:
                ET.SubElement(g_cont, f"{{{SVG_NS}}}polygon",
                              {"points": " ".join(pts)})

        # nodes & edges
        players = snap.get("players", []) or []
        friendships = snap.get("friendships", []) or []
        nodes_by_id = {p["player_id"]: p for p in players if "player_id" in p}
        adjacency: Dict[str, List[str]] = {}
        for e in friendships:
            a, b = _edge_pair(e)
            if a and b:
                adjacency.setdefault(a, []).append(b)
                adjacency.setdefault(b, []).append(a)
        hop_dist = _hops_from(player_id, nodes_by_id, adjacency, 3)

        g_e = ET.SubElement(root, f"{{{SVG_NS}}}g", {
            "stroke": th["edge"], "stroke-width": "0.8",
            "fill": "none", "opacity": "0.7",
        })
        seen_pairs: set = set()
        for e in friendships:
            a, b = _edge_pair(e)
            if not (a and b) or a == b:
                continue
            key = tuple(sorted((a, b)))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            p_a, p_b = nodes_by_id.get(a), nodes_by_id.get(b)
            if not p_a or not p_b:
                continue
            p1 = orthographic(_lon(p_a), _lat(p_a), orbit_lon, orbit_lat,
                              cx=cx_p, cy=cy_p, r=panel_globe_r)
            p2 = orthographic(_lon(p_b), _lat(p_b), orbit_lon, orbit_lat,
                              cx=cx_p, cy=cy_p, r=panel_globe_r)
            if p1 is None or p2 is None:
                continue
            x1, y1 = p1
            x2, y2 = p2
            mx_, my_ = (x1 + x2) / 2, (y1 + y2) / 2
            ctrl_x = mx_ + (cx_p - mx_) * 0.35
            ctrl_y = my_ + (cy_p - my_) * 0.35
            stroke = th["edge_self"] if (a == player_id or b == player_id) else th["edge"]
            ET.SubElement(g_e, f"{{{SVG_NS}}}path", {
                "d": f"M {x1:.1f} {y1:.1f} Q {ctrl_x:.1f} {ctrl_y:.1f} {x2:.1f} {y2:.1f}",
                "stroke": stroke,
            })
        g_n = ET.SubElement(root, f"{{{SVG_NS}}}g", {})
        for pid, p in nodes_by_id.items():
            pt = orthographic(_lon(p), _lat(p), orbit_lon, orbit_lat,
                              cx=cx_p, cy=cy_p, r=panel_globe_r)
            if pt is None:
                continue
            x, y = pt
            h = hop_dist.get(pid, 4)
            color = th["hop"][min(h, len(th["hop"]) - 1)]
            r = 5.0 if h == 0 else max(2.0, 4.0 - h * 0.8)
            ET.SubElement(g_n, f"{{{SVG_NS}}}circle", {
                "cx": f"{x:.1f}", "cy": f"{y:.1f}", "r": f"{r:.1f}",
                "fill": color, "stroke": th["node_stroke"], "stroke-width": "0.8",
            })

        # snapshot label
        label = str(snap.get("label", f"snap_{i}"))
        _text(root, cx_p, py + panel_h + 24, label, th["title"],
              size=14, anchor="middle", weight="600")
        meta = f"{len(nodes_by_id)} players · {len(friendships)} edges"
        _text(root, cx_p, py + panel_h + 42, meta, th["subtitle"],
              size=11, anchor="middle")

    crystal_id = _crystal_anchor(player_id, "render_progression", output_path)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _text(root, 40, height - 18,
          f"crystal {_short_crystal(crystal_id)} · generated {ts}",
          th["footer"], size=11)
    _text(root, width - 40, height - 18,
          "friend_graph_visualizer · progression",
          th["footer"], size=11, anchor="end")

    out = _resolve_output(output_path, crystal_id)
    _write_svg(root, out)
    return out


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------
def _lat(p: Dict[str, Any]) -> float:
    try:
        return float(p.get("lat", 0.0) or 0.0)
    except Exception:
        return 0.0


def _lon(p: Dict[str, Any]) -> float:
    try:
        return float(p.get("lon", 0.0) or 0.0)
    except Exception:
        return 0.0


def _edge_pair(e: Any) -> Tuple[Optional[str], Optional[str]]:
    """Extract (player_a, player_b) from any of the common edge shapes."""
    if isinstance(e, dict):
        a = e.get("player_a") or e.get("a") or e.get("source") or e.get("from")
        b = e.get("player_b") or e.get("b") or e.get("target") or e.get("to")
        return (str(a) if a else None, str(b) if b else None)
    if isinstance(e, (list, tuple)) and len(e) >= 2:
        return (str(e[0]), str(e[1]))
    return (None, None)


def _resolve_output(output_path: Optional[str], crystal_id: str) -> Path:
    if output_path:
        p = Path(os.path.expanduser(str(output_path)))
    else:
        cc_home = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
        p = cc_home / "planet_renders" / f"{_short_crystal(crystal_id)}.svg"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _write_svg(root: ET.Element, out: Path) -> None:
    """Write SVG with one element per line so line-based greps work + humans
    can scan the output. ET.indent is stdlib (added Python 3.9)."""
    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ", level=0)
    except Exception:
        # ET.indent only landed in 3.9; fall back to no-pretty if older
        pass
    tree.write(str(out), encoding="utf-8", xml_declaration=True)


def _crystal_anchor(player_id: str, source_action: str,
                    output_path: Optional[str]) -> str:
    """Log a crystal anchor entry — returns crystal_id (or '' on failure)."""
    if not _HAS_LOGGER or InferenceLogger is None:
        return ""
    try:
        logger = InferenceLogger()
        return logger.log(
            tier="visualization",
            model="friend_graph_visualizer",
            scope="svg_render",
            original_prompt=player_id,
            enhanced_prompt=player_id,
            output_text=str(output_path or ""),
            source_action=source_action,
        ) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> int:
    ap = argparse.ArgumentParser(
        prog="friend_graph_visualizer",
        description="Render the MySpace++ social graph as a static SVG.",
    )
    sub = ap.add_subparsers(dest="cmd")

    w = sub.add_parser("world", help="equirectangular world-map SVG")
    w.add_argument("player_id")
    w.add_argument("--out", default=None)
    w.add_argument("--max-hops", type=int, default=2)
    w.add_argument("--max-nodes", type=int, default=200)
    w.add_argument("--theme", default="dark", choices=list(THEMES.keys()))

    g = sub.add_parser("globe", help="orthographic globe SVG")
    g.add_argument("player_id")
    g.add_argument("--out", default=None)
    g.add_argument("--orbit-lon", type=float, default=0.0)
    g.add_argument("--orbit-lat", type=float, default=15.0)
    g.add_argument("--max-hops", type=int, default=2)
    g.add_argument("--max-nodes", type=int, default=200)
    g.add_argument("--theme", default="dark", choices=list(THEMES.keys()))

    p = sub.add_parser("progression", help="N small globes side-by-side")
    p.add_argument("player_id")
    p.add_argument("--out", default=None)
    p.add_argument("--weeks", type=int, default=4,
                   help="How many snapshots — used only when --snapshots-json is absent")
    p.add_argument("--snapshots-json", default=None,
                   help="Path to a JSON file containing a list of snapshot dicts")
    p.add_argument("--theme", default="dark", choices=list(THEMES.keys()))

    args = ap.parse_args()

    if args.cmd == "world":
        out = render_world_map(args.player_id, args.out,
                               max_hops=args.max_hops,
                               max_nodes=args.max_nodes,
                               theme=args.theme)
        print(str(out))
        return 0
    if args.cmd == "globe":
        out = render_globe_view(args.player_id, args.out,
                                orbit_lon=args.orbit_lon,
                                orbit_lat=args.orbit_lat,
                                max_hops=args.max_hops,
                                max_nodes=args.max_nodes,
                                theme=args.theme)
        print(str(out))
        return 0
    if args.cmd == "progression":
        snapshots: Optional[List[Dict[str, Any]]] = None
        if args.snapshots_json:
            try:
                snapshots = json.loads(Path(args.snapshots_json).read_text())
                if not isinstance(snapshots, list):
                    snapshots = None
            except Exception as e:
                print(f"failed to load snapshots json: {e}", file=sys.stderr)
                snapshots = None
        if snapshots is None:
            # Synth weekly snapshots by orbiting the same live graph through
            # different longitudes — gives N visually distinct globes even
            # without historical data.
            live = _fetch_graph(args.player_id, 2, 200)
            n = max(1, int(args.weeks))
            snapshots = []
            for i in range(n):
                snapshots.append({
                    "label": time.strftime(
                        "%Y-W%V", time.gmtime(time.time() - (n - 1 - i) * 7 * 86400)
                    ),
                    "players": live.get("players", []),
                    "friendships": live.get("friendships", []),
                    "orbit_lon": -180.0 + (360.0 * i / max(n - 1, 1)) if n > 1 else 0.0,
                    "orbit_lat": 15.0,
                })
        out = render_progression(args.player_id, args.out,
                                 snapshots=snapshots, theme=args.theme)
        print(str(out))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
