"""standard_import.py — Tesseract inventory → Lucid Standard Import JSON.

Reads tesseract.inventory.build_inventory() and emits a Lucid Standard
Import document with:

  - One PAGE per source DAG (8 pages: opcode, model, recipe, flow,
    pass, template, subsystem, project_type)
  - One SHAPE per node, positioned in a grid, fill colored by source
    DAG (or by status for subsystem nodes)
  - One LINE per directed edge between nodes (cross-page allowed —
    Lucid resolves cross-page references)
  - Custom data fields on every shape carrying the canonical id, kind,
    source_dag, edges count, walk-state, and any inputs/outputs

The output is offline-only: no Lucid account needed to generate, only
to import. Drop it into Lucid via:

    File → Import → Standard Import → choose Tesseract.lucid-si.json

The exact shape of the Standard Import JSON is best-effort based on
Lucid's documented "-si" pages — the schema continues to evolve, so
the converter is conservative: minimum-required fields, no exotic
features. If Lucid rejects the import, run with --verbose to see the
diff and adjust the SCHEMA_VERSION + property names below.

Refs:
    https://lucid.readme.io/docs/overview-si.md      Standard Import overview
    https://lucid.readme.io/docs/data-si.md          Data fields
    https://lucid.readme.io/docs/shapes-si.md        Shape entities
    https://lucid.readme.io/docs/lines-si.md         Line entities
    https://lucid.readme.io/docs/pages-si.md         Page entities
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
sys.path.insert(0, str(STUDIO_ROOT))

import paths   # noqa: E402

# ── Conservative defaults for the Standard Import schema ────────────────────
SCHEMA_VERSION = 1

PAGE_W = 1920
PAGE_H = 1200
CELL_W = 140
CELL_H = 90
GUTTER_X = 30
GUTTER_Y = 30
MARGIN = 80

DAG_FILL = {
    "opcode":       "#7dd3fc",
    "model":        "#a78bfa",
    "recipe":       "#34d399",
    "flow":         "#f472b6",
    "pass":         "#fbbf24",
    "template":     "#fb7185",
    "subsystem":    "#60a5fa",
    "project_type": "#e879f9",
}

STATUS_FILL = {
    "impl":        "#22c55e",
    "partial":     "#facc15",
    "stub":        "#fb923c",
    "placeholder": "#94a3b8",
}

PAGE_TITLES = {
    "opcode":       "Opcode DAG (HF task taxonomy)",
    "model":        "Model DAG (concrete models)",
    "recipe":       "Recipe DAG (multi-hop chains)",
    "flow":         "Flow DAG (named user flows)",
    "pass":         "Pass DAG (filetype → import-time passes)",
    "template":     "Template DAG (Claude-authored workflows)",
    "subsystem":    "Subsystems",
    "project_type": "Project types (switchboard)",
}


def _grid_position(idx: int, page_w: int = PAGE_W) -> tuple[int, int]:
    """Lay nodes out left-to-right, wrap on page width."""
    usable_w = page_w - 2 * MARGIN
    cols = max(1, usable_w // (CELL_W + GUTTER_X))
    col, row = idx % cols, idx // cols
    x = MARGIN + col * (CELL_W + GUTTER_X)
    y = MARGIN + row * (CELL_H + GUTTER_Y)
    return x, y


def _shape_id(dag: str, node_id: str) -> str:
    """Lucid wants stable, slug-safe shape IDs. Build a deterministic
    identifier from (dag, node-id)."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in node_id)
    return f"mspc.{dag}.{safe}"


def _node_fill(dag: str, node: dict) -> str:
    """Subsystem nodes color by status; everything else by source DAG."""
    if dag == "subsystem":
        return STATUS_FILL.get(node.get("status", "impl"), STATUS_FILL["impl"])
    return DAG_FILL.get(dag, "#cbd5e1")


def _shape_for(node: dict, dag: str, idx: int) -> dict:
    x, y = _grid_position(idx)
    sid = _shape_id(dag, node["id"])
    fill = _node_fill(dag, node)
    return {
        "id": sid,
        "type": "shape",
        "shapeType": "ProcessBlock" if dag != "subsystem" else "Tile",
        "boundingBox": {"x": x, "y": y, "w": CELL_W, "h": CELL_H},
        "style": {
            "fill":   {"type": "color", "color": fill},
            "stroke": {"color": "#0f172a", "width": 1.5, "style": "solid"},
            "rounding": 8,
        },
        "text": (node.get("label") or node["id"])[:60],
        # Lucid stores arbitrary key/value on shapes — used by formulas + the
        # data connector to bind upstream records.
        "customData": {
            "mspc:node-id":     node["id"],
            "mspc:kind":        node.get("kind", "?"),
            "mspc:source-dag":  dag,
            "mspc:status":      node.get("status", "impl"),
            "mspc:walk-state":  "pending",
            "mspc:edge-count":  len(node.get("edges", [])),
            "mspc:inputs":      ",".join(node.get("inputs", []))[:240],
            "mspc:outputs":     ",".join(node.get("outputs", []))[:240],
            "mspc:files":       ",".join(node.get("files", []))[:240],
        },
    }


def _line_for(src_dag: str, src_node_id: str,
              dst_dag: str, dst_node_id: str,
              role: str = "edge") -> dict:
    return {
        "id": f"edge.{src_dag}.{src_node_id}.{dst_dag}.{dst_node_id}.{role}",
        "type": "line",
        "endpoint1": {"connection": _shape_id(src_dag, src_node_id)},
        "endpoint2": {"connection": _shape_id(dst_dag, dst_node_id)},
        "stroke": {"color": "#64748b", "width": 1, "style": "solid"},
        "lineType": "elbow",
        "label": role,
    }


def _guess_neighbor_dag(role: str, neighbor_kind: Optional[str]) -> Optional[str]:
    """Edges sometimes know the neighbor's DAG by kind (e.g. 'model' or
    'subsystem'). Return that, else None to signal cross-DAG."""
    if neighbor_kind in DAG_FILL:
        return neighbor_kind
    # role-based hints
    if role in ("uses", "anchor", "lead", "deck", "step"):
        return "model"
    if role == "requires" or role == "optional" or role == "helps":
        return "subsystem"
    if role == "default_pass":
        return "pass"
    if role == "depends_on" or role == "enables":
        return "opcode"
    return None


def build_standard_import(inventory: Optional[dict] = None) -> dict:
    """Top-level builder. Returns the Standard Import JSON object."""
    if inventory is None:
        try:
            from tesseract.inventory import build_inventory
        except ImportError:
            sys.path.insert(0, str(STUDIO_ROOT))
            from tesseract.inventory import build_inventory
        inventory = build_inventory()

    pages: list[dict] = []
    all_known_shape_ids: set[str] = set()

    for dag, nodes in inventory["dags"].items():
        shapes: list[dict] = []
        for idx, n in enumerate(nodes):
            shape = _shape_for(n, dag, idx)
            shapes.append(shape)
            all_known_shape_ids.add(shape["id"])

        pages.append({
            "id": f"page.{dag}",
            "title": PAGE_TITLES.get(dag, dag),
            "size": {"w": PAGE_W, "h": PAGE_H},
            "shapes": shapes,
            "lines": [],   # filled in pass 2 below
            "customData": {
                "mspc:dag":        dag,
                "mspc:node-count": len(nodes),
                "mspc:edge-count": sum(len(n.get("edges", [])) for n in nodes),
            },
        })

    # Pass 2 — emit lines now that every shape id is known.
    for page in pages:
        dag = page["customData"]["mspc:dag"]
        nodes = inventory["dags"][dag]
        lines: list[dict] = []
        for n in nodes:
            src_id = n["id"]
            for e in n.get("edges", []):
                role     = e.get("role", "edge")
                nb_id    = e.get("neighbor_id")
                nb_kind  = e.get("neighbor_kind")
                if not nb_id:
                    continue
                nb_dag = _guess_neighbor_dag(role, nb_kind) or dag
                # Verify the neighbor shape exists (else it's a dangling edge
                # — represent it as a labeled but un-connected line so the
                # import doesn't fail).
                target = _shape_id(nb_dag, nb_id)
                if target not in all_known_shape_ids:
                    continue
                lines.append(_line_for(dag, src_id, nb_dag, nb_id, role))
        page["lines"] = lines

    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "title": "MySpace++ — Tesseract (DAG of DAGs)",
        "description": (
            "Auto-generated from studio/tesseract/inventory.build_inventory(). "
            "Each page is one source DAG; shapes carry custom data fields "
            "(mspc:*) that the data connector binds to live state."
        ),
        "customData": {
            "mspc:generator": "studio/lucid/standard_import.py",
            "mspc:totals":    inventory["totals"],
        },
        "pages": pages,
    }
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(prog="standard_import.py")
    ap.add_argument(
        "--out", default=None,
        help="output path (default: studio/docs/Tesseract.lucid-si.json)",
    )
    ap.add_argument("--stdout", action="store_true",
                    help="print to stdout instead of writing a file")
    ap.add_argument("--pretty", action="store_true",
                    help="pretty-print JSON (default: compact)")
    args = ap.parse_args()

    doc = build_standard_import()
    text = json.dumps(doc, indent=2 if args.pretty else None,
                      ensure_ascii=False)

    if args.stdout:
        print(text)
        return 0

    out = Path(args.out) if args.out else paths.DOCS_ROOT / "Tesseract.lucid-si.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)

    totals = doc["customData"]["mspc:totals"]
    n_lines = sum(len(p["lines"]) for p in doc["pages"])
    n_shapes = sum(len(p["shapes"]) for p in doc["pages"])
    print(f"wrote {out}")
    print(f"  pages:  {len(doc['pages'])}")
    print(f"  shapes: {n_shapes}  (inventory total: {totals['nodes_total']})")
    print(f"  lines:  {n_lines}   (inventory edges: {totals['edges_total']})")
    print(f"  size:   {out.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
