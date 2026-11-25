"""inventory.py — discover every DAG + node + system in the studio.

Returns a unified inventory used to build the master SVG. Pulls from
the canonical sources (no hand-maintained list):

  • Opcode DAG       — planning/hf_task_evolution.jsonl   (53 HF opcodes)
  • Model DAG        — studio/nodes.py NODES_BY_ID         (47 nodes)
  • Recipe DAG       — studio/recipes.py RECIPES + SINGLE_HOPS
  • Flows DAG        — studio/flows.py FLOWS
  • Passes DAG       — studio/passes/registry.py REGISTRY  (20 passes)
  • Workflow tpls    — cc.db workflow_templates table
  • Subsystem cat    — tesseract/projects.py SUBSYSTEMS

Every node carries:
    id           — unique within (kind, source_dag)
    label        — human display
    kind         — opcode | model | recipe | flow | pass | template | subsystem
    source_dag   — which DAG it lives in
    inputs       — list of typed input slots (where known)
    outputs      — list of typed output slots
    edges        — list of (neighbor_kind, neighbor_id, role) tuples
    files        — repo-relative file references (for jumping to source)
    status       — impl|partial|stub|placeholder
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent
PROJECT_ROOT = STUDIO_ROOT.parent
sys.path.insert(0, str(STUDIO_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "planning"))


@dataclass
class Node:
    id: str
    label: str
    kind: str
    source_dag: str
    inputs:   list[str] = field(default_factory=list)
    outputs:  list[str] = field(default_factory=list)
    edges:    list[dict] = field(default_factory=list)
    files:    list[str] = field(default_factory=list)
    status:   str = "impl"
    extra:    dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Source: opcode DAG (hf_task_evolution.jsonl) ───────────────────────────
def _opcodes() -> list[Node]:
    p = PROJECT_ROOT / "planning" / "hf_task_evolution.jsonl"
    if not p.exists():
        return []
    out: list[Node] = []
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"): continue
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        # The opcode JSONL uses 'task', 'inputs', 'outputs', 'depends_on', 'enables'.
        n = Node(
            id=row.get("task", "?"),
            label=row.get("task", "?"),
            kind="opcode",
            source_dag="opcode",
            inputs=list(row.get("inputs", []) or []),
            outputs=list(row.get("outputs", []) or []),
            files=["planning/hf_task_evolution.jsonl"],
            extra={"era": row.get("era"), "year": row.get("year"),
                   "category": row.get("category"),
                   "layer": row.get("layer"),
                   "role_in_avatar": row.get("role_in_avatar")},
        )
        for dep in row.get("depends_on", []) or []:
            n.edges.append({"role": "depends_on",
                            "neighbor_id": dep, "neighbor_kind": "opcode"})
        for en in row.get("enables", []) or []:
            n.edges.append({"role": "enables",
                            "neighbor_id": en, "neighbor_kind": "opcode"})
        out.append(n)
    return out


# ── Source: model DAG (studio/nodes.py NODES_BY_ID) ────────────────────────
def _models() -> list[Node]:
    try:
        from nodes import NODES_BY_ID
    except ImportError:
        return []
    out: list[Node] = []
    for nid, spec in NODES_BY_ID.items():
        out.append(Node(
            id=nid,
            label=spec.get("name", nid),
            kind=spec.get("kind", "model"),
            source_dag="model",
            inputs=[p.get("name", "?") + ":" + p.get("type", "")
                    for p in spec.get("inputs", [])],
            outputs=[p.get("name", "?") + ":" + p.get("type", "")
                     for p in spec.get("outputs", [])],
            files=[f"studio/{spec.get('dir','?')}"],
            extra={"vram_gb": spec.get("vram_gb"),
                   "entry": spec.get("entry")},
        ))
    return out


# ── Source: recipes (C01-C25 + S01-S21) ────────────────────────────────────
def _recipes() -> list[Node]:
    try:
        from recipes import RECIPES, SINGLE_HOPS
    except ImportError:
        return []
    out: list[Node] = []
    for rid, r in {**RECIPES, **SINGLE_HOPS}.items():
        chain = r.get("chain", []) if isinstance(r, dict) else []
        edges = [{"role": "uses", "neighbor_id": nid, "neighbor_kind": "model"}
                 for nid in chain]
        out.append(Node(
            id=rid,
            label=r.get("name", rid) if isinstance(r, dict) else rid,
            kind="recipe",
            source_dag="recipe",
            edges=edges,
            files=["studio/recipes.py"],
            extra={"chain": chain, "note": r.get("note") if isinstance(r, dict) else None},
        ))
    return out


# ── Source: flows (tuple of Flow dataclasses) ──────────────────────────────
def _flows() -> list[Node]:
    try:
        from flows import FLOWS
    except ImportError:
        return []
    out: list[Node] = []
    for f in FLOWS:
        edges: list[dict] = []
        for s in getattr(f, "steps", ()) or ():
            anchor = getattr(s, "anchor", None)
            lead   = getattr(s, "lead", None)
            if anchor:
                edges.append({"role": "anchor",
                              "neighbor_id": anchor, "neighbor_kind": "model"})
            if lead:
                edges.append({"role": "lead",
                              "neighbor_id": lead, "neighbor_kind": "model"})
            for d in getattr(s, "deck", ()) or ():
                edges.append({"role": "deck",
                              "neighbor_id": d, "neighbor_kind": "model"})
        out.append(Node(
            id=f.id, label=f.goal or f.name, kind="flow",
            source_dag="flow", edges=edges,
            files=["studio/flows.py"],
        ))
    return out


# ── Source: passes registry ────────────────────────────────────────────────
def _passes() -> list[Node]:
    try:
        from passes import registry as reg
    except ImportError:
        return []
    out: list[Node] = []
    for p in reg.REGISTRY:
        out.append(Node(
            id=p.id, label=p.label, kind="pass", source_dag="pass",
            inputs=p.input_kinds, outputs=[p.output_kind],
            files=["studio/passes/inference.py",
                   "studio/passes/registry.py"],
            extra={"cost_class": p.cost_class,
                   "import_time": p.import_time,
                   "needs": p.needs,
                   "extensions": p.file_extensions},
        ))
    return out


# ── Source: workflow templates from cc.db ──────────────────────────────────
def _templates() -> list[Node]:
    db_path = Path(os.environ.get("CC_GLOBAL_DB",
                                  str(Path.home() / ".cc" / "cc.db")))
    if not db_path.exists():
        return []
    out: list[Node] = []
    try:
        with sqlite3.connect(db_path) as c:
            rows = c.execute(
                "SELECT name, template_json FROM workflow_templates LIMIT 200"
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    for name, blob in rows:
        try:
            tpl = json.loads(blob)
        except Exception:
            continue
        steps = tpl.get("steps", [])
        edges = [{"role": "step", "neighbor_id": s.get("opcode"),
                  "neighbor_kind": "opcode"}
                 for s in steps if isinstance(s, dict) and s.get("opcode")]
        out.append(Node(
            id=name, label=tpl.get("description", name)[:64], kind="template",
            source_dag="template",
            inputs=[tpl.get("primary_opcode", "")],
            edges=edges,
            files=[],
            extra={"primary_opcode": tpl.get("primary_opcode"),
                   "tags": tpl.get("tags", [])},
        ))
    return out



# ── Source: subsystem catalog (projects.py SUBSYSTEMS) ─────────────────────
def _subsystems() -> list[Node]:
    try:
        from tesseract.projects import SUBSYSTEMS
    except ImportError:
        from .projects import SUBSYSTEMS
    out: list[Node] = []
    for sid, s in SUBSYSTEMS.items():
        edges = [{"role": "helps", "neighbor_id": h, "neighbor_kind": "subsystem"}
                 for h in s.get("helps", [])]
        out.append(Node(
            id=sid, label=s["name"], kind="subsystem",
            source_dag="subsystem",
            edges=edges,
            files=s.get("files", []),
            status=s.get("status", "impl"),
        ))
    return out



# ── Source: project types ──────────────────────────────────────────────────
def _project_types() -> list[Node]:
    try:
        from tesseract.projects import PROJECT_TYPES
    except ImportError:
        from .projects import PROJECT_TYPES
    out: list[Node] = []
    for pid, pt in PROJECT_TYPES.items():
        edges  = [{"role": "requires", "neighbor_id": s, "neighbor_kind": "subsystem"}
                  for s in pt.required]
        edges += [{"role": "optional", "neighbor_id": s, "neighbor_kind": "subsystem"}
                  for s in pt.optional]
        edges += [{"role": "default_pass", "neighbor_id": p, "neighbor_kind": "pass"}
                  for p in pt.default_passes]
        out.append(Node(
            id=pid, label=pt.label, kind="project_type",
            source_dag="project_type",
            edges=edges,
            files=["studio/tesseract/projects.py"],
        ))
    return out


# ── Source: Godot scene node trees (DAG-of-DAGs) ───────────────────────────
def _godot_scenes() -> list[Node]:
    """Parse studio/godot/project/scenes/*.tscn into a DAG-of-DAGs: each .tscn is
    a sub-DAG (its node tree, parent→child edges); a per-scene `godot_scene` node
    is the sub-DAG handle. Registered as a tesseract source → synced by
    construction, walker-ingestible like any other DAG (no hand-maintained drift)."""
    import re
    scenes_dir = STUDIO_ROOT / "godot" / "project" / "scenes"
    if not scenes_dir.exists():
        return []
    name_re = re.compile(r'name="([^"]+)"')
    type_re = re.compile(r'type="([^"]+)"')
    parent_re = re.compile(r'parent="([^"]+)"')
    out: list[Node] = []
    for tscn in sorted(scenes_dir.glob("*.tscn")):
        scene = tscn.stem
        rel = f"studio/godot/project/scenes/{tscn.name}"
        scene_id = f"godot:{scene}"
        scene_node = Node(id=scene_id, label=scene, kind="godot_scene",
                          source_dag="godot_scene", files=[rel], extra={"engine": "godot"})
        n_nodes = 0
        for ln in tscn.read_text(errors="ignore").splitlines():
            s = ln.strip()
            if not s.startswith("[node "):
                continue
            nm = name_re.search(s)
            if not nm:
                continue
            name = nm.group(1)
            tm = type_re.search(s)
            ntype = tm.group(1) if tm else "Instance"
            pm = parent_re.search(s)
            n_nodes += 1
            if not pm:                                   # scene root (no parent=)
                full, edges = ".", [{"role": "root_of", "neighbor_id": scene_id,
                                     "neighbor_kind": "godot_scene"}]
                scene_node.edges.append({"role": "root", "neighbor_id": f"{scene_id}#.",
                                         "neighbor_kind": "godot_node"})
            else:
                parent = pm.group(1)
                full = name if parent == "." else f"{parent}/{name}"
                edges = [{"role": "child_of", "neighbor_id": f"{scene_id}#{parent}",
                          "neighbor_kind": "godot_node"}]
            out.append(Node(id=f"{scene_id}#{full}", label=name, kind=f"godot:{ntype}",
                            source_dag="godot_scene", files=[rel], edges=edges,
                            extra={"godot_type": ntype, "scene": scene, "path": full}))
        scene_node.extra["node_count"] = n_nodes
        out.append(scene_node)
    return out


# ── Source: Godot scripts (relations = DAG; generated from workflow_cards) ──
def _godot_scripts() -> list[Node]:
    """Parse godot/project/src/*.{gd,cs}. Relations ARE the DAG: extends, signals,
    and the crystal-addressed workflow_card each script is GENERATED from
    (`# card_crystal:` / target). Language (godot_gd|godot_cs) is just the target."""
    import re
    src_dir = STUDIO_ROOT / "godot" / "project" / "src"
    if not src_dir.exists():
        return []
    rx = {k: re.compile(p) for k, p in {
        "extends": r"^extends\s+(\w+)", "class_name": r"^class_name\s+(\w+)",
        "signal": r"^signal\s+(\w+)", "card": r"card_crystal:\s*([0-9a-f]{8,})",
        "wcard": r"workflow_card:\s*(\S+)", "target": r"target:\s*(\S+)"}.items()}
    out: list[Node] = []
    for f in sorted(list(src_dir.glob("*.gd")) + list(src_dir.glob("*.cs"))):
        txt = f.read_text(errors="ignore")
        lang = "godot_cs" if f.suffix == ".cs" else "godot_gd"
        ext = cls = card = wcard = target = None
        signals: list[str] = []
        for ln in txt.splitlines():
            s = ln.strip()
            if (m := rx["extends"].match(s)): ext = m.group(1)
            elif (m := rx["class_name"].match(s)): cls = m.group(1)
            elif (m := rx["signal"].match(s)): signals.append(m.group(1))
            if (m := rx["card"].search(s)): card = m.group(1)[:16]
            if (m := rx["wcard"].search(s)): wcard = m.group(1)
            if (m := rx["target"].search(s)): target = m.group(1)
        sid = f"gd:{f.stem}"
        edges = []
        if ext:
            edges.append({"role": "extends", "neighbor_id": f"godot_type:{ext}", "neighbor_kind": "godot_type"})
        if wcard:
            edges.append({"role": "generated_from", "neighbor_id": f"card:{wcard}", "neighbor_kind": "workflow_card"})
        for sig in signals:
            edges.append({"role": "emits", "neighbor_id": f"signal:{f.stem}.{sig}", "neighbor_kind": "signal"})
        out.append(Node(id=sid, label=f.stem, kind="godot_script", source_dag="godot_script",
                        files=[f"studio/godot/project/src/{f.name}"], edges=edges,
                        extra={"lang": target or lang, "extends": ext, "class_name": cls,
                               "signals": signals, "card_crystal": card,
                               "generated": bool(wcard), "workflow_card": wcard}))
    return out


# ── Source: material library (crystal-addressed manifests = DAG) ────────────
def _material_library() -> list[Node]:
    """The material library IS a DAG: each crystal-addressed material manifest
    (~/.cc/chain_renders/<crystal>/manifest.json kind=material) → its PBR maps."""
    root = Path.home() / ".cc" / "chain_renders"
    if not root.exists():
        return []
    out: list[Node] = []
    for d in sorted(root.iterdir()):
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        try:
            m = json.loads(mf.read_text())
        except Exception:
            continue
        if m.get("kind") != "material":
            continue
        crystal = m.get("crystal_short", d.name)
        mid = f"mat:{crystal}"
        edges = [{"role": "map", "neighbor_id": f"tex:{crystal}/{k}",
                  "neighbor_kind": "texture", "slot": k}
                 for k in (m.get("maps") or {})]
        out.append(Node(id=mid, label=m.get("name", crystal), kind="material",
                        source_dag="material_library",
                        files=[f"~/.cc/chain_renders/{crystal}/manifest.json"], edges=edges,
                        status="impl" if not m.get("pending") else "partial",
                        extra={"crystal_short": crystal, "maps": list((m.get("maps") or {})),
                               "pending": list((m.get("pending") or {})),
                               "standards_version": m.get("standards_version")}))
    return out


# ── Public entry ───────────────────────────────────────────────────────────
def build_inventory() -> dict:
    """Return {meta, dags: {name: [Node...]}, totals}."""
    dags = {
        "opcode":       _opcodes(),
        "model":        _models(),
        "recipe":       _recipes(),
        "flow":         _flows(),
        "pass":         _passes(),
        "template":     _templates(),
        "subsystem":    _subsystems(),
        "project_type": _project_types(),
        "godot_scene":  _godot_scenes(),
        "godot_script": _godot_scripts(),
        "material_library": _material_library(),
    }
    totals = {k: len(v) for k, v in dags.items()}
    totals["nodes_total"] = sum(totals.values())
    totals["edges_total"] = sum(len(n.edges) for v in dags.values() for n in v)
    return {
        "meta": {
            "studio_root": str(STUDIO_ROOT),
            "project_root": str(PROJECT_ROOT),
        },
        "dags": {k: [n.to_dict() for n in v] for k, v in dags.items()},
        "totals": totals,
    }


if __name__ == "__main__":
    import json as _json
    inv = build_inventory()
    print(f"DAG totals: {inv['totals']}")
    print()
    for dag_name, nodes in inv["dags"].items():
        print(f"  {dag_name}: {len(nodes)} nodes")
        if nodes:
            print(f"    first: {nodes[0]['id']}  →  {nodes[0]['label'][:60]}")
