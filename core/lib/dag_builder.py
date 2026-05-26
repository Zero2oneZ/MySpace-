#!/usr/bin/env python3
"""dag_builder.py — Populates the hash-addressed DAG cache (dag_nodes,
dag_edges, dag_chains, dag_build_queue) from the existing seeded
library (capability_cards + gui_cards + path_builder rankings).

Two roles:

  1. BOOTSTRAP (one-shot): scan all source data, generate stable
     sha256 IDs for every node, persist all nodes/edges/chains.
       python3 dag_builder.py bootstrap

  2. WORKER (long-running OR one-shot): pop tasks from
     dag_build_queue, process them, mark dependents stale where
     needed.
       python3 dag_builder.py work             # one tick
       python3 dag_builder.py work --loop      # daemon-style
       python3 dag_builder.py work --loop --sleep 5

  Plus an enqueue helper:
       python3 dag_builder.py enqueue rebuild_chain <chain_id>

Node ID conventions (stable across runs):
  opcode:   sha256("opcode:" + opcode_name)
  widget:   sha256("widget:" + opcode_name + ":" + widget_name)
  state:    sha256("state:" + opcode_name + ":" + state_name)
  chain:    sha256("chain:" + canonical_chain_repr)
  trans:    sha256("trans:" + src_chain_id + "→" + dst_chain_id)

The hashes are 64-hex sha256 truncated to 16 hex chars for legibility.
Collision probability at our scale (~10K nodes) is < 10^-12.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Default paths — same fallback chain as author_cards.py.
def _find_taxonomy() -> Path:
    candidates = [
        HERE / "hf_task_evolution.jsonl",
        HERE.parent.parent / "planning" / "hf_task_evolution.jsonl",
        HERE.parent / "planning" / "hf_task_evolution.jsonl",
    ]
    if (env := os.environ.get("CC_TAXONOMY")):
        candidates.insert(0, Path(env))
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


def _find_path_builder() -> Path:
    for c in [
        HERE.parent.parent / "planning" / "path_builder.py",
        HERE.parent / "planning" / "path_builder.py",
    ]:
        if c.is_file():
            return c
    return HERE / "path_builder.py"


DB_PATH = (os.environ.get("CC_DB")
           or os.environ.get("CC_GLOBAL_DB")
           or str(Path.home() / ".cc" / "cc.db"))


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30.0, isolation_level=None)
    c.execute("PRAGMA journal_mode = WAL;")
    c.execute("PRAGMA synchronous = NORMAL;")
    return c


# ---- Node ID generators (stable hashes) --------------------------------

def _h(s: str) -> str:
    """sha256 truncated to 16 hex chars."""
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def opcode_id(name: str) -> str:
    return _h(f"opcode:{name}")


def widget_id(opcode: str, widget_name: str) -> str:
    return _h(f"widget:{opcode}:{widget_name}")


def state_id(opcode: str, state_name: str) -> str:
    return _h(f"state:{opcode}:{state_name}")


def chain_id_for(opcodes: list[str]) -> str:
    canonical = "→".join(opcodes)
    return _h(f"chain:{canonical}")


def transition_id(src_chain: str, dst_chain: str) -> str:
    return _h(f"trans:{src_chain}→{dst_chain}")


# ---- MUI lookup --------------------------------------------------------

# Import mui_map.lookup if available.
try:
    from mui_map import lookup as _mui_lookup
except ImportError:
    sys.path.insert(0, str(HERE))
    from mui_map import lookup as _mui_lookup  # type: ignore


def mui_for_widget(widget_name: str, output_kind: str = "") -> str:
    spec = _mui_lookup(widget_name, output_kind)
    return spec.get("component", "Box")


# ---- DB helpers (small subset; full helpers live in db.py) -------------

def upsert_node(c: sqlite3.Connection, node_id: str, kind: str, name: str,
                payload: dict, mui_component: str = "",
                parent: str = "") -> None:
    c.execute(
        "INSERT INTO dag_nodes(node_id, node_kind, name, payload_json, "
        "  mui_component, parent_node) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(node_id) DO UPDATE SET "
        "  payload_json=excluded.payload_json, "
        "  mui_component=excluded.mui_component, "
        "  parent_node=excluded.parent_node, "
        "  updated_at=datetime('now'), stale=0",
        (node_id, kind, name, json.dumps(payload),
         mui_component or None, parent or None),
    )


def upsert_edge(c: sqlite3.Connection, src: str, dst: str, kind: str,
                weight: float = 1.0, payload: dict | None = None) -> None:
    eid = _h(f"{src}→{dst}:{kind}")
    pj = json.dumps(payload) if payload else None
    c.execute(
        "INSERT INTO dag_edges(edge_id, src_node, dst_node, edge_kind, "
        "  weight, payload_json) VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(edge_id) DO UPDATE SET "
        "  weight=excluded.weight, payload_json=excluded.payload_json",
        (eid, src, dst, kind, weight, pj),
    )


def upsert_chain(c: sqlite3.Connection, chain: list[str],
                 score: float, intent_tags: str = "",
                 gui_root: str = "") -> str:
    cid = chain_id_for(chain)
    c.execute(
        "INSERT INTO dag_chains(chain_id, src_opcode, dst_opcode, "
        "  chain_json, score, intent_tags, gui_dag_root) "
        "VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(chain_id) DO UPDATE SET "
        "  chain_json=excluded.chain_json, "
        "  score=excluded.score, "
        "  intent_tags=excluded.intent_tags, "
        "  gui_dag_root=excluded.gui_dag_root, "
        "  updated_at=datetime('now'), stale=0",
        (cid, chain[0], chain[-1], json.dumps(chain), score,
         intent_tags or None, gui_root or None),
    )
    return cid


# ---- Bootstrap ---------------------------------------------------------

def bootstrap(verbose: bool = False) -> dict:
    """Read taxonomy + gui_cards + capability_cards + path_builder
    rankings. Populate dag_nodes, dag_edges, dag_chains. Re-runnable
    (idempotent) — counts represent number of upserts, not net new rows."""
    tax_path = _find_taxonomy()
    if not tax_path.is_file():
        print(f"ERROR: taxonomy not found at {tax_path}", file=sys.stderr)
        print(f"  set CC_TAXONOMY=<path> or place hf_task_evolution.jsonl in "
              f"one of: {[str(HERE / 'hf_task_evolution.jsonl'), '...']}",
              file=sys.stderr)
        sys.exit(1)
    try:
        tax_rows = []
        for line_no, line in enumerate(tax_path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                tax_rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARNING: bad JSON at {tax_path}:{line_no}: {e}",
                      file=sys.stderr)
    except Exception as e:
        print(f"ERROR: failed to read taxonomy: {e}", file=sys.stderr)
        sys.exit(1)
    by_name = {r["task"]: r for r in tax_rows}

    counts = {"opcodes": 0, "widgets": 0, "states": 0,
              "edges": 0, "chains": 0, "skipped_no_gui": 0,
              "skipped_no_path_builder": 0}

    with db() as c:
        # 1) opcode nodes
        for r in tax_rows:
            op = r["task"]
            nid = opcode_id(op)
            payload = {
                "task": op,
                "category": r.get("category"),
                "era": r.get("era"),
                "layer": r.get("layer"),
                "inputs": r.get("inputs"),
                "outputs": r.get("outputs"),
                "exemplars": r.get("exemplars"),
                "role_in_avatar": r.get("role_in_avatar"),
            }
            upsert_node(c, nid, "opcode", op, payload)
            counts["opcodes"] += 1

        # 2) opcode → opcode succession edges (typed by modality match)
        for src in tax_rows:
            src_outs = set(src.get("outputs") or [])
            if not src_outs:
                continue
            for dst in tax_rows:
                if dst["task"] == src["task"]:
                    continue
                dst_ins = set(dst.get("inputs") or [])
                match = src_outs & dst_ins
                if not match:
                    continue
                # weight: prefer pipeline-step continuity, era recency
                w = 1.0 + dst.get("era", 1) * 0.1
                if dst.get("layer") in (3, 5):
                    w += 0.3
                a_step = src.get("pipeline_step")
                b_step = dst.get("pipeline_step")
                if a_step is not None and b_step is not None and b_step == a_step + 1:
                    w += 1.0
                if dst["task"] == "Any-to-Any":
                    w -= 0.5
                upsert_edge(c, opcode_id(src["task"]), opcode_id(dst["task"]),
                            "succession", weight=round(w, 3),
                            payload={"via": sorted(match)})
                counts["edges"] += 1

        # 3) widget + state nodes from gui_cards
        # Track which opcodes have gui_cards so we can warn about gaps
        opcodes_with_gui: set[str] = set()
        for opcode, blob in c.execute(
            "SELECT opcode, card_json FROM gui_cards"
        ):
            try:
                gui = json.loads(blob)
            except json.JSONDecodeError:
                if verbose:
                    print(f"  WARN: bad gui_card JSON for {opcode}",
                          file=sys.stderr)
                continue
            opcodes_with_gui.add(opcode)
            parent = opcode_id(opcode)

            # Input widgets
            for w in gui.get("inputs") or []:
                wname = w.get("name", "?")
                widget_type = w.get("widget", "?")
                wid = widget_id(opcode, wname)
                mui = mui_for_widget(widget_type)
                payload = {
                    "opcode": opcode,
                    "widget": widget_type,
                    "name": wname,
                    "props": w.get("props") or {},
                    "required": bool(w.get("required")),
                    "modality_slot": w.get("modality_slot"),
                    "description": w.get("description", ""),
                }
                upsert_node(c, wid, "widget", wname, payload,
                            mui_component=mui, parent=parent)
                counts["widgets"] += 1
                upsert_edge(c, wid, parent, "input",
                            weight=2.0 if w.get("required") else 1.0)
                counts["edges"] += 1

            # Output widgets — store with modality-prefixed names so
            # the same opcode's multi-output cards don't collide.
            for w in gui.get("outputs") or []:
                modality = w.get("modality", "?")
                wname = f"output_{modality.lower()}"
                widget_type = w.get("widget", "output_preview")
                kind = (w.get("props") or {}).get("kind", "")
                wid = widget_id(opcode, wname)
                mui = mui_for_widget(widget_type, kind)
                payload = {
                    "opcode": opcode,
                    "widget": widget_type,
                    "modality": modality,
                    "kind": kind,
                    "props": w.get("props") or {},
                }
                upsert_node(c, wid, "widget", wname, payload,
                            mui_component=mui, parent=parent)
                counts["widgets"] += 1
                upsert_edge(c, parent, wid, "output", weight=1.0)
                counts["edges"] += 1

            # State machine nodes (validate, submit, running, done, ...)
            meta = gui.get("meta") or {}
            hitl = bool(meta.get("hitl_likely"))
            n_req = sum(1 for w in (gui.get("inputs") or [])
                        if w.get("required"))
            state_chain = ["submit", "running"]
            if n_req >= 2:
                state_chain.insert(0, "validate")
            if hitl:
                state_chain.append("hitl")
            state_chain.extend(["download", "done"])

            prev_state = None
            for sname in state_chain:
                sid = state_id(opcode, sname)
                mui = mui_for_widget(sname)  # state nodes also live in mui_map
                payload = {"opcode": opcode, "state": sname,
                           "runtime_s": meta.get("estimated_runtime_s")}
                upsert_node(c, sid, "state", sname, payload,
                            mui_component=mui, parent=parent)
                counts["states"] += 1
                if prev_state:
                    upsert_edge(c, prev_state, sid, "renders", weight=1.0)
                    counts["edges"] += 1
                prev_state = sid

        # Tally opcodes missing gui_cards (informational, not fatal)
        missing_gui = {r["task"] for r in tax_rows} - opcodes_with_gui
        counts["skipped_no_gui"] = len(missing_gui)
        if verbose and missing_gui:
            print(f"  INFO: {len(missing_gui)} opcode(s) lack a gui_card — "
                  f"run `cc -author-gui-cards <opcode>` to fill in:",
                  file=sys.stderr)
            for m in sorted(missing_gui)[:10]:
                print(f"      - {m}", file=sys.stderr)

        # 4) cached chains — top N per (src_mod, dst_mod) modality pair.
        #    Expanded from 15 hand-picked pairs to all 8×8 pipeline-
        #    carrying modalities = 64 pairs. Each runs path_builder
        #    rank with --top 10 then dedups by chain_id.
        pb = _find_path_builder()
        if not pb.is_file():
            print(f"  WARN: path_builder.py not found at {pb} — "
                  "chains not cached. Bundle it next to dag_builder.py "
                  "or place at planning/path_builder.py.", file=sys.stderr)
            counts["skipped_no_path_builder"] = 1
        if pb.is_file():
            PIPELINE_MODS = ["TEXT", "IMAGE", "AUDIO", "VIDEO", "3D",
                             "DOC", "EMBEDDING", "TIMESERIES"]
            modality_pairs = [(s, d) for s in PIPELINE_MODS
                              for d in PIPELINE_MODS]
            for src_mod, dst_mod in modality_pairs:
                try:
                    r = subprocess.run(
                        [sys.executable, str(pb), "rank", src_mod, dst_mod,
                         "--top", "10"],
                        capture_output=True, text=True, timeout=20,
                    )
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    continue
                for line in r.stdout.splitlines():
                    m = re.match(
                        r"^\[\s*\d+\][^A-Za-z]*score=([\d.]+)\s+(.+?)\s*$",
                        line,
                    )
                    if not m:
                        continue
                    score = float(m.group(1))
                    chain = [s.strip() for s in m.group(2).split("→")]
                    if any(s not in by_name for s in chain):
                        continue
                    tags = f"src:{src_mod},dst:{dst_mod}"
                    gui_root = opcode_id(chain[0])
                    upsert_chain(c, chain, score, intent_tags=tags,
                                 gui_root=gui_root)
                    counts["chains"] += 1

    return counts


# ---- Worker (queue processor) ------------------------------------------

def work_one() -> bool:
    """Pop one task and process it. Returns True if work was done."""
    with db() as c:
        c.execute("BEGIN IMMEDIATE;")
        r = c.execute(
            "SELECT id, task_kind, target_id FROM dag_build_queue "
            "WHERE status='pending' "
            "ORDER BY priority DESC, id LIMIT 1"
        ).fetchone()
        if not r:
            c.execute("COMMIT;")
            return False
        task_id, kind, target = r
        c.execute(
            "UPDATE dag_build_queue SET status='running', "
            "started_at=datetime('now') WHERE id=?",
            (task_id,),
        )
        c.execute("COMMIT;")

    t0 = time.monotonic()
    err = ""
    try:
        if kind == "rebuild_chain":
            _rebuild_chain(target)
        elif kind == "rebuild_node":
            _rebuild_node(target)
        elif kind == "mark_stale":
            with db() as c:
                c.execute("UPDATE dag_chains SET stale=1 WHERE chain_id=?",
                          (target,))
                c.execute("UPDATE dag_nodes SET stale=1 WHERE node_id=?",
                          (target,))
        else:
            err = f"unknown task_kind {kind!r}"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    ms = int((time.monotonic() - t0) * 1000)

    with db() as c:
        c.execute(
            "UPDATE dag_build_queue SET status=?, finished_at=datetime('now'), "
            "ms_elapsed=?, error_text=? WHERE id=?",
            ("failed" if err else "done", ms, err or None, task_id),
        )
    return True


def _rebuild_chain(chain_id: str) -> None:
    """Re-score and refresh a cached chain. For now, just touches the
    updated_at + clears stale flag (real recompute hooks into the
    full scoring formula in path_builder)."""
    with db() as c:
        c.execute(
            "UPDATE dag_chains SET stale=0, updated_at=datetime('now') "
            "WHERE chain_id=?",
            (chain_id,),
        )


def _rebuild_node(node_id: str) -> None:
    with db() as c:
        c.execute(
            "UPDATE dag_nodes SET stale=0, updated_at=datetime('now') "
            "WHERE node_id=?",
            (node_id,),
        )


def work_loop(sleep_s: int = 5) -> None:
    """Run until SIGINT. Pop tasks, sleep when queue empty."""
    print(f"# dag worker loop started (sleep {sleep_s}s when idle). "
          "Ctrl-C to stop.", file=sys.stderr)
    while True:
        did = work_one()
        if not did:
            time.sleep(sleep_s)


def invalidate(opcode: str) -> dict:
    """Mark all dag_nodes (widgets + states for this opcode), all
    succession edges leaving/entering it, and all chains containing it
    as stale. The async builder can then re-process them; or `cc -dag-
    bootstrap` re-runs everything regardless."""
    nid = opcode_id(opcode)
    counts = {"nodes": 0, "chains": 0}
    with db() as c:
        # The opcode node itself + all widgets/states whose parent is it.
        cur = c.execute(
            "UPDATE dag_nodes SET stale=1 "
            "WHERE node_id=? OR parent_node=?",
            (nid, nid),
        )
        counts["nodes"] = cur.rowcount
        # All chains whose JSON contains this opcode name. sqlite's
        # JSON1 supports this directly; LIKE works in a pinch.
        cur = c.execute(
            "UPDATE dag_chains SET stale=1 "
            "WHERE chain_json LIKE ?",
            (f'%"{opcode}"%',),
        )
        counts["chains"] = cur.rowcount
    return counts


# ---- CLI ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(prog="dag_builder.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap", help="scan source data and populate cache")
    b.add_argument("--verbose", action="store_true",
                   help="show per-opcode warnings during bootstrap")
    w = sub.add_parser("work", help="process queue tasks")
    w.add_argument("--loop", action="store_true")
    w.add_argument("--sleep", type=int, default=5)
    e = sub.add_parser("enqueue", help="add a task to the build queue")
    e.add_argument("task_kind")
    e.add_argument("target_id")
    e.add_argument("--priority", type=int, default=0)
    inv = sub.add_parser("invalidate",
                         help="mark all cache rows for an opcode stale")
    inv.add_argument("opcode")
    args = ap.parse_args()

    if args.cmd == "bootstrap":
        counts = bootstrap(verbose=args.verbose)
        for k, v in counts.items():
            print(f"  {k:<22} {v}")
    elif args.cmd == "work":
        if args.loop:
            try:
                work_loop(args.sleep)
            except KeyboardInterrupt:
                print("\n# stopped", file=sys.stderr)
        else:
            did = work_one()
            print("processed 1" if did else "queue empty")
    elif args.cmd == "enqueue":
        with db() as c:
            cur = c.execute(
                "INSERT INTO dag_build_queue(task_kind, target_id, priority) "
                "VALUES(?,?,?)",
                (args.task_kind, args.target_id, args.priority),
            )
            print(cur.lastrowid)
    elif args.cmd == "invalidate":
        counts = invalidate(args.opcode)
        print(f"  marked stale: {counts['nodes']} node(s), "
              f"{counts['chains']} chain(s)")


if __name__ == "__main__":
    main()
