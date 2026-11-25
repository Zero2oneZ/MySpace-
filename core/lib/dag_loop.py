#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        dag_loop
# role:        ENGINE · INFINITE_LOOP_FOUR_DAG_ORCHESTRATOR
# tier:        L0
# substrate:   the meta-product — the system that runs the system
# storage:     studio/assets/_loop_cycles/ (one JSONL per cycle, crystal-anchored)
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - cc loop cycle | cc loop start | cc loop status | cc loop inspect
#   - studio_runtime (when card pass.engine='dag_loop')
# outbound:
#   - ops_dag.build_ops_dag (universal node store)
#   - hf_hub.inference (for routing decisions)
#   - inference_logger.log (cycle records, tier='loop_cycle')
#   - all four sub-DAG sources (BUILD_THESE_INNOVATE.md, _products/, _doc_corpus/, hf_hub providers)
# substrate touch:
#   - reads:  studio/assets/_workflows/*.json, _products/*.json, _doc_corpus/,
#             agent_defs, BUILD_THESE_INNOVATE.md, hf_hub.INFERENCE_PROVIDERS
#   - writes: studio/assets/_loop_cycles/<crystal>.jsonl, crystal chain entries
# ----------------------------------------------------------------------------
# THE FOUR SUB-DAGS
# ----------------------------------------------------------------------------
# PLATFORM_DAG  — every external service that has users + messages + media
#                   nodes: MCPs from BUILD_THESE §3, third_party/* connectors
#                   color: blue
#
# DOCS_DAG      — structured knowledge the chain consumes/produces
#                   nodes: parsed docs, agent_defs, source modules, project docs
#                   color: green
#
# INFERENCE_DAG — routing tree across cloud + local + free providers
#                   nodes: hf_hub providers, task_queue pools, future cloud_providers specs
#                   color: orange
#
# APPS_DAG      — products that emerge as outputs of the loop
#                   nodes: studio/assets/_products/*.product.v0.json + workflow_cards
#                   color: purple
#
# THE LOOP: PLATFORM → DOCS → INFERENCE → APPS → back to PLATFORM
#           (closed cycle; each transition is a crystal-anchored edge)
# ============================================================================
"""dag_loop.py — the four-DAG infinite-loop engine.

Walks the existing substrate, partitions every node into one of four
sub-DAGs (platform / doc / inference / app), and crystal-anchors each
loop cycle. The cycle drives itself: platform events feed docs, docs
inform inference, inference produces apps, apps deploy back to platforms.

Build the spine once, ship the products forever.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Resolve project root regardless of cwd
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))


try:
    import blake3 as _blake3_mod
    def _hash(data: bytes) -> str:
        return _blake3_mod.blake3(data).hexdigest()
except ImportError:
    def _hash(data: bytes) -> str:
        return hashlib.blake2b(data).hexdigest()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ASSETS = _PROJECT_ROOT / "studio" / "assets"
AGENT_DEFS_DIR = ASSETS / "_agents" / "agent_defs"
WORKFLOWS_DIR = ASSETS / "_workflows"
PRODUCTS_DIR = ASSETS / "_products"
DOC_CORPUS_DIR = ASSETS / "_doc_corpus"
DOCS_DIR = _PROJECT_ROOT / "studio" / "docs"
THIRD_PARTY_DIR = _PROJECT_ROOT / "core" / "lib" / "third_party"
LIB_DIR = _PROJECT_ROOT / "core" / "lib"
BUILD_THESE_PATH = _PROJECT_ROOT / "BUILD_THESE_INNOVATE.md"
LOOP_CYCLES_DIR = ASSETS / "_loop_cycles"


# ---------------------------------------------------------------------------
# Node + Edge structures (compatible with ops_dag.OpNode shape, extended)
# ---------------------------------------------------------------------------

@dataclass
class LoopNode:
    id: str
    name: str
    kind: str               # platform | doc | inference | app | (existing: agent | pass | placeholder)
    sub_dag: str            # PLATFORMS | DOCS | INFERENCE | APPS | ORCHESTRATION
    status: str = "ACTIVE"
    role: str = ""
    module_path: str = ""
    cost_class: str = "unknown"
    source: str = ""
    description: str = ""


@dataclass
class LoopEdge:
    src: str
    dst: str
    kind: str               # ingests_from | references | routes_through | produces | feeds_back | calls | feeds_into
    source: str = ""


# ---------------------------------------------------------------------------
# Four sub-DAG loaders
# ---------------------------------------------------------------------------

_MCP_TABLE_RE = re.compile(
    r"\|\s*`([a-z][a-z0-9_-]+(?:-mcp))`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
)

def load_platforms_from_buildthese() -> Tuple[List[LoopNode], List[LoopEdge]]:
    """Scan BUILD_THESE_INNOVATE.md §3 tables; emit one LoopNode per MCP entry."""
    nodes: List[LoopNode] = []
    edges: List[LoopEdge] = []
    if not BUILD_THESE_PATH.exists():
        return nodes, edges
    text = BUILD_THESE_PATH.read_text(encoding="utf-8")
    for m in _MCP_TABLE_RE.finditer(text):
        name = m.group(1)
        state = m.group(2).strip()
        tools = m.group(3).strip()
        free = m.group(4).strip()
        op_id = f"op_{name.replace('-', '_')}"
        status = "ACTIVE" if "LIVE" in state else ("IN-FLIGHT" if "stub" in state.lower() or "exists" in state.lower() else "TEXT-PLACEHOLDER")
        nodes.append(LoopNode(
            id=op_id, name=name, kind="platform", sub_dag="PLATFORMS",
            status=status, role="MCP_SERVER",
            module_path=f"core/lib/third_party/{name.replace('-mcp', '').replace('-', '_')}.py",
            cost_class="cheap" if "free" in free.lower() else "medium",
            source="BUILD_THESE_INNOVATE.md",
            description=f"{tools[:200]} (free={free})",
        ))
    # third_party/*.py — connectors already on disk are PLATFORMS too
    if THIRD_PARTY_DIR.exists():
        for py in THIRD_PARTY_DIR.glob("*.py"):
            if py.name in ("__init__.py", "base.py", "manager.py", "cli.py"):
                continue
            stem = py.stem
            op_id = f"op_{stem}"
            # Only add if not already added from BUILD_THESE_INNOVATE.md
            if not any(n.id == op_id for n in nodes):
                nodes.append(LoopNode(
                    id=op_id, name=stem, kind="platform", sub_dag="PLATFORMS",
                    status="ACTIVE", role="THIRD_PARTY_CONNECTOR",
                    module_path=f"core/lib/third_party/{py.name}",
                    cost_class="cheap", source="third_party/",
                    description=f"Live connector at {py.name}",
                ))
    return nodes, edges


def load_docs() -> Tuple[List[LoopNode], List[LoopEdge]]:
    """Walk studio/docs/, studio/assets/_doc_corpus/, agent_defs, and core/lib modules."""
    nodes: List[LoopNode] = []
    edges: List[LoopEdge] = []
    # studio/docs/*.md — project documentation
    if DOCS_DIR.exists():
        for md in sorted(DOCS_DIR.glob("*.md")):
            op_id = f"op_doc_{md.stem.lower().replace('-', '_').replace('.', '_')}"
            nodes.append(LoopNode(
                id=op_id, name=md.stem, kind="doc", sub_dag="DOCS",
                status="ACTIVE", role="PROJECT_DOC",
                module_path=str(md.relative_to(_PROJECT_ROOT)),
                cost_class="deterministic", source="studio/docs/",
                description=f"Project doc: {md.name}",
            ))
    # BUILD_THESE_INNOVATE.md is itself a doc
    if BUILD_THESE_PATH.exists():
        nodes.append(LoopNode(
            id="op_doc_build_these_innovate", name="BUILD_THESE_INNOVATE",
            kind="doc", sub_dag="DOCS", status="ACTIVE", role="STRATEGY_DOC",
            module_path="BUILD_THESE_INNOVATE.md",
            cost_class="deterministic", source="project root",
            description="Strategic roadmap doc: 10 products + 22 MCPs + DAG patterns",
        ))
    # _doc_corpus/<adapter>/*.jsonl — parsed external docs (populated by doc_parser later)
    if DOC_CORPUS_DIR.exists():
        for jsonl in DOC_CORPUS_DIR.rglob("*.jsonl"):
            op_id = f"op_doc_corpus_{jsonl.stem}"
            nodes.append(LoopNode(
                id=op_id, name=jsonl.stem, kind="doc", sub_dag="DOCS",
                status="ACTIVE", role="PARSED_DOC",
                module_path=str(jsonl.relative_to(_PROJECT_ROOT)),
                cost_class="deterministic", source="doc_parser",
                description=f"Parsed doc corpus: {jsonl.parent.name}/{jsonl.name}",
            ))
    # core/lib/*.py — every module is documentation for its own surface
    if LIB_DIR.exists():
        skip = {"__init__.py", "__pycache__"}
        for py in sorted(LIB_DIR.glob("*.py")):
            if py.name in skip:
                continue
            op_id = f"op_module_{py.stem}"
            nodes.append(LoopNode(
                id=op_id, name=py.stem, kind="doc", sub_dag="DOCS",
                status="ACTIVE", role="SOURCE_MODULE",
                module_path=str(py.relative_to(_PROJECT_ROOT)),
                cost_class="deterministic", source="core/lib/",
                description=f"Substrate module — see file for docstring + agent card",
            ))
    return nodes, edges


def load_inference_providers() -> Tuple[List[LoopNode], List[LoopEdge]]:
    """The 19 HF Inference Providers + task_queue pools + ZeroGPU/DeepSeek/droplet futures."""
    nodes: List[LoopNode] = []
    edges: List[LoopEdge] = []
    # 19 HF providers
    try:
        from hf_hub import INFERENCE_PROVIDERS
    except ImportError:
        INFERENCE_PROVIDERS = ()
    for p in INFERENCE_PROVIDERS:
        op_id = f"op_provider_{p.replace('-', '_')}"
        # Free tiers get classed differently
        free_tier = p in ("groq", "cerebras", "hf-inference", "fal-ai", "novita")
        nodes.append(LoopNode(
            id=op_id, name=p, kind="inference", sub_dag="INFERENCE",
            status="ACTIVE", role="HF_INFERENCE_PROVIDER",
            module_path="core/lib/hf_hub.py",
            cost_class="cheap" if free_tier else "medium",
            source="hf_hub.INFERENCE_PROVIDERS",
            description=f"HF unified router provider: {p}",
        ))
    # task_queue pools
    for pool in ("gpu", "ollama", "cloud", "deterministic"):
        op_id = f"op_pool_{pool}"
        nodes.append(LoopNode(
            id=op_id, name=f"pool_{pool}", kind="inference", sub_dag="INFERENCE",
            status="ACTIVE", role="TASK_QUEUE_POOL",
            module_path="core/lib/task_queue.py",
            cost_class="deterministic" if pool == "deterministic" else
                       ("cheap" if pool in ("ollama", "gpu") else "medium"),
            source="task_queue", description=f"Async pool: {pool}",
        ))
    # Forward-reference future inference nodes (Phase 4 of lively-enchanting-parrot)
    future_inference = [
        ("zerogpu", "ZeroGPU on HF Spaces (free A100, ~25 GPU-hr/day)"),
        ("deepseek", "DeepSeek API (cheap; ~$0.27/M input)"),
        ("browser_pool", "Chromium WebGPU workers (free, browser tabs)"),
        ("droplet_remote", "DigitalOcean droplet via WireGuard (cheap, slow)"),
    ]
    for name, desc in future_inference:
        nodes.append(LoopNode(
            id=f"op_provider_{name}", name=name, kind="inference",
            sub_dag="INFERENCE", status="TEXT-PLACEHOLDER",
            role="FUTURE_INFERENCE_PROVIDER",
            cost_class="cheap", source="lively-enchanting-parrot plan",
            description=desc,
        ))
    return nodes, edges


def load_apps() -> Tuple[List[LoopNode], List[LoopEdge]]:
    """Products (studio/assets/_products/) + existing workflow_cards become APP nodes."""
    nodes: List[LoopNode] = []
    edges: List[LoopEdge] = []
    if PRODUCTS_DIR.exists():
        for pc in sorted(PRODUCTS_DIR.glob("vm_mspc_001.products.*.json")):
            try:
                data = json.loads(pc.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            name = data.get("name", pc.stem)
            op_id = f"op_product_{name}"
            nodes.append(LoopNode(
                id=op_id, name=name, kind="app", sub_dag="APPS",
                status=data.get("status", "DESIGN"),
                role="PRODUCT",
                module_path=str(pc.relative_to(_PROJECT_ROOT)),
                cost_class="medium",
                source="_products/",
                description=data.get("tagline", "")[:300],
            ))
            # Edges: app → platforms it ingests from
            for mcp in data.get("input_mcps", []):
                src_id = f"op_{mcp.replace('-', '_')}"
                edges.append(LoopEdge(src=src_id, dst=op_id, kind="ingests_from",
                                       source="product_card"))
            # Edges: app → substrate it uses
            for sub in data.get("substrate_uses", []):
                src_id = f"op_module_{sub}" if sub.startswith("op_module_") is False else sub
                edges.append(LoopEdge(src=src_id, dst=op_id, kind="references",
                                       source="product_card"))
    # Workflow cards also become APP nodes (each one is a sellable run)
    if WORKFLOWS_DIR.exists():
        for wc in sorted(WORKFLOWS_DIR.glob("vm_mspc_001.workflows.*.json")):
            try:
                data = json.loads(wc.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            name = data.get("name", wc.stem)
            op_id = f"op_app_workflow_{name}"
            nodes.append(LoopNode(
                id=op_id, name=name, kind="app", sub_dag="APPS",
                status=data.get("state", "active").upper(),
                role="WORKFLOW_CARD",
                module_path=str(wc.relative_to(_PROJECT_ROOT)),
                cost_class="medium",
                source="_workflows/",
                description=data.get("summary", "")[:300],
            ))
    return nodes, edges


# ---------------------------------------------------------------------------
# Unified loader — merges all four sub-DAGs into one graph
# ---------------------------------------------------------------------------

def load_recursive_workflows() -> Tuple[List[LoopNode], List[LoopEdge]]:
    """Persisted recursion records become 5th-sub-DAG nodes."""
    nodes: List[LoopNode] = []
    edges: List[LoopEdge] = []
    try:
        from recursive_workflows import load_recursive_workflows_as_nodes
    except ImportError:
        return nodes, edges
    for r in load_recursive_workflows_as_nodes():
        nodes.append(LoopNode(
            id=r["id"], name=r["name"], kind="recursive_workflow",
            sub_dag="RECURSIVE_WORKFLOWS", status=r["status"], role=r["role"],
            module_path=r["module_path"], cost_class="deterministic",
            source=r["source"], description=r["description"],
        ))
        # Edges back into the source nodes (the recursion references them)
        for involved in r.get("_extras", {}).get("involved_nodes", []):
            edges.append(LoopEdge(src=r["id"], dst=involved, kind="references",
                                    source="recursion"))
    return nodes, edges


def build_loop_dag() -> Tuple[Dict[str, LoopNode], List[LoopEdge]]:
    nodes: Dict[str, LoopNode] = {}
    edges: List[LoopEdge] = []
    for loader in (load_platforms_from_buildthese, load_docs,
                    load_inference_providers, load_apps,
                    load_recursive_workflows):
        ns, eds = loader()
        for n in ns:
            if n.id not in nodes:
                nodes[n.id] = n
        edges.extend(eds)

    # Add cross-DAG loop edges: PLATFORMS → DOCS → INFERENCE → APPS → PLATFORMS
    platforms = [nid for nid, n in nodes.items() if n.sub_dag == "PLATFORMS"]
    docs = [nid for nid, n in nodes.items() if n.sub_dag == "DOCS"]
    inference = [nid for nid, n in nodes.items() if n.sub_dag == "INFERENCE"]
    apps = [nid for nid, n in nodes.items() if n.sub_dag == "APPS"]

    # Representative inter-DAG edges (one per transition — keeps graph readable)
    if platforms and docs:
        edges.append(LoopEdge(src=platforms[0], dst=docs[0], kind="feeds_into",
                               source="dag_loop"))
    if docs and inference:
        edges.append(LoopEdge(src=docs[0], dst=inference[0], kind="feeds_into",
                               source="dag_loop"))
    if inference and apps:
        edges.append(LoopEdge(src=inference[0], dst=apps[0], kind="produces",
                               source="dag_loop"))
    if apps and platforms:
        edges.append(LoopEdge(src=apps[0], dst=platforms[0], kind="feeds_back",
                               source="dag_loop"))
    # The closure edge — explicitly mark the loop
    return nodes, edges


def partition_by_sub_dag(nodes: Dict[str, LoopNode]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {
        "PLATFORMS": [], "DOCS": [], "INFERENCE": [], "APPS": [],
        "RECURSIVE_WORKFLOWS": [], "ORCHESTRATION": [],
    }
    for nid, n in nodes.items():
        out.setdefault(n.sub_dag, []).append(nid)
    return out


# ---------------------------------------------------------------------------
# The cycle — one loop iteration
# ---------------------------------------------------------------------------

@dataclass
class CycleStep:
    transition: str             # "platforms→docs" | "docs→inference" | ...
    src_count: int
    dst_count: int
    events_seen: int = 0
    actions_taken: int = 0
    notes: str = ""


@dataclass
class LoopCycle:
    ts: str
    cycle_idx: int
    nodes_total: int
    edges_total: int
    by_sub_dag: Dict[str, int] = field(default_factory=dict)
    steps: List[CycleStep] = field(default_factory=list)
    crystal: str = ""
    prev_crystal: str = ""


def _last_cycle_crystal() -> str:
    """Look up the previous cycle's crystal for chaining."""
    if not LOOP_CYCLES_DIR.exists():
        return ""
    files = sorted(LOOP_CYCLES_DIR.glob("cycle_*.jsonl"))
    if not files:
        return ""
    last = files[-1]
    try:
        first_line = last.read_text(encoding="utf-8").splitlines()[0]
        return json.loads(first_line).get("crystal", "")
    except (OSError, json.JSONDecodeError, IndexError):
        return ""


def _compute_cycle_crystal(cycle: LoopCycle) -> str:
    canonical = json.dumps({
        "cycle_idx": cycle.cycle_idx,
        "nodes_total": cycle.nodes_total,
        "edges_total": cycle.edges_total,
        "by_sub_dag": cycle.by_sub_dag,
        "steps": [asdict(s) for s in cycle.steps],
        "prev_crystal": cycle.prev_crystal,
    }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return _hash(canonical.encode("utf-8"))


def cycle_once(dry_run: bool = False) -> LoopCycle:
    """Run one cycle of the four-DAG loop. Crystal-anchors. Persists to disk."""
    nodes, edges = build_loop_dag()
    part = partition_by_sub_dag(nodes)
    cycle = LoopCycle(
        ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        cycle_idx=_next_cycle_idx(),
        nodes_total=len(nodes),
        edges_total=len(edges),
        by_sub_dag={k: len(v) for k, v in part.items()},
        prev_crystal=_last_cycle_crystal(),
    )
    # Four transitions of the loop
    transitions = [
        ("platforms→docs",   "PLATFORMS", "DOCS"),
        ("docs→inference",   "DOCS",      "INFERENCE"),
        ("inference→apps",   "INFERENCE", "APPS"),
        ("apps→platforms",   "APPS",      "PLATFORMS"),
    ]
    for label, src_sub, dst_sub in transitions:
        src_count = len(part.get(src_sub, []))
        dst_count = len(part.get(dst_sub, []))
        # Count cross-DAG edges as actions for this transition
        actions = sum(
            1 for e in edges
            if e.src in part.get(src_sub, []) and e.dst in part.get(dst_sub, [])
        )
        cycle.steps.append(CycleStep(
            transition=label,
            src_count=src_count, dst_count=dst_count,
            events_seen=src_count,    # potential events from each src node
            actions_taken=actions,
            notes=f"{src_sub} → {dst_sub}: {actions} explicit cross-DAG edges",
        ))
    cycle.crystal = _compute_cycle_crystal(cycle)

    if not dry_run:
        LOOP_CYCLES_DIR.mkdir(parents=True, exist_ok=True)
        out_path = LOOP_CYCLES_DIR / f"cycle_{cycle.cycle_idx:06d}_{cycle.crystal[:12]}.jsonl"
        lines = [
            json.dumps({
                "type": "loop_cycle_header",
                "crystal": cycle.crystal,
                "prev_crystal": cycle.prev_crystal,
                "ts": cycle.ts,
                "cycle_idx": cycle.cycle_idx,
                "nodes_total": cycle.nodes_total,
                "edges_total": cycle.edges_total,
                "by_sub_dag": cycle.by_sub_dag,
            }, sort_keys=True, separators=(",", ":")),
        ]
        for s in cycle.steps:
            lines.append(json.dumps({"type": "loop_cycle_step", **asdict(s)},
                                     sort_keys=True, separators=(",", ":")))
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Try to log to crystal chain
        try:
            from inference_logger import InferenceLogger  # type: ignore
            il = InferenceLogger()
            il.log(
                original_prompt=f"loop_cycle_{cycle.cycle_idx}",
                enhanced_prompt=f"nodes={cycle.nodes_total} edges={cycle.edges_total}",
                output_text=json.dumps({"by_sub_dag": cycle.by_sub_dag,
                                         "transitions": [s.transition for s in cycle.steps]},
                                        separators=(",", ":")),
                tier="loop_cycle", model="dag_loop",
                tokens_in=0, tokens_out=0, latency_ms=0,
                chain_context="four_dag_infinite_loop",
                done_flag=True,
            )
        except Exception:
            pass

    return cycle


def _next_cycle_idx() -> int:
    if not LOOP_CYCLES_DIR.exists():
        return 0
    files = sorted(LOOP_CYCLES_DIR.glob("cycle_*.jsonl"))
    if not files:
        return 0
    last_name = files[-1].stem
    try:
        idx = int(last_name.split("_")[1])
        return idx + 1
    except (ValueError, IndexError):
        return len(files)


# ---------------------------------------------------------------------------
# Inspection / summary
# ---------------------------------------------------------------------------

def summary_dict() -> Dict[str, Any]:
    nodes, edges = build_loop_dag()
    part = partition_by_sub_dag(nodes)
    by_status: Dict[str, int] = {}
    for n in nodes.values():
        by_status[n.status] = by_status.get(n.status, 0) + 1
    by_edge_kind: Dict[str, int] = {}
    for e in edges:
        by_edge_kind[e.kind] = by_edge_kind.get(e.kind, 0) + 1
    return {
        "nodes_total": len(nodes),
        "edges_total": len(edges),
        "by_sub_dag": {k: len(v) for k, v in part.items()},
        "by_status": by_status,
        "by_edge_kind": by_edge_kind,
        "cycles_recorded": len(list(LOOP_CYCLES_DIR.glob("cycle_*.jsonl")))
                            if LOOP_CYCLES_DIR.exists() else 0,
        "last_cycle_crystal": _last_cycle_crystal(),
    }


def list_cycles(limit: int = 10) -> List[Dict[str, Any]]:
    if not LOOP_CYCLES_DIR.exists():
        return []
    out = []
    for path in sorted(LOOP_CYCLES_DIR.glob("cycle_*.jsonl"))[-limit:]:
        try:
            first = path.read_text(encoding="utf-8").splitlines()[0]
            out.append(json.loads(first))
        except (OSError, json.JSONDecodeError, IndexError):
            continue
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="dag_loop — four-DAG infinite-loop engine")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status",  help="show current 4-DAG counts and edge distribution")
    sub.add_parser("inspect", help="print every node organized by sub-DAG")
    p_cycle = sub.add_parser("cycle", help="run one loop cycle (crystal-anchored)")
    p_cycle.add_argument("--dry-run", action="store_true")
    p_list = sub.add_parser("cycles", help="list recent loop cycles")
    p_list.add_argument("--limit", type=int, default=10)
    sub.add_parser("partitions", help="list node IDs grouped by sub-DAG")
    args = ap.parse_args()

    if args.cmd == "status":
        print(json.dumps(summary_dict(), indent=2))

    elif args.cmd == "inspect":
        nodes, edges = build_loop_dag()
        part = partition_by_sub_dag(nodes)
        for sd in ("PLATFORMS", "DOCS", "INFERENCE", "APPS", "ORCHESTRATION"):
            print(f"\n=== {sd} ({len(part.get(sd, []))} nodes) ===")
            for nid in sorted(part.get(sd, [])):
                n = nodes[nid]
                print(f"  [{n.status:18s}] {n.name:40s} {n.role}")

    elif args.cmd == "cycle":
        c = cycle_once(dry_run=args.dry_run)
        print(json.dumps({
            "cycle_idx": c.cycle_idx,
            "crystal": c.crystal,
            "prev_crystal": c.prev_crystal,
            "nodes_total": c.nodes_total,
            "edges_total": c.edges_total,
            "by_sub_dag": c.by_sub_dag,
            "steps": [asdict(s) for s in c.steps],
            "dry_run": args.dry_run,
        }, indent=2))

    elif args.cmd == "cycles":
        for c in list_cycles(args.limit):
            print(json.dumps(c, separators=(",", ":")))

    elif args.cmd == "partitions":
        nodes, _ = build_loop_dag()
        part = partition_by_sub_dag(nodes)
        out = {sd: sorted(part.get(sd, [])) for sd in
                ("PLATFORMS", "DOCS", "INFERENCE", "APPS", "ORCHESTRATION")}
        print(json.dumps(out, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
