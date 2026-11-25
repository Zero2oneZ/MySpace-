#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        recursive_workflows
# role:        ENGINE · RECURSION_DETECTOR_FIFTH_SUB_DAG
# tier:        L0
# substrate:   detects self-referential patterns across every DAG built so far
# storage:     studio/assets/_recursions/<crystal>.json (one per detected pattern)
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - dag_loop.load_recursive_workflows() — picked up as 5th sub-DAG
#   - cc loop recursive — direct CLI invocation
#   - studio_runtime (when card pass.engine='recursion_detector')
# outbound:
#   - ops_dag.build_ops_dag (universal node store, agents + passes + placeholders)
#   - dag_loop.build_loop_dag (platforms + docs + inference + apps)
#   - inference_logger.log (one InferenceRecord per detected recursion, tier='recursion')
# substrate touch:
#   - reads:  everything ops_dag + dag_loop discover
#   - writes: studio/assets/_recursions/, ~/.cc/inference_master_chain.jsonl
# ----------------------------------------------------------------------------
# WHAT IT FINDS
# ----------------------------------------------------------------------------
# Three categories of recursion:
#   (1) STRONGLY-CONNECTED COMPONENTS (Tarjan)
#       — clusters where every node can reach every other node
#       — these are the TRUE feedback loops in the system
#   (2) SIMPLE CYCLES (DFS-based enumeration, bounded)
#       — ordered loops that close on themselves
#       — eg: studio_runtime → workflow_card → studio_runtime
#   (3) REPEATED MOTIFS (canonical-signature matching)
#       — subgraph patterns that appear multiple times in the universe
#       — eg: (platform → parser → inference → app) appears in N products
#
# Each recursion becomes a node in the 5th sub-DAG: RECURSIVE_WORKFLOWS
# Crystal-anchored. Named. Cross-linked back into the original sub-DAGs.
# ============================================================================
"""recursive_workflows.py — the 5th-DAG recursion detector.

Walks every DAG already built (ops_dag + dag_loop) → aggregates into one
mega-graph → applies Tarjan SCC + bounded cycle enumeration + motif mining
→ emits one node per detected recursion with crystal anchor. The next
dag_loop cycle picks them up as RECURSIVE_WORKFLOWS sub-DAG members.

This closes the universe: every closed loop in the substrate becomes
a first-class object the chain can reason about.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Recursion:
    id: str                          # rec_<kind>_<head>_<size>
    kind: str                        # scc | simple_cycle | motif
    nodes: List[str]                 # the node IDs involved (ordered for cycles)
    size: int                        # len(nodes)
    sub_dags_touched: List[str]      # which of PLATFORMS/DOCS/INFERENCE/APPS this spans
    edge_kinds_traversed: List[str]  # eg ["calls", "feeds_into"]
    has_self_loop: bool = False
    name: str = ""                   # human-readable
    description: str = ""
    crystal: str = ""

    def compute_crystal(self) -> str:
        canonical = json.dumps({
            "kind": self.kind,
            "nodes": sorted(self.nodes) if self.kind in ("scc", "motif") else list(self.nodes),
            "edge_kinds_traversed": sorted(self.edge_kinds_traversed),
        }, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        self.crystal = _hash(canonical.encode("utf-8"))
        return self.crystal


# ---------------------------------------------------------------------------
# Universal graph builder — aggregate every DAG we've built
# ---------------------------------------------------------------------------

def build_universal_graph() -> Tuple[Dict[str, Dict[str, Any]], List[Tuple[str, str, str]], Dict[str, str]]:
    """Aggregate nodes from ops_dag + dag_loop into one mega-graph.
    Returns:
        nodes: {node_id: {name, kind, sub_dag, status, ...}}
        edges: [(src, dst, edge_kind), ...]
        sub_dag_of: {node_id: sub_dag_name}
    """
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Tuple[str, str, str]] = []
    sub_dag_of: Dict[str, str] = {}

    # 1. ops_dag — agent + pass + placeholder nodes
    try:
        from ops_dag import build_ops_dag  # type: ignore
        op_nodes, op_edges = build_ops_dag()
        for nid, n in op_nodes.items():
            nodes[nid] = {
                "name": n.name, "kind": n.kind, "sub_dag": "ORCHESTRATION",
                "status": n.status, "role": n.role,
                "module_path": n.module_path, "source": n.source,
            }
            sub_dag_of[nid] = "ORCHESTRATION"
        for e in op_edges:
            edges.append((e.src, e.dst, e.kind))
    except Exception as exc:
        print(f"warning: ops_dag load failed: {exc}", file=sys.stderr)

    # 2. dag_loop — platform / doc / inference / app nodes
    try:
        from dag_loop import build_loop_dag  # type: ignore
        loop_nodes, loop_edges = build_loop_dag()
        for nid, n in loop_nodes.items():
            if nid not in nodes:
                nodes[nid] = {
                    "name": n.name, "kind": n.kind, "sub_dag": n.sub_dag,
                    "status": n.status, "role": n.role,
                    "module_path": n.module_path, "source": n.source,
                }
            sub_dag_of[nid] = n.sub_dag
        for e in loop_edges:
            edges.append((e.src, e.dst, e.kind))
    except Exception as exc:
        print(f"warning: dag_loop load failed: {exc}", file=sys.stderr)

    # 3. Cull edges whose endpoints aren't in nodes (provenance regex dropouts)
    edges = [e for e in edges if e[0] in nodes and e[1] in nodes]

    # 4. Dedup edges
    seen: Set[Tuple[str, str, str]] = set()
    deduped: List[Tuple[str, str, str]] = []
    for e in edges:
        if e not in seen:
            seen.add(e); deduped.append(e)

    return nodes, deduped, sub_dag_of


# ---------------------------------------------------------------------------
# (1) Tarjan SCC
# ---------------------------------------------------------------------------

def tarjan_scc(nodes: Dict[str, Any],
                 edges: Iterable[Tuple[str, str, str]]) -> List[List[str]]:
    """Tarjan's strongly-connected components.
    Returns: list of SCCs, each a list of node IDs."""
    adj: Dict[str, List[str]] = defaultdict(list)
    for src, dst, _ in edges:
        adj[src].append(dst)

    index_counter = [0]
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    result: List[List[str]] = []

    sys.setrecursionlimit(max(10_000, len(nodes) * 4))

    def strongconnect(v: str) -> None:
        indices[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], indices[w])

        if lowlink[v] == indices[v]:
            scc: List[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            result.append(scc)

    for v in nodes:
        if v not in indices:
            strongconnect(v)

    return result


# ---------------------------------------------------------------------------
# (2) Simple cycles — bounded DFS enumeration
# ---------------------------------------------------------------------------

def find_simple_cycles(nodes: Dict[str, Any],
                         edges: Iterable[Tuple[str, str, str]],
                         max_cycles: int = 200,
                         max_length: int = 8) -> List[List[str]]:
    """Find simple directed cycles up to max_length. Bounded enumeration
    so we don't blow up on dense graphs."""
    adj: Dict[str, List[str]] = defaultdict(list)
    for src, dst, _ in edges:
        adj[src].append(dst)

    cycles: List[List[str]] = []
    seen_signatures: Set[Tuple[str, ...]] = set()

    def canonical(cycle: List[str]) -> Tuple[str, ...]:
        """Rotate so smallest node is first; this dedupes cycle rotations."""
        if not cycle:
            return tuple()
        min_idx = cycle.index(min(cycle))
        rotated = tuple(cycle[min_idx:] + cycle[:min_idx])
        return rotated

    def dfs(start: str, current: str, path: List[str], visited: Set[str]) -> None:
        if len(cycles) >= max_cycles:
            return
        if len(path) > max_length:
            return
        for nxt in adj.get(current, []):
            if nxt == start and len(path) >= 1:
                # Found a cycle (length ≥ 2 incl. self-loops as length 1+1)
                cycle = path[:]
                sig = canonical(cycle)
                if sig not in seen_signatures:
                    seen_signatures.add(sig)
                    cycles.append(cycle)
            elif nxt not in visited and nxt > start:
                # Constraint: only explore nodes lexicographically greater than start
                # — Johnson-style pruning; we'll find each cycle from its smallest node
                visited.add(nxt); path.append(nxt)
                dfs(start, nxt, path, visited)
                path.pop(); visited.discard(nxt)

    for v in sorted(nodes.keys()):
        if len(cycles) >= max_cycles:
            break
        dfs(v, v, [v], {v})

    return cycles


# ---------------------------------------------------------------------------
# (3) Motif mining — repeated subgraph patterns by canonical signature
# ---------------------------------------------------------------------------

def find_motifs(nodes: Dict[str, Any],
                  edges: Iterable[Tuple[str, str, str]],
                  signature_kind_of: Dict[str, str],
                  min_repetitions: int = 3,
                  motif_length: int = 3) -> Dict[str, List[List[str]]]:
    """Find sequences of length=motif_length (node kinds, in order) that
    repeat at least min_repetitions times across the graph.
    Returns: {signature: [path1, path2, ...]}"""
    adj: Dict[str, List[str]] = defaultdict(list)
    for src, dst, _ in edges:
        adj[src].append(dst)

    by_signature: Dict[str, List[List[str]]] = defaultdict(list)

    def walk(start: str, path: List[str]) -> None:
        if len(path) == motif_length:
            sig = "→".join(signature_kind_of.get(n, nodes.get(n, {}).get("kind", "?"))
                            for n in path)
            by_signature[sig].append(path[:])
            return
        for nxt in adj.get(path[-1], []):
            if nxt in path:
                continue
            path.append(nxt)
            walk(start, path)
            path.pop()

    for v in nodes:
        walk(v, [v])

    return {sig: paths for sig, paths in by_signature.items()
             if len(paths) >= min_repetitions}


# ---------------------------------------------------------------------------
# Build Recursion objects
# ---------------------------------------------------------------------------

def recursions_from_sccs(sccs: List[List[str]], nodes: Dict[str, Any],
                           edges: List[Tuple[str, str, str]],
                           sub_dag_of: Dict[str, str]) -> List[Recursion]:
    """Filter SCCs to those of size ≥ 2 (true cycles) or with self-loops."""
    self_loops = {src for src, dst, _ in edges if src == dst}
    recs: List[Recursion] = []
    for i, scc in enumerate(sorted(sccs, key=lambda s: (-len(s), s[0] if s else ""))):
        if len(scc) >= 2 or (len(scc) == 1 and scc[0] in self_loops):
            sub_dags = sorted({sub_dag_of.get(n, "?") for n in scc})
            scc_edge_kinds = sorted({
                kind for src, dst, kind in edges
                if src in scc and dst in scc
            })
            head = scc[0]
            rec_id = f"rec_scc_{head}_{len(scc):02d}_{i:03d}"
            name = _generate_recursion_name(scc, nodes)
            r = Recursion(
                id=rec_id, kind="scc", nodes=scc, size=len(scc),
                sub_dags_touched=sub_dags, edge_kinds_traversed=scc_edge_kinds,
                has_self_loop=any(n in self_loops for n in scc),
                name=name,
                description=f"SCC of {len(scc)} nodes spanning {','.join(sub_dags)}",
            )
            r.compute_crystal()
            recs.append(r)
    return recs


def recursions_from_simple_cycles(cycles: List[List[str]], nodes: Dict[str, Any],
                                     edges: List[Tuple[str, str, str]],
                                     sub_dag_of: Dict[str, str]) -> List[Recursion]:
    recs: List[Recursion] = []
    edge_kind_lookup: Dict[Tuple[str, str], str] = {}
    for src, dst, k in edges:
        edge_kind_lookup[(src, dst)] = k

    for i, cyc in enumerate(sorted(cycles, key=lambda c: (len(c), c[0]))):
        sub_dags = sorted({sub_dag_of.get(n, "?") for n in cyc})
        cyc_edges_kinds = []
        for j in range(len(cyc)):
            a, b = cyc[j], cyc[(j + 1) % len(cyc)]
            if (a, b) in edge_kind_lookup:
                cyc_edges_kinds.append(edge_kind_lookup[(a, b)])
        cyc_edges_kinds = sorted(set(cyc_edges_kinds))
        rec_id = f"rec_cycle_{cyc[0]}_{len(cyc):02d}_{i:03d}"
        name = _generate_recursion_name(cyc, nodes)
        r = Recursion(
            id=rec_id, kind="simple_cycle", nodes=cyc, size=len(cyc),
            sub_dags_touched=sub_dags, edge_kinds_traversed=cyc_edges_kinds,
            name=name,
            description=f"Simple cycle of length {len(cyc)} spanning {','.join(sub_dags)}",
        )
        r.compute_crystal()
        recs.append(r)
    return recs


def recursions_from_motifs(motifs: Dict[str, List[List[str]]],
                              nodes: Dict[str, Any],
                              sub_dag_of: Dict[str, str]) -> List[Recursion]:
    recs: List[Recursion] = []
    for i, (sig, paths) in enumerate(sorted(motifs.items(),
                                              key=lambda kv: (-len(kv[1]), kv[0]))):
        all_nodes_in_pattern: Set[str] = set()
        for p in paths:
            for n in p:
                all_nodes_in_pattern.add(n)
        sub_dags = sorted({sub_dag_of.get(n, "?") for n in all_nodes_in_pattern})
        rec_id = f"rec_motif_{sig.replace('→', '_to_').replace(' ', '_')[:60]}_{i:03d}"
        r = Recursion(
            id=rec_id, kind="motif",
            nodes=sorted(all_nodes_in_pattern),
            size=len(paths),  # # of repetitions
            sub_dags_touched=sub_dags, edge_kinds_traversed=[],
            name=f"motif: {sig}",
            description=f"Pattern '{sig}' appears {len(paths)} times across {','.join(sub_dags)}",
        )
        r.compute_crystal()
        recs.append(r)
    return recs


def _generate_recursion_name(node_ids: List[str], nodes: Dict[str, Any]) -> str:
    """Produce a short human-readable name from the involved node names."""
    short = []
    for nid in node_ids[:3]:
        n = nodes.get(nid, {})
        nm = n.get("name", nid)
        # strip op_ prefix and limit width
        nm = nm.replace("op_", "")[:18]
        short.append(nm)
    suffix = "..." if len(node_ids) > 3 else ""
    return " → ".join(short) + suffix


# ---------------------------------------------------------------------------
# Persistence + chain logging
# ---------------------------------------------------------------------------

RECURSIONS_DIR = _PROJECT_ROOT / "studio" / "assets" / "_recursions"


def persist_recursions(recursions: List[Recursion]) -> int:
    RECURSIONS_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for r in recursions:
        out_path = RECURSIONS_DIR / f"{r.id[:120]}_{r.crystal[:12]}.json"
        out_path.write_text(json.dumps(asdict(r), sort_keys=True, indent=2,
                                          ensure_ascii=True), encoding="utf-8")
        written += 1
    return written


def log_to_crystal_chain(recursions: List[Recursion]) -> int:
    try:
        from inference_logger import InferenceLogger  # type: ignore
    except ImportError:
        return 0
    il = InferenceLogger()
    logged = 0
    for r in recursions:
        try:
            il.log(
                original_prompt=r.id,
                enhanced_prompt=r.name,
                output_text=r.description,
                tier="recursion", model="recursive_workflows",
                tokens_in=0, tokens_out=0, latency_ms=0,
                chain_context="five_dag_recursion_detector",
                done_flag=True,
            )
            logged += 1
        except Exception:
            continue
    return logged


# ---------------------------------------------------------------------------
# Main detector — runs all three categories
# ---------------------------------------------------------------------------

def detect_all(max_cycles: int = 200, max_cycle_length: int = 8,
                 motif_length: int = 3, motif_min_repetitions: int = 3) -> Dict[str, Any]:
    """Run all three detectors. Return aggregate result with recursions list."""
    nodes, edges, sub_dag_of = build_universal_graph()

    # SCCs
    sccs = tarjan_scc(nodes, edges)
    scc_recs = recursions_from_sccs(sccs, nodes, edges, sub_dag_of)

    # Simple cycles
    cycles = find_simple_cycles(nodes, edges,
                                  max_cycles=max_cycles,
                                  max_length=max_cycle_length)
    cyc_recs = recursions_from_simple_cycles(cycles, nodes, edges, sub_dag_of)

    # Motifs (by node kind)
    signature_kind_of = {nid: n.get("kind", "?") for nid, n in nodes.items()}
    motifs = find_motifs(nodes, edges, signature_kind_of,
                          min_repetitions=motif_min_repetitions,
                          motif_length=motif_length)
    motif_recs = recursions_from_motifs(motifs, nodes, sub_dag_of)

    all_recursions = scc_recs + cyc_recs + motif_recs

    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "universe_nodes": len(nodes),
        "universe_edges": len(edges),
        "sccs_found": len(scc_recs),
        "simple_cycles_found": len(cyc_recs),
        "motifs_found": len(motif_recs),
        "recursions": all_recursions,
        "sub_dag_distribution": {
            sd: sum(1 for r in all_recursions if sd in r.sub_dags_touched)
            for sd in ("PLATFORMS", "DOCS", "INFERENCE", "APPS", "ORCHESTRATION")
        },
    }


# ---------------------------------------------------------------------------
# Loader for dag_loop to consume as 5th sub-DAG
# ---------------------------------------------------------------------------

def load_recursive_workflows_as_nodes() -> List[Dict[str, Any]]:
    """Return persisted recursion records as LoopNode-compatible dicts.
    Called by dag_loop.load_recursive_workflows() to integrate."""
    out: List[Dict[str, Any]] = []
    if not RECURSIONS_DIR.exists():
        return out
    for f in sorted(RECURSIONS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "id": data["id"],
            "name": data.get("name", data["id"])[:60],
            "kind": "recursive_workflow",
            "sub_dag": "RECURSIVE_WORKFLOWS",
            "status": "ACTIVE",
            "role": f"RECURSION_{data.get('kind', 'unknown').upper()}",
            "module_path": str(f.relative_to(_PROJECT_ROOT)),
            "source": "recursive_workflows.detect_all",
            "description": data.get("description", ""),
            "_extras": {
                "crystal": data.get("crystal", ""),
                "size": data.get("size", 0),
                "sub_dags_touched": data.get("sub_dags_touched", []),
                "involved_nodes": data.get("nodes", []),
            },
        })
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _summary_table(recursions: List[Recursion], limit: int = 30) -> str:
    rows: List[str] = []
    rows.append(f"{'KIND':14s} {'SIZE':>5s}  {'CRYSTAL':16s}  {'SUB-DAGS':30s}  NAME")
    rows.append("-" * 110)
    for r in recursions[:limit]:
        rows.append(
            f"{r.kind:14s} {r.size:5d}  {r.crystal[:16]:16s}  "
            f"{','.join(r.sub_dags_touched)[:30]:30s}  {r.name[:60]}"
        )
    if len(recursions) > limit:
        rows.append(f"... ({len(recursions) - limit} more)")
    return "\n".join(rows)


def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="recursive_workflows — find recursion across every DAG")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("all", help="run all three detectors + persist + log to chain")
    sub.add_parser("scc", help="strongly connected components only")
    sub.add_parser("cycles", help="simple cycles only")
    sub.add_parser("motifs", help="repeated motifs only")
    sub.add_parser("list", help="list persisted recursions")
    sub.add_parser("graph", help="dump the universal mega-graph for inspection")

    args = ap.parse_args()

    if args.cmd == "all" or args.cmd is None:
        result = detect_all()
        recursions = result["recursions"]
        n_persisted = persist_recursions(recursions)
        n_logged = log_to_crystal_chain(recursions)
        print(json.dumps({
            "ts": result["ts"],
            "universe_nodes": result["universe_nodes"],
            "universe_edges": result["universe_edges"],
            "sccs_found": result["sccs_found"],
            "simple_cycles_found": result["simple_cycles_found"],
            "motifs_found": result["motifs_found"],
            "sub_dag_distribution": result["sub_dag_distribution"],
            "persisted_to_disk": n_persisted,
            "logged_to_chain": n_logged,
        }, indent=2))
        print()
        print("=== top recursions ===")
        print(_summary_table(recursions, limit=30))

    elif args.cmd == "scc":
        nodes, edges, sub_dag_of = build_universal_graph()
        sccs = tarjan_scc(nodes, edges)
        recs = recursions_from_sccs(sccs, nodes, edges, sub_dag_of)
        print(_summary_table(recs, limit=50))
        print(f"\n[{len(recs)} SCCs · {len(sccs)} total SCCs incl. singletons]")

    elif args.cmd == "cycles":
        nodes, edges, sub_dag_of = build_universal_graph()
        cycles = find_simple_cycles(nodes, edges)
        recs = recursions_from_simple_cycles(cycles, nodes, edges, sub_dag_of)
        print(_summary_table(recs, limit=50))
        print(f"\n[{len(recs)} simple cycles]")

    elif args.cmd == "motifs":
        nodes, edges, sub_dag_of = build_universal_graph()
        sig_of = {nid: n.get("kind", "?") for nid, n in nodes.items()}
        motifs = find_motifs(nodes, edges, sig_of)
        recs = recursions_from_motifs(motifs, nodes, sub_dag_of)
        print(_summary_table(recs, limit=50))
        print(f"\n[{len(recs)} motifs]")

    elif args.cmd == "list":
        recs = load_recursive_workflows_as_nodes()
        for r in recs[:50]:
            print(f"{r['role']:30s} {r['_extras']['crystal'][:16]}  {r['name']}")
        print(f"\n[{len(recs)} persisted recursions]")

    elif args.cmd == "graph":
        nodes, edges, sub_dag_of = build_universal_graph()
        print(json.dumps({
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "by_sub_dag": {sd: sum(1 for s in sub_dag_of.values() if s == sd)
                             for sd in {"PLATFORMS", "DOCS", "INFERENCE", "APPS",
                                         "ORCHESTRATION", "RECURSIVE_WORKFLOWS"}},
            "edge_kinds": {kind: sum(1 for _, _, k in edges if k == kind)
                             for kind in {k for _, _, k in edges}},
        }, indent=2))

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
