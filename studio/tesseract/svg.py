"""svg.py — emit the master Tesseract SVG.

Layout (z-ordered groups inside one <svg>):

    layer 0  instructions      visible HTML-in-foreignObject explaining the
                               agent walker contract; also embedded in
                               <metadata> as ascii so non-rendered parsers
                               can read it
    layer 1  systems           10 subsystem tiles with status color codes
                               + which files implement each
    layer 2  dag_of_dags       8 cluster blobs (opcode/model/recipe/flow/
                               pass/template/subsystem/project_type) with
                               meta-edges between them
    layer 3  nodes             every discovered node as a circle + label,
                               carrying data-walk-state (pending|in-progress|
                               processed) attributes the walker mutates
    layer 4  project_types     project-type switchboard — each project
                               type names the subsystems it activates
    layer 5  plan              current plan steps from tesseract.plan

The <metadata> block holds the machine-readable manifest: every node's
id, kind, source_dag, edges, and walk state. The walker reads/writes
THIS rather than the visual elements.
"""
from __future__ import annotations

import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
sys.path.insert(0, str(STUDIO_ROOT))
import paths  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
TES_NS = "https://myspace.local/tesseract"
HTML_NS = "http://www.w3.org/1999/xhtml"
ET.register_namespace("", SVG_NS)
ET.register_namespace("tes", TES_NS)


# ── Canvas constants ────────────────────────────────────────────────────────
W = 2400
H = 1800
LAYER_PAD = 18

# Status → fill color
STATUS_COLOR = {
    "impl":         "#22c55e",
    "partial":      "#facc15",
    "stub":         "#fb923c",
    "placeholder":  "#94a3b8",
}

DAG_COLOR = {
    "opcode":       "#7dd3fc",   # cyan
    "model":        "#a78bfa",   # violet
    "recipe":       "#34d399",   # emerald
    "flow":         "#f472b6",   # pink
    "pass":         "#fbbf24",   # amber
    "template":     "#fb7185",   # rose
    "subsystem":    "#60a5fa",   # blue
    "project_type": "#e879f9",   # fuchsia
}


# ── Embedded instructions (the contract — what an agent MUST do) ────────────
INSTRUCTIONS = """\
== TESSERACT RENDERER · AGENT CONTRACT ==

You are an agent walking this DAG-of-DAGs. The master SVG is BOTH the
document and the executable plan.

To advance through one node you MUST satisfy these THREE requirements:

  1. IDENTIFY THE NODE
     Set the node's data-walk-id to the canonical node id and
     data-walk-by to your agent identifier. Confirms you read it.

  2. IDENTIFY EVERY ADJACENT NODE
     List the IDs of every node connected to this one (edges in either
     direction) into data-walk-neighbors as JSON.

  3. MAP THE SUBJECT MATTER AT EACH LAYER
     Record into data-walk-subjects a JSON dict like:
       { "dag":          "<which DAG owns the node>",
         "subsystem":    "<which subsystem (if any) this serves>",
         "project_types": ["<which project types this is reachable from>"] }

Only when all three attributes are populated may the walker mark
data-walk-state="processed" and advance. Walk every node across all
DAGs to complete the operations pass.

Use cc -tesseract-walk to fetch the next pending node and the exact
requirements for it. Use cc -tesseract-identify <node-id> ... to submit
your three answers.

== STATUS COLORS ==
  green  = implemented      yellow = partial implementation
  orange = stub             gray   = placeholder (no code yet)

== LAYERS ==
  0 instructions   (this text)         visible
  1 systems        subsystem tiles     visible
  2 dag_of_dags    cluster overview    visible
  3 nodes          every node          visible (zoom for detail)
  4 project_types  switchboard         visible
  5 plan           steps tracker       visible

== HOW TO REGENERATE ==
  cc -tesseract-build
"""


def _layer(parent, layer_id: str, label: str) -> ET.Element:
    g = ET.SubElement(parent, f"{{{SVG_NS}}}g", attrib={
        "id":               f"layer:{layer_id}",
        "data-layer":       layer_id,
        "data-layer-label": label,
    })
    return g


def _text(parent, x, y, txt, *, size=14, color="#0f172a", weight="normal"):
    t = ET.SubElement(parent, f"{{{SVG_NS}}}text", attrib={
        "x": str(x), "y": str(y),
        "font-family": "system-ui, sans-serif",
        "font-size": str(size), "fill": color,
        "font-weight": weight,
    })
    t.text = txt
    return t


def _rect(parent, x, y, w, h, *, fill="#fff", stroke="#1e293b", rx=6, **kw):
    return ET.SubElement(parent, f"{{{SVG_NS}}}rect", attrib={
        "x": str(x), "y": str(y), "width": str(w), "height": str(h),
        "rx": str(rx), "fill": fill, "stroke": stroke,
        "stroke-width": "1.5", **{k.replace("_", "-"): str(v) for k, v in kw.items()},
    })


def _line(parent, x1, y1, x2, y2, *, stroke="#94a3b8", w=1):
    return ET.SubElement(parent, f"{{{SVG_NS}}}line", attrib={
        "x1": str(x1), "y1": str(y1), "x2": str(x2), "y2": str(y2),
        "stroke": stroke, "stroke-width": str(w),
    })


def _circle(parent, cx, cy, r, *, fill="#fff", stroke="#1e293b", **kw):
    return ET.SubElement(parent, f"{{{SVG_NS}}}circle", attrib={
        "cx": str(cx), "cy": str(cy), "r": str(r),
        "fill": fill, "stroke": stroke,
        "stroke-width": "1.5",
        **{k.replace("_", "-"): str(v) for k, v in kw.items()},
    })


def build_master(out_path: Optional[Path] = None,
                 inventory: Optional[dict] = None) -> Path:
    """Build the master Tesseract SVG. Writes to studio/docs/Tesseract.svg
    by default."""
    if inventory is None:
        try:
            from tesseract.inventory import build_inventory
        except ImportError:
            from .inventory import build_inventory
        inventory = build_inventory()

    if out_path is None:
        out_path = paths.DOCS_ROOT / "Tesseract.svg"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    svg = ET.Element(f"{{{SVG_NS}}}svg", attrib={
        "width": str(W), "height": str(H),
        "viewBox": f"0 0 {W} {H}", "version": "1.1",
        "data-version": "1",
        "data-built-at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })

    # ── Manifest in <metadata> + machine-readable contract ─────────────────
    meta = ET.SubElement(svg, f"{{{SVG_NS}}}metadata",
                         attrib={"id": "tesseract-manifest"})
    contract = ET.SubElement(meta, f"{{{TES_NS}}}contract")
    contract.text = INSTRUCTIONS
    dag_index = ET.SubElement(meta, f"{{{TES_NS}}}dags")
    for dname, nodes in inventory["dags"].items():
        d = ET.SubElement(dag_index, f"{{{TES_NS}}}dag",
                          attrib={"name": dname, "count": str(len(nodes))})
        for n in nodes:
            ET.SubElement(d, f"{{{TES_NS}}}node", attrib={
                "id":           f"{dname}:{n['id']}",
                "label":        (n.get("label") or n["id"])[:120],
                "kind":         n["kind"],
                "status":       n.get("status", "impl"),
                "edges":        str(len(n.get("edges", []))),
                "walk-state":   "pending",
            })

    # Background
    _rect(svg, 0, 0, W, H, fill="#f8fafc", stroke="#cbd5e1", rx=0)

    # ── Layer 0 — Instructions (visible) ────────────────────────────────────
    l0 = _layer(svg, "instructions", "Instructions · Agent Contract")
    _rect(l0, 20, 20, 760, 460, fill="#fefce8", stroke="#facc15", rx=8)
    _text(l0, 36, 50, "TESSERACT RENDERER", size=18, weight="bold")
    _text(l0, 36, 72, "Agent contract — read this before walking.", size=12, color="#475569")
    # Render instructions as visible svg text (manual line layout)
    y = 100
    for line in INSTRUCTIONS.splitlines():
        if y > 470:
            _text(l0, 36, y, "…(full text in <metadata>/<tes:contract>)", size=11, color="#475569")
            break
        if line.startswith("=="):
            _text(l0, 36, y, line, size=12, weight="bold", color="#7c2d12")
        else:
            _text(l0, 36, y, line, size=11, color="#0f172a")
        y += 14

    # ── Layer 1 — Subsystems ───────────────────────────────────────────────
    l1 = _layer(svg, "systems", "Subsystems")
    sub_nodes = inventory["dags"]["subsystem"]
    cols = 5
    sx0, sy0 = 800, 40
    cell_w, cell_h, cell_gap = 290, 80, 12
    _text(l1, sx0, sy0, "SUBSYSTEMS", size=16, weight="bold")
    for i, n in enumerate(sub_nodes):
        col, row = i % cols, i // cols
        x = sx0 + col * (cell_w + cell_gap)
        y = sy0 + 20 + row * (cell_h + cell_gap)
        color = STATUS_COLOR.get(n.get("status", "impl"), "#94a3b8")
        _rect(l1, x, y, cell_w, cell_h, fill=color, stroke="#1e293b", rx=10)
        _text(l1, x + 12, y + 24, n["label"], size=13, weight="bold")
        _text(l1, x + 12, y + 44, f"status: {n.get('status','impl')}", size=11, color="#1e293b")
        _text(l1, x + 12, y + 62, f"helps: {', '.join(e['neighbor_id'] for e in n.get('edges', []))[:50]}",
              size=10, color="#1e293b")

    # ── Layer 2 — DAG-of-DAGs cluster blobs ────────────────────────────────
    l2 = _layer(svg, "dag_of_dags", "DAG of DAGs")
    cx0, cy0 = 60, 540
    cell = 200
    pad = 24
    _text(l2, cx0, cy0 - 14, "DAG OF DAGS — 8 source DAGs", size=14, weight="bold")
    for i, (dname, nodes) in enumerate(inventory["dags"].items()):
        col, row = i % 4, i // 4
        x = cx0 + col * (cell + pad)
        y = cy0 + row * (cell - 20 + pad)
        fill = DAG_COLOR.get(dname, "#cbd5e1")
        _rect(l2, x, y, cell, cell - 30, fill=fill, stroke="#0f172a", rx=14)
        _text(l2, x + 12, y + 26, dname.upper(), size=14, weight="bold")
        _text(l2, x + 12, y + 50, f"{len(nodes)} nodes", size=12)
        _text(l2, x + 12, y + 72, f"edges: {sum(len(n.get('edges', [])) for n in nodes)}", size=11)

    # ── Layer 3 — Nodes (compact dots; metadata holds the truth) ───────────
    l3 = _layer(svg, "nodes", "Nodes (every DAG, every node)")
    nx0, ny0 = 60, 980
    panel_w, panel_h = W - 120, 480
    _rect(l3, nx0, ny0 - 20, panel_w, panel_h, fill="#ffffff", stroke="#cbd5e1", rx=10)
    _text(l3, nx0 + 12, ny0 + 4, "ALL NODES — colored by source DAG, click to inspect data-* attrs",
          size=12, weight="bold")
    # Flow-layout dots: one row per DAG, side by side.
    row_y = ny0 + 30
    dot_r = 5
    dot_gap = 12
    for dname, nodes in inventory["dags"].items():
        _text(l3, nx0 + 12, row_y + 4, f"{dname} ({len(nodes)})", size=11, weight="bold")
        x = nx0 + 140
        for n in nodes:
            walk_state = "pending"
            fill = DAG_COLOR.get(dname, "#94a3b8")
            stroke = "#1e293b"
            c = _circle(l3, x, row_y, dot_r, fill=fill, stroke=stroke)
            # Annotate with full data-* for the walker.
            c.set("id", f"node:{dname}:{n['id']}")
            c.set("data-node-id", n["id"])
            c.set("data-source-dag", dname)
            c.set("data-kind", n["kind"])
            c.set("data-walk-state", walk_state)
            x += dot_gap
            if x > nx0 + panel_w - 20:
                row_y += 16
                x = nx0 + 140
        row_y += 28
        if row_y > ny0 + panel_h - 30:
            _text(l3, nx0 + 12, row_y, "…(remaining DAGs in <metadata>)", size=11, color="#94a3b8")
            break

    # ── Layer 4 — Project type switchboard ─────────────────────────────────
    l4 = _layer(svg, "project_types", "Project types")
    px0, py0 = 60, 1490
    _text(l4, px0, py0, "PROJECT TYPES — switchboard", size=14, weight="bold")
    pcell_w, pcell_h, pgap = 260, 120, 12
    pcols = 4
    for i, n in enumerate(inventory["dags"]["project_type"]):
        col, row = i % pcols, i // pcols
        x = px0 + col * (pcell_w + pgap)
        y = py0 + 20 + row * (pcell_h + pgap)
        _rect(l4, x, y, pcell_w, pcell_h, fill="#ecfeff", stroke="#0891b2", rx=10)
        _text(l4, x + 10, y + 20, n["label"], size=12, weight="bold")
        req = [e["neighbor_id"] for e in n.get("edges", []) if e.get("role") == "requires"]
        opt = [e["neighbor_id"] for e in n.get("edges", []) if e.get("role") == "optional"]
        _text(l4, x + 10, y + 40, f"req:  {', '.join(req)[:34]}", size=10, color="#155e75")
        _text(l4, x + 10, y + 58, f"opt:  {', '.join(opt)[:34]}", size=10, color="#155e75")
        passes = [e["neighbor_id"] for e in n.get("edges", []) if e.get("role") == "default_pass"]
        _text(l4, x + 10, y + 76, f"default passes: {', '.join(passes)[:34]}", size=10, color="#0c4a6e")

    # ── Layer 5 — Plan steps (rendered from plan.py if available) ──────────
    l5 = _layer(svg, "plan", "Plan steps")
    _rect(l5, 1600, 540, 720, 410, fill="#ffffff", stroke="#cbd5e1", rx=10)
    _text(l5, 1620, 570, "PLAN STEPS", size=14, weight="bold")
    try:
        try:
            from tesseract import plan as plan_mod
        except ImportError:
            from . import plan as plan_mod
        steps = plan_mod.list_steps()
    except Exception:
        steps = []
    if not steps:
        _text(l5, 1620, 596, "(no steps yet — run cc -tesseract-plan-seed)",
              size=11, color="#64748b")
    else:
        y = 596
        for s in steps[:24]:
            color = {"planned": "#94a3b8", "in_progress": "#facc15",
                     "done": "#22c55e", "blocked": "#ef4444"}.get(s.get("status"), "#64748b")
            _circle(l5, 1632, y - 4, 5, fill=color, stroke="#1e293b")
            _text(l5, 1648, y, f"{s.get('title','?')[:64]}", size=11, color="#0f172a")
            y += 16

    # ── Counts / footer ────────────────────────────────────────────────────
    footer = _layer(svg, "footer", "Footer")
    _text(footer, 60, H - 30,
          f"Tesseract · {inventory['totals']['nodes_total']} nodes · "
          f"{inventory['totals']['edges_total']} edges · "
          f"{len(inventory['dags'])} DAGs · built {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
          size=10, color="#475569")

    # ── Write ──────────────────────────────────────────────────────────────
    ET.ElementTree(svg).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path


if __name__ == "__main__":
    out = build_master()
    print(f"wrote {out}  ({out.stat().st_size} bytes)")
