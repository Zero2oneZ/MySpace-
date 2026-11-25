"""walker.py — agent walker contract enforcer.

Reads / writes the master Tesseract SVG's <metadata> node manifest. An
agent calls next_node() to discover what's pending; calls identify()
to satisfy the three-requirement contract for one node; only after a
successful identify is the node marked processed in the manifest.

The visual <circle> elements get their data-walk-state attribute synced
to the manifest, so opening the SVG in a browser shows progress
visually.

Public API:
    next_node()                                  → dict | None
    identify(node_uid, neighbors, subjects,
             agent_id, by="agent")               → bool
    status()                                     → progress summary
    reset(node_uid=None)                         → wipe walk state
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
import paths   # noqa: E402

SVG_PATH = paths.DOCS_ROOT / "Tesseract.svg"

SVG_NS = "http://www.w3.org/2000/svg"
TES_NS = "https://myspace.local/tesseract"
ET.register_namespace("", SVG_NS)
ET.register_namespace("tes", TES_NS)


def _ensure_svg() -> Path:
    if not SVG_PATH.exists():
        try:
            from tesseract.svg import build_master
        except ImportError:
            from .svg import build_master
        build_master()
    return SVG_PATH


def _load() -> ET.ElementTree:
    return ET.parse(_ensure_svg())


def _save(tree: ET.ElementTree) -> None:
    tree.write(SVG_PATH, encoding="utf-8", xml_declaration=True)


def _manifest_nodes(tree: ET.ElementTree):
    """Return list of <tes:node> elements in document order."""
    root = tree.getroot()
    meta = root.find(f"{{{SVG_NS}}}metadata")
    if meta is None:
        return []
    out = []
    for dag in meta.iter(f"{{{TES_NS}}}dag"):
        for n in dag.iter(f"{{{TES_NS}}}node"):
            out.append(n)
    return out


def _visual_circle_for(root, node_uid: str):
    """node_uid format = '<dag>:<node-id>' — matches `id` on the visual <circle>."""
    target_id = f"node:{node_uid}"
    for el in root.iter(f"{{{SVG_NS}}}circle"):
        if el.get("id") == target_id:
            return el
    return None


def next_node() -> Optional[dict]:
    """Return the next pending node, with everything an agent needs to
    satisfy the contract for it."""
    tree = _load()
    for n in _manifest_nodes(tree):
        if n.get("walk-state") == "pending":
            return {
                "uid":       n.get("id"),
                "label":     n.get("label"),
                "kind":      n.get("kind"),
                "edges":     int(n.get("edges", "0")),
                "status":    n.get("status"),
                "contract": {
                    "must_identify_node":  True,
                    "must_list_neighbors": True,
                    "must_map_subjects":   True,
                    "required_subject_levels": ["dag", "subsystem", "project_types"],
                },
            }
    return None


def identify(node_uid: str, *, neighbors: list[str],
             subjects: dict, agent_id: str = "anonymous") -> dict:
    """Submit the three contract requirements for `node_uid`.

    Args:
        node_uid:   "<dag>:<node-id>" — copy from next_node()['uid']
        neighbors:  list of adjacent node UIDs (with dag prefix)
        subjects:   {dag, subsystem, project_types[]}
        agent_id:   your agent identifier
    """
    if not isinstance(neighbors, list):
        return {"ok": False, "error": "neighbors must be a list"}
    if not isinstance(subjects, dict):
        return {"ok": False, "error": "subjects must be a dict"}
    for required in ("dag", "subsystem", "project_types"):
        if required not in subjects:
            return {"ok": False, "error": f"subjects missing key: {required}"}

    tree = _load()
    root = tree.getroot()

    # Find the manifest entry
    n_el = None
    for n in _manifest_nodes(tree):
        if n.get("id") == node_uid:
            n_el = n; break
    if n_el is None:
        return {"ok": False, "error": f"unknown node: {node_uid}"}
    if n_el.get("walk-state") == "processed":
        return {"ok": False, "error": "already processed"}

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    n_el.set("walk-state",     "processed")
    n_el.set("walk-by",        agent_id)
    n_el.set("walk-at",        ts)
    n_el.set("walk-neighbors", json.dumps(neighbors))
    n_el.set("walk-subjects",  json.dumps(subjects, sort_keys=True))

    # Also flip the visual circle (so SVG viewers show progress).
    c = _visual_circle_for(root, node_uid)
    if c is not None:
        c.set("data-walk-state", "processed")
        c.set("data-walk-by",    agent_id)
        # Fade the dot to green so the eye picks it up.
        c.set("fill", "#22c55e")

    _save(tree)
    return {"ok": True, "node_uid": node_uid, "at": ts}


def status() -> dict:
    """Walk-progress summary."""
    tree = _load()
    nodes = _manifest_nodes(tree)
    total = len(nodes)
    by_dag: dict[str, dict] = {}
    by_state = {"pending": 0, "in-progress": 0, "processed": 0}
    for n in nodes:
        state = n.get("walk-state", "pending")
        by_state[state] = by_state.get(state, 0) + 1
        uid = n.get("id") or ""
        dag = uid.split(":")[0] if ":" in uid else "?"
        by_dag.setdefault(dag, {"total": 0, "processed": 0, "pending": 0})
        by_dag[dag]["total"] += 1
        if state == "processed":
            by_dag[dag]["processed"] += 1
        elif state == "pending":
            by_dag[dag]["pending"] += 1
    return {"total": total, "by_state": by_state, "by_dag": by_dag}


def reset(node_uid: Optional[str] = None) -> dict:
    """Reset one node (or every node) back to pending."""
    tree = _load()
    root = tree.getroot()
    n_wiped = 0
    for n in _manifest_nodes(tree):
        if node_uid and n.get("id") != node_uid:
            continue
        n.set("walk-state", "pending")
        for k in ("walk-by", "walk-at", "walk-neighbors", "walk-subjects"):
            if n.get(k) is not None:
                n.attrib.pop(k, None)
        c = _visual_circle_for(root, n.get("id") or "")
        if c is not None:
            c.set("data-walk-state", "pending")
            try:
                from tesseract.svg import DAG_COLOR
            except ImportError:
                from .svg import DAG_COLOR
            uid = n.get("id") or ""
            dag = uid.split(":")[0] if ":" in uid else "?"
            c.set("fill", DAG_COLOR.get(dag, "#94a3b8"))
        n_wiped += 1
        if node_uid:
            break
    _save(tree)
    return {"ok": True, "reset": n_wiped}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="walker.py")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("next")
    sp.add_parser("status")
    p_id = sp.add_parser("identify")
    p_id.add_argument("uid"); p_id.add_argument("--agent", default="cli")
    p_id.add_argument("--neighbors", default="[]")
    p_id.add_argument("--subjects",  default="{}")
    p_r = sp.add_parser("reset"); p_r.add_argument("--uid", default=None)
    args = ap.parse_args()

    if args.cmd == "next":
        print(json.dumps(next_node(), indent=2))
    elif args.cmd == "status":
        print(json.dumps(status(), indent=2))
    elif args.cmd == "identify":
        r = identify(args.uid,
                     neighbors=json.loads(args.neighbors),
                     subjects=json.loads(args.subjects),
                     agent_id=args.agent)
        print(json.dumps(r, indent=2))
    elif args.cmd == "reset":
        print(json.dumps(reset(args.uid), indent=2))
