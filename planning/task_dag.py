#!/usr/bin/env python3
"""task_dag.py — MySpace++ opcode-graph utility

Loads the HF task taxonomy JSONL and treats each task as an OPCODE with
typed inputs and outputs. The pipeline DAG self-assembles via the rule:

    EDGE(A -> B) exists iff outputs(A) ∩ inputs(B) ≠ ∅

CLI:
  task_dag.py stats                       summary of the taxonomy
  task_dag.py edges [--from TASK]          list edges (filterable)
  task_dag.py consumers TYPE              which tasks accept this modality?
  task_dag.py producers TYPE              which tasks emit this modality?
  task_dag.py paths FROM_MOD TO_MOD       enumerate pipelines (BFS, ≤ max-depth)
                                          e.g.: task_dag.py paths DOC AUDIO

Limitations:
- One-input matching: an edge from A to B is established if any output of
  A matches any input of B. For multi-input downstream tasks (e.g. VQA
  needs both IMAGE and TEXT), the edge says A satisfies ONE input. A real
  pipeline planner would track which inputs remain unmet — left for v2.
- Any-to-Any is treated as accepting/emitting all four core modalities;
  it short-circuits most graphs. Use --no-any-to-any to exclude it.
"""

import argparse
import json
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable

DEFAULT_JSONL = Path(__file__).resolve().parent / "hf_task_evolution.jsonl"


def load(path: Path = DEFAULT_JSONL) -> list[dict]:
    tasks = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        tasks.append(json.loads(line))
    return tasks


def edges(tasks: list[dict], exclude_any: bool = False) -> list[tuple[str, str, str]]:
    """Return [(src_task, dst_task, matching_modality)]."""
    out = []
    for a in tasks:
        if exclude_any and a["task"] == "Any-to-Any":
            continue
        a_outs = set(a.get("outputs", []))
        for b in tasks:
            if a["task"] == b["task"]:
                continue
            if exclude_any and b["task"] == "Any-to-Any":
                continue
            b_ins = set(b.get("inputs", []))
            shared = a_outs & b_ins
            for m in shared:
                out.append((a["task"], b["task"], m))
    return out


def by_name(tasks: list[dict]) -> dict[str, dict]:
    return {t["task"]: t for t in tasks}


def consumers(tasks: list[dict], modality: str) -> list[str]:
    return [t["task"] for t in tasks if modality in t.get("inputs", [])]


def producers(tasks: list[dict], modality: str) -> list[str]:
    return [t["task"] for t in tasks if modality in t.get("outputs", [])]


def paths(
    tasks: list[dict], src_mod: str, dst_mod: str,
    max_depth: int = 5, exclude_any: bool = False,
    extend_past_hit: bool = True,
) -> list[list[str]]:
    """Enumerate task pipelines that begin by consuming src_mod and end by
    producing dst_mod. Returns shortest paths first (BFS, deduped).

    By default (extend_past_hit=True), the BFS records a successful path
    BUT keeps walking — so a longer path that detours through extra
    tasks before re-arriving at dst is also enumerated. This lets the
    ranker see e.g. `V2T2T → Summarize` (length 2, both produce TEXT)
    alongside the minimal `V2T2T` (length 1). Set extend_past_hit=False
    for shortest-only behavior."""
    starts = [t["task"] for t in tasks
              if src_mod in t.get("inputs", [])
              and (not exclude_any or t["task"] != "Any-to-Any")]
    if not starts:
        return []
    # adjacency: task -> [(next_task, matching_modality)]
    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for src, dst, m in edges(tasks, exclude_any=exclude_any):
        adj[src].append((dst, m))

    found: list[list[str]] = []
    seen_paths: set[tuple[str, ...]] = set()
    name_map = by_name(tasks)
    for start in starts:
        # BFS from start
        q = deque([[start]])
        while q:
            path = q.popleft()
            tip = path[-1]
            tip_outs = set(name_map[tip].get("outputs", []))
            if dst_mod in tip_outs:
                key = tuple(path)
                if key not in seen_paths:
                    found.append(path)
                    seen_paths.add(key)
                if not extend_past_hit:
                    continue
            if len(path) >= max_depth:
                continue
            for nxt, _m in adj.get(tip, []):
                if nxt in path:
                    continue   # no cycles
                q.append(path + [nxt])
    found.sort(key=lambda p: (len(p), p))
    return found


def render_path(tasks_by_name: dict[str, dict], path: list[str]) -> str:
    """Render a pipeline with its modality transitions."""
    parts = []
    for i, name in enumerate(path):
        t = tasks_by_name[name]
        ins = "+".join(t.get("inputs", []) or ["-"])
        outs = "+".join(t.get("outputs", []) or ["-"])
        parts.append(f"{name}[{ins}->{outs}]")
    return "  ─►  ".join(parts)


def cmd_stats(args, tasks: list[dict]):
    from collections import Counter
    n = len(tasks)
    print(f"tasks:          {n}")
    print(f"unique inputs:  {sorted({m for t in tasks for m in t.get('inputs', [])})}")
    print(f"unique outputs: {sorted({m for t in tasks for m in t.get('outputs', [])})}")
    e = edges(tasks)
    print(f"edges (raw):    {len(e)}")
    e_no_any = edges(tasks, exclude_any=True)
    print(f"edges (no Any-to-Any): {len(e_no_any)}")
    print("\nlayer distribution:")
    for lyr, c in sorted(Counter(t.get('layer') for t in tasks).items()):
        print(f"  layer {lyr}: {c}")
    print("\nera distribution:")
    for era, c in sorted(Counter(t['era'] for t in tasks).items()):
        print(f"  era {era}: {c}")


def cmd_edges(args, tasks: list[dict]):
    e = edges(tasks, exclude_any=args.no_any)
    if args.from_task:
        e = [x for x in e if x[0] == args.from_task]
    for src, dst, m in sorted(e):
        print(f"  {src}  --[{m}]-->  {dst}")
    print(f"\n{len(e)} edge(s)")


def cmd_consumers(args, tasks: list[dict]):
    for t in sorted(consumers(tasks, args.modality)):
        print(f"  {t}")


def cmd_producers(args, tasks: list[dict]):
    for t in sorted(producers(tasks, args.modality)):
        print(f"  {t}")


def cmd_paths(args, tasks: list[dict]):
    found = paths(tasks, args.src, args.dst,
                  max_depth=args.max_depth, exclude_any=args.no_any)
    if not found:
        print(f"no pipeline found from {args.src} to {args.dst} within {args.max_depth} steps")
        return
    name_map = by_name(tasks)
    print(f"# {len(found)} pipeline(s) {args.src} -> {args.dst}  (max-depth={args.max_depth})")
    for i, path in enumerate(found[:args.limit], 1):
        print(f"\n[{i}] {' -> '.join(path)}")
        print(f"    {render_path(name_map, path)}")


def main():
    ap = argparse.ArgumentParser(description="MySpace++ task-DAG utility")
    ap.add_argument("--jsonl", default=str(DEFAULT_JSONL),
                    help="path to hf_task_evolution.jsonl")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats")

    p_edges = sub.add_parser("edges")
    p_edges.add_argument("--from", dest="from_task", default=None,
                         help="filter to edges leaving this task")
    p_edges.add_argument("--no-any", action="store_true",
                         help="exclude Any-to-Any (collapses graph)")

    p_cons = sub.add_parser("consumers")
    p_cons.add_argument("modality")

    p_prod = sub.add_parser("producers")
    p_prod.add_argument("modality")

    p_paths = sub.add_parser("paths")
    p_paths.add_argument("src", help="starting modality (e.g. DOC)")
    p_paths.add_argument("dst", help="target modality (e.g. AUDIO)")
    p_paths.add_argument("--max-depth", type=int, default=5)
    p_paths.add_argument("--limit", type=int, default=20)
    p_paths.add_argument("--no-any", action="store_true",
                         help="exclude Any-to-Any from the search")

    args = ap.parse_args()
    tasks = load(Path(args.jsonl))

    handlers = {
        "stats": cmd_stats,
        "edges": cmd_edges,
        "consumers": cmd_consumers,
        "producers": cmd_producers,
        "paths": cmd_paths,
    }
    handlers[args.cmd](args, tasks)


if __name__ == "__main__":
    main()
