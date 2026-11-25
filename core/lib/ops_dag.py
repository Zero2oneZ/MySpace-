#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        ops_dag
# role:        SUBSTRATE · OPERATIONAL_DAG
# tier:        L0
# substrate:   ops_dag.jsonl (auto-built from agent_defs + workflows + placeholders)
# engine:      walk substrates → emit nodes + edges → topo-sort + parallel detect
# storage:     ~/.cc/ops_dag.jsonl (ParserCursor-compatible)
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.ops_dag.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/cc.sh::cmd_ops_dag (cc ops-dag build / topo / parallel / placeholders)
#   - workflow_generator (to verify a card's passes are realizable given current DAG state)
# outbound:
#   - reads studio/assets/_agents/agent_defs/*.json
#   - reads studio/assets/_workflows/*.json
#   - reads studio/assets/_operations/text_placeholders.json
#   - writes ~/.cc/ops_dag.jsonl
# substrate touch:
#   - reads:  the three sources above
#   - writes: ~/.cc/ops_dag.jsonl
# ============================================================================
"""ops_dag.py — the deterministic operational DAG.

Every system operation is a node:
  * agent_def    (17+ — each Python/bash module we've built)
  * workflow_pass (per pass in each workflow_card)
  * text_placeholder (hand-authored future ops)

Edges:
  * declared from agent_def routing_connections.inbound_callers / outbound_calls
  * declared from workflow_card pass.in / pass.out
  * declared from text_placeholder.expected_after / expected_before

Queries:
  * topo_sort  → optimal execution order
  * parallel_groups → ops with no inter-dependency
  * placeholders → text-only stubs awaiting implementation
  * ready → ops whose deps are all ACTIVE
  * path A B → shortest path from op A to op B
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any


REPO_ROOT = Path("/data/Projects/MySpace++")
AGENT_DEFS_DIR    = REPO_ROOT / "studio" / "assets" / "_agents" / "agent_defs"
WORKFLOWS_DIR     = REPO_ROOT / "studio" / "assets" / "_workflows"
PLACEHOLDERS_FILE = REPO_ROOT / "studio" / "assets" / "_operations" / "text_placeholders.json"
OUT_PATH          = Path.home() / ".cc" / "ops_dag.jsonl"


STATUS_RANKS = {"ACTIVE": 0, "IN-FLIGHT": 1, "STUB": 2, "TEXT-PLACEHOLDER": 3, "UNKNOWN": 4}


# ---------------------------------------------------------------------------
# Node + edge dataclasses
# ---------------------------------------------------------------------------
@dataclass
class OpNode:
    id: str
    name: str
    kind: str                  # agent | pass | placeholder
    status: str = "UNKNOWN"     # ACTIVE | IN-FLIGHT | STUB | TEXT-PLACEHOLDER
    role: str = ""
    module_path: str = ""
    tier: str = "L0"
    cost_class: str = "unknown"
    source: str = ""           # agent_def | workflow_card | manual
    description: str = ""


@dataclass
class OpEdge:
    src: str
    dst: str
    kind: str                  # calls | reads | writes | depends_on | feeds_into | placeholder_for
    source: str = ""           # provenance: which substrate declared this


# ---------------------------------------------------------------------------
# Builder — walk substrates → emit nodes + edges
# ---------------------------------------------------------------------------

# Regex to extract module/script references from routing_connections free-text strings
_REF_RE = re.compile(r"(core/(?:lib|scripts)/[A-Za-z0-9_/.\-]+\.(?:py|sh)|core/cc\.sh|studio/[A-Za-z0-9_/.\-]+\.(?:py|sh|js|gd|tscn|cpp|json))")
_NAMED_RE = re.compile(r"\b([a-z_][a-z0-9_]+)(?:\.py|\.sh|\.active\.json)?\b")


def _module_basename_to_op_id(text: str) -> Optional[str]:
    """Try to extract an op_id from a free-text inbound/outbound string."""
    # First try full path
    m = _REF_RE.search(text)
    if m:
        path = m.group(1)
        bn = Path(path).name
        bn = bn.replace(".py", "").replace(".sh", "").replace(".active.json", "")
        return f"op_{bn}"
    # Fallback: any token that looks like a module name
    candidates = _NAMED_RE.findall(text.lower())
    # filter to known modules — we'll resolve against name_to_id after loading
    return None


def load_agent_def(path: Path) -> Tuple[Optional[OpNode], List[OpEdge]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, []
    name = data.get("name", path.stem)
    op_id = f"op_{name}"
    node = OpNode(
        id=op_id,
        name=name,
        kind="agent",
        status=_infer_status(data),
        role=data.get("role", ""),
        module_path=data.get("module_path") or
                    (data.get("module_paths", [None])[0] if data.get("module_paths") else ""),
        tier=data.get("tier", "L0"),
        cost_class="deterministic",  # most agent_defs are deterministic; LLM ops get overridden later
        source="agent_def",
        description=data.get("summary", "")[:300],
    )
    edges: List[OpEdge] = []
    rc = data.get("routing_connections", {})
    for caller in rc.get("inbound_callers", []) or []:
        src_id = _module_basename_to_op_id(caller)
        if src_id:
            edges.append(OpEdge(src=src_id, dst=op_id, kind="calls", source="agent_def"))
    for callee in rc.get("outbound_calls", []) or []:
        dst_id = _module_basename_to_op_id(callee)
        if dst_id:
            edges.append(OpEdge(src=op_id, dst=dst_id, kind="calls", source="agent_def"))
    return node, edges


def _infer_status(data: Dict) -> str:
    state = (data.get("state") or "").lower()
    if state == "active":
        return "ACTIVE"
    if state in ("inflight", "in-flight", "draft"):
        return "IN-FLIGHT"
    if state == "stub":
        return "STUB"
    return "ACTIVE"  # default for parked agent_defs


def load_workflow_card(path: Path) -> Tuple[List[OpNode], List[OpEdge]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], []
    nodes: List[OpNode] = []
    edges: List[OpEdge] = []
    card_name = data.get("name", path.stem)
    for p in data.get("passes", []):
        pid = p.get("id", "")
        op_id = f"op_pass_{card_name}_{pid}"
        nodes.append(OpNode(
            id=op_id,
            name=f"{card_name}::{pid}",
            kind="pass",
            status=p.get("status", "STUB"),
            role=f"PASS · {p.get('agent','?')} via {p.get('engine','?')}",
            module_path=p.get("model_path", ""),
            cost_class=p.get("tier", "unknown"),
            source="workflow_card",
            description=f"agent={p.get('agent','')}; engine={p.get('engine','')}; out={p.get('out','')}",
        ))
        # Edge: each pass depends on prior passes that produced its inputs
        for in_name in (p.get("in") or []):
            for other in data.get("passes", []):
                if other.get("out") == in_name and other is not p:
                    other_id = f"op_pass_{card_name}_{other.get('id','')}"
                    edges.append(OpEdge(src=other_id, dst=op_id, kind="feeds_into",
                                         source="workflow_card"))
    return nodes, edges


def load_placeholders() -> Tuple[List[OpNode], List[OpEdge]]:
    if not PLACEHOLDERS_FILE.exists():
        return [], []
    try:
        data = json.loads(PLACEHOLDERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], []
    nodes: List[OpNode] = []
    edges: List[OpEdge] = []
    for p in data.get("placeholders", []):
        pid = p.get("id", "")
        nodes.append(OpNode(
            id=pid,
            name=pid.replace("op_", ""),
            kind="placeholder",
            status=p.get("status", "TEXT-PLACEHOLDER"),
            role="PLACEHOLDER",
            cost_class=p.get("cost_class", "unknown"),
            source="manual",
            description=p.get("description", "")[:600],
        ))
        for after in (p.get("expected_after") or []):
            edges.append(OpEdge(src=after, dst=pid, kind="placeholder_for", source="manual"))
        for before in (p.get("expected_before") or []):
            edges.append(OpEdge(src=pid, dst=before, kind="placeholder_for", source="manual"))
    return nodes, edges


def build_ops_dag() -> Tuple[Dict[str, OpNode], List[OpEdge]]:
    nodes: Dict[str, OpNode] = {}
    edges: List[OpEdge] = []

    # Walk agent_defs
    if AGENT_DEFS_DIR.exists():
        for f in sorted(AGENT_DEFS_DIR.glob("*.active.json")):
            node, eds = load_agent_def(f)
            if node is None:
                continue
            nodes[node.id] = node
            edges.extend(eds)

    # Walk workflows
    if WORKFLOWS_DIR.exists():
        for f in sorted(WORKFLOWS_DIR.glob("vm_mspc_001.workflows.*.json")):
            ns, eds = load_workflow_card(f)
            for n in ns:
                nodes[n.id] = n
            edges.extend(eds)

    # Walk text placeholders
    ns, eds = load_placeholders()
    for n in ns:
        nodes[n.id] = n
    edges.extend(eds)

    # Cull edges whose endpoints aren't in nodes (regex false-matches happen)
    edges = [e for e in edges if e.src in nodes and e.dst in nodes]

    # Deduplicate edges
    seen: Set[Tuple[str, str, str]] = set()
    deduped = []
    for e in edges:
        k = (e.src, e.dst, e.kind)
        if k not in seen:
            seen.add(k)
            deduped.append(e)
    return nodes, deduped


# ---------------------------------------------------------------------------
# Emit JSONL
# ---------------------------------------------------------------------------

def emit_jsonl(nodes: Dict[str, OpNode], edges: List[OpEdge], out_path: Path = OUT_PATH) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    # chain root
    lines.append(json.dumps({
        "type": "element", "name": "chain", "depth": 0,
        "attributes": {
            "schema": "ops_dag_v0",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    }, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
    # nodes (sorted by id for determinism)
    for node_id in sorted(nodes.keys()):
        n = nodes[node_id]
        lines.append(json.dumps({
            "type": "element", "name": "op_node", "depth": 1, "parent": "chain",
            "attributes": {
                "id": n.id, "name": n.name, "kind": n.kind, "status": n.status,
                "role": n.role, "module_path": n.module_path, "tier": n.tier,
                "cost_class": n.cost_class, "source": n.source,
            },
            "data": n.description,
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
    # edges (sorted deterministically)
    for e in sorted(edges, key=lambda x: (x.src, x.dst, x.kind)):
        lines.append(json.dumps({
            "type": "element", "name": "op_edge", "depth": 1, "parent": "chain",
            "attributes": {"src": e.src, "dst": e.dst, "kind": e.kind, "source": e.source},
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def topo_sort(nodes: Dict[str, OpNode], edges: List[OpEdge]) -> List[str]:
    """Kahn's algorithm. Returns a topologically sorted list of op_ids."""
    incoming: Dict[str, Set[str]] = {nid: set() for nid in nodes}
    outgoing: Dict[str, Set[str]] = defaultdict(set)
    for e in edges:
        # only consider "ordering" edges (skip the calls metaregex churn)
        if e.kind not in ("feeds_into", "depends_on", "placeholder_for"):
            continue
        incoming[e.dst].add(e.src)
        outgoing[e.src].add(e.dst)

    ready = deque(sorted(nid for nid, deps in incoming.items() if not deps))
    order: List[str] = []
    while ready:
        nid = ready.popleft()
        order.append(nid)
        for nxt in sorted(outgoing[nid]):
            incoming[nxt].discard(nid)
            if not incoming[nxt]:
                ready.append(nxt)
    if len(order) < len(nodes):
        # cycle — append remaining nodes deterministically
        remaining = sorted(set(nodes) - set(order))
        order.extend(remaining)
    return order


def parallel_groups(nodes: Dict[str, OpNode], edges: List[OpEdge]) -> List[List[str]]:
    """Group ops by topological 'level' — same level = parallelizable."""
    incoming: Dict[str, Set[str]] = {nid: set() for nid in nodes}
    outgoing: Dict[str, Set[str]] = defaultdict(set)
    for e in edges:
        if e.kind not in ("feeds_into", "depends_on", "placeholder_for"):
            continue
        incoming[e.dst].add(e.src)
        outgoing[e.src].add(e.dst)

    groups: List[List[str]] = []
    seen: Set[str] = set()
    level_in = dict(incoming)
    while True:
        ready = sorted(nid for nid in nodes if nid not in seen and not level_in[nid])
        if not ready:
            break
        groups.append(ready)
        for nid in ready:
            seen.add(nid)
            for nxt in outgoing[nid]:
                level_in[nxt].discard(nid)
    if len(seen) < len(nodes):
        groups.append(sorted(set(nodes) - seen))
    return groups


def find_placeholders(nodes: Dict[str, OpNode]) -> List[OpNode]:
    return sorted((n for n in nodes.values() if n.status == "TEXT-PLACEHOLDER"),
                  key=lambda x: x.id)


def find_ready(nodes: Dict[str, OpNode], edges: List[OpEdge]) -> List[OpNode]:
    """Ops whose all 'ordering' dependencies are ACTIVE."""
    incoming: Dict[str, List[str]] = defaultdict(list)
    for e in edges:
        if e.kind in ("feeds_into", "depends_on", "placeholder_for"):
            incoming[e.dst].append(e.src)
    ready = []
    for nid, n in nodes.items():
        if n.status == "ACTIVE":
            continue  # already done
        deps = incoming.get(nid, [])
        if all(nodes.get(d, OpNode(id=d, name=d, kind="?")).status == "ACTIVE" for d in deps):
            ready.append(n)
    return sorted(ready, key=lambda x: STATUS_RANKS.get(x.status, 99))


def find_path(nodes: Dict[str, OpNode], edges: List[OpEdge],
              src: str, dst: str) -> List[str]:
    """BFS shortest path from src op to dst op."""
    adj: Dict[str, List[str]] = defaultdict(list)
    for e in edges:
        adj[e.src].append(e.dst)
    if src not in nodes or dst not in nodes:
        return []
    visited: Set[str] = {src}
    queue: deque = deque([(src, [src])])
    while queue:
        cur, path = queue.popleft()
        if cur == dst:
            return path
        for nxt in adj.get(cur, []):
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, path + [nxt]))
    return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _summary(nodes: Dict[str, OpNode], edges: List[OpEdge]) -> Dict:
    by_status = defaultdict(int)
    by_kind = defaultdict(int)
    by_cost = defaultdict(int)
    for n in nodes.values():
        by_status[n.status] += 1
        by_kind[n.kind] += 1
        by_cost[n.cost_class] += 1
    by_edge_kind = defaultdict(int)
    for e in edges:
        by_edge_kind[e.kind] += 1
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "by_status": dict(by_status),
        "by_kind": dict(by_kind),
        "by_cost_class": dict(by_cost),
        "by_edge_kind": dict(by_edge_kind),
    }


def _main():
    import argparse
    ap = argparse.ArgumentParser(description="ops_dag — the operational DAG")
    sub = ap.add_subparsers(dest="cmd")

    p_build = sub.add_parser("build", help="walk substrates and emit ops_dag.jsonl")
    p_build.add_argument("--out", default=str(OUT_PATH))

    p_summary = sub.add_parser("summary")
    p_topo = sub.add_parser("topo", help="topological sort (ordering edges only)")
    p_parallel = sub.add_parser("parallel", help="parallelizable groups by topo level")
    p_placeholders = sub.add_parser("placeholders", help="list TEXT-PLACEHOLDER ops")
    p_ready = sub.add_parser("ready", help="ops whose deps are all ACTIVE")
    p_path = sub.add_parser("path", help="shortest path between two ops")
    p_path.add_argument("src"); p_path.add_argument("dst")

    args = ap.parse_args()
    nodes, edges = build_ops_dag()

    if args.cmd == "build":
        n = emit_jsonl(nodes, edges, Path(args.out))
        print(json.dumps({"out": args.out, "lines": n, **_summary(nodes, edges)}, indent=2))
    elif args.cmd == "summary":
        print(json.dumps(_summary(nodes, edges), indent=2))
    elif args.cmd == "topo":
        order = topo_sort(nodes, edges)
        for nid in order:
            n = nodes[nid]
            print(f"  {n.status:<18} {n.kind:<12} {nid}")
    elif args.cmd == "parallel":
        groups = parallel_groups(nodes, edges)
        for i, group in enumerate(groups):
            print(f"-- level {i} ({len(group)} ops, parallelizable) --")
            for nid in group:
                n = nodes[nid]
                print(f"  {n.status:<18} {n.kind:<12} {nid}")
    elif args.cmd == "placeholders":
        ps = find_placeholders(nodes)
        print(f"{len(ps)} text-placeholder ops:\n")
        for n in ps:
            print(f"  {n.id}")
            print(f"    cost: {n.cost_class}")
            print(f"    {n.description[:200]}")
            print()
    elif args.cmd == "ready":
        ready = find_ready(nodes, edges)
        print(f"{len(ready)} ops ready (deps ACTIVE):\n")
        for n in ready:
            print(f"  {n.status:<18} {n.id}  — {n.description[:140]}")
    elif args.cmd == "path":
        p = find_path(nodes, edges, args.src, args.dst)
        if not p:
            print(json.dumps({"path": [], "found": False}))
        else:
            print(json.dumps({"path": p, "len": len(p)}, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
