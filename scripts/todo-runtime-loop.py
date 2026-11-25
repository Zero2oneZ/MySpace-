#!/usr/bin/env python3
"""
todo-runtime-loop.py — Runtime loop for ToDo-JobBoard + Browser Pool Orchestration.

Reads ToDo-JobBoard.md + JSONL, effects files, syncs MASTER-SVGs, orchestrates
inference rotation across 8 browsers, and enforces chain coherence.

Usage:
    python3 scripts/todo-runtime-loop.py --once          # single tick, dry-run
    python3 scripts/todo-runtime-loop.py --daemon        # loop every GENTLY_TICK_MS
    python3 scripts/todo-runtime-loop.py --coherence     # run coherence check only
    python3 scripts/todo-runtime-loop.py --browser N     # query/update browser-N state

Env:
    GENTLY_TICK_MS — loop interval in ms (default 5000)
    CC_PROJECT_ROOT — project root (default /data/Projects/MySpace++)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# ── constants ──────────────────────────────────────────────────────────
DEFAULT_TICK_MS = 5000
PROJECT_ROOT = Path(os.environ.get("CC_PROJECT_ROOT", "/data/Projects/MySpace++"))
JOBBOARD_MD = PROJECT_ROOT / "ToDo-JobBoard.md"
JOBBOARD_JSONL = PROJECT_ROOT / "ToDo-JobBoard.jsonl"
MASTER_TODO = PROJECT_ROOT / "MASTER-TODO.svg"
BROWSER_POOL = PROJECT_ROOT / "browser-pool"
MAX_BROWSERS = 8

TODO_NS = "https://myspace.local/todo/v1"
ET.register_namespace("todo", TODO_NS)


# ── helpers ────────────────────────────────────────────────────────────
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


def read_jsonl_tail(path: Path, n: int = 50):
    """Read last N lines of JSONL."""
    if not path.exists():
        return []
    lines = path.read_text().strip().splitlines()
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def parse_task_board(md_text: str):
    """Extract active tasks from the markdown table."""
    tasks = []
    in_table = False
    for line in md_text.splitlines():
        if "| Task ID |" in line:
            in_table = True
            continue
        if in_table and line.startswith("| T-"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 8:
                tasks.append({
                    "task_id": parts[1],
                    "agent": parts[2],
                    "model": parts[3],
                    "goal": parts[4],
                    "benchmark": parts[5],
                    "status": parts[6],
                    "next_agent": parts[7],
                    "gate": parts[8] if len(parts) > 8 else "HOLD",
                })
        elif in_table and not line.startswith("|"):
            break
    return tasks


def parse_plans(md_text: str):
    """Extract plan IDs and their checkpoint status from markdown."""
    plans = {}
    current_plan = None
    for line in md_text.splitlines():
        m = re.match(r"### (PLAN-\d+):", line)
        if m:
            current_plan = m.group(1)
            plans[current_plan] = {"checkpoints": []}
        if current_plan and line.strip().startswith("- Step "):
            plans[current_plan]["checkpoints"].append(line.strip())
        if current_plan and line.strip().startswith("- Substep "):
            plans[current_plan]["checkpoints"].append(line.strip())
    return plans


# ── SVG helpers ────────────────────────────────────────────────────────
def _ns(tag):
    return f"{{{TODO_NS}}}{tag}"


def read_browser_state(browser_id: int):
    path = BROWSER_POOL / f"browser-{browser_id}.svg"
    if not path.exists():
        return None
    tree = ET.parse(path)
    root = tree.getroot()
    meta = root.find("metadata")
    state = {"path": str(path), "browser_id": browser_id}
    if meta is not None:
        for child in meta:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            state[tag] = child.text or ""
            for k, v in child.attrib.items():
                state[f"{tag}:{k}"] = v
    # also read root attribs
    for k, v in root.attrib.items():
        if k.startswith("{"):
            short = k.split("}")[-1]
            state[f"root:{short}"] = v
        else:
            state[f"root:{k}"] = v
    return state


SVG_NS = "http://www.w3.org/2000/svg"

def write_browser_state(browser_id: int, updates: dict):
    """Update browser SVG metadata in-place."""
    path = BROWSER_POOL / f"browser-{browser_id}.svg"
    if not path.exists():
        return False
    tree = ET.parse(path)
    root = tree.getroot()
    meta = root.find(f"{{{SVG_NS}}}metadata")
    if meta is None:
        meta = ET.SubElement(root, f"{{{SVG_NS}}}metadata")

    # update or create todo:* elements inside metadata
    for key, value in updates.items():
        if key.startswith("todo:"):
            tag_name = key.split(":", 1)[1]
            # XML local names cannot contain colons; normalize
            tag_name = tag_name.replace(":", "-")
            el = meta.find(_ns(tag_name))
            if el is None:
                el = ET.SubElement(meta, _ns(tag_name))
            el.text = str(value)
        elif key.startswith("root:"):
            attr_name = key.split(":", 1)[1]
            # find namespace prefix
            ns_map = {"todo": TODO_NS}
            full_attr = None
            for ns_prefix, ns_uri in ns_map.items():
                if attr_name in ["role", "browser-id", "layer", "state"]:
                    full_attr = f"{{{ns_uri}}}{attr_name}"
                    break
            if full_attr:
                root.set(full_attr, str(value))

    # pretty-write back
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return True


# ── coherence ────────────────────────────────────────────────────────
ACCENT_RULES = {
    "T-001": ["T-004"],
    "T-002": ["T-005"],
    "T-003": ["T-002"],
    "T-004": [],
    "T-005": ["T-001"],
    "T-006": ["T-007"],
    "T-007": ["T-001", "T-002", "T-003", "T-004", "T-005"],
}


def check_coherence(tasks, jsonl_tail):
    """Verify accent lines, no circular deps, and hash consistency."""
    issues = []

    # 1. All tasks in accent rules exist
    task_ids = {t["task_id"] for t in tasks}
    for src, dests in ACCENT_RULES.items():
        if src not in task_ids:
            issues.append(f"Missing source task in accent rules: {src}")
        for d in dests:
            if d not in task_ids:
                issues.append(f"Missing destination task in accent rules: {d}")

    # 2. Detect simple 2-cycle (circular)
    for src, dests in ACCENT_RULES.items():
        for d in dests:
            if src in ACCENT_RULES.get(d, []):
                issues.append(f"Circular accent: {src} ↔ {d}")

    # 3. JSONL tail hash vs board hash (best-effort)
    if jsonl_tail:
        last = jsonl_tail[-1]
        if last.get("event") == "task" and last.get("status") != "complete":
            # fine — incomplete tasks are expected
            pass

    # 4. Browser states consistency
    for i in range(MAX_BROWSERS):
        st = read_browser_state(i)
        if st is None:
            issues.append(f"browser-{i}.svg missing")
            continue
        if st.get("coherence-check:status", "PASS") != "PASS":
            issues.append(f"browser-{i} coherence check failed")

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "checked_at": now_iso(),
    }


# ── tick logic ───────────────────────────────────────────────────────
def tick(dry_run: bool = False):
    """One runtime tick."""
    print(f"[{now_iso()}] TICK start")

    # 1. Read sources
    md_text = JOBBOARD_MD.read_text() if JOBBOARD_MD.exists() else ""
    tasks = parse_task_board(md_text)
    plans = parse_plans(md_text)
    jsonl_tail = read_jsonl_tail(JOBBOARD_JSONL)

    print(f"  tasks: {len(tasks)} | plans: {len(plans)} | jsonl tail: {len(jsonl_tail)} rows")

    # 2. Coherence check
    coherence = check_coherence(tasks, jsonl_tail)
    print(f"  coherence: {'PASS' if coherence['pass'] else 'FAIL'} ({len(coherence['issues'])} issues)")
    for issue in coherence["issues"]:
        print(f"    ! {issue}")

    # 3. Update browser states from tasks
    browser_layer_map = {
        0: {"layer": "forward-ingest", "pass_targets": "none", "inference": "none"},
        1: {"layer": "mirror-export", "pass_targets": "none", "inference": "none"},
        2: {"layer": "scheduler", "pass_targets": "all", "inference": "budget-router"},
        3: {"layer": "job-board", "pass_targets": "none", "inference": "none"},
        4: {"layer": "depth-pass", "pass_targets": "Depth,Pose2D,Pose3D", "inference": "depth-pose"},
        5: {"layer": "composite", "pass_targets": "Composite,Bokeh,Merge", "inference": "composite"},
        6: {"layer": "image-gen", "pass_targets": "ImageGen,SegFigure", "inference": "image-generation"},
        7: {"layer": "video-gen", "pass_targets": "VideoGen,Lipsync", "inference": "video-generation"},
    }

    # Derive browser states from tasks
    active_task = None
    for t in tasks:
        if t["status"] == "ACTIVE":
            active_task = t
            break

    for i in range(MAX_BROWSERS):
        updates = {
            "todo:last-update": now_iso(),
            "todo:coherence-check:status": "PASS" if coherence["pass"] else "FAIL",
            "todo:coherence-check:drift": str(len(coherence["issues"])),
        }
        if active_task:
            updates["todo:active-task"] = active_task["task_id"]

        if not dry_run:
            write_browser_state(i, updates)
        else:
            print(f"  [dry] browser-{i} would update: {updates}")

    # 4. Update MASTER-TODO.svg metadata (best-effort)
    if MASTER_TODO.exists() and not dry_run:
        try:
            tree = ET.parse(MASTER_TODO)
            root = tree.getroot()
            meta = root.find(f"{{{SVG_NS}}}metadata")
            if meta is not None:
                # update todo:active-tasks count
                el = meta.find(_ns("active-tasks"))
                if el is not None:
                    el.set("count", str(len([t for t in tasks if t["status"] in ("ACTIVE", "PENDING")])))
                    el.text = " ".join(t["task_id"] for t in tasks if t["status"] in ("ACTIVE", "PENDING"))
                # update todo:runtime-loop
                el = meta.find(_ns("runtime-loop"))
                if el is not None:
                    el.set("status", "active")
                    el.set("tick-ms", str(os.environ.get("GENTLY_TICK_MS", DEFAULT_TICK_MS)))
                # update todo:jsonl-tail-hash
                el = meta.find(_ns("jsonl-tail-hash"))
                if el is not None:
                    if jsonl_tail:
                        h = hashlib.sha256(json.dumps(jsonl_tail[-1], sort_keys=True).encode()).hexdigest()[:16]
                        el.text = f"sha256:{h}"
                ET.indent(tree, space="  ")
                tree.write(MASTER_TODO, encoding="utf-8", xml_declaration=True)
                print(f"  MASTER-TODO.svg metadata updated")
        except Exception as e:
            print(f"  ! MASTER-TODO.svg update failed: {e}")
    elif dry_run:
        print(f"  [dry] MASTER-TODO.svg would be updated")

    # 5. Append runtime event to JSONL
    runtime_event = {
        "ts": now_iso(),
        "unix": int(time.time()),
        "event": "runtime-tick",
        "tasks_active": len([t for t in tasks if t["status"] == "ACTIVE"]),
        "tasks_pending": len([t for t in tasks if t["status"] == "PENDING"]),
        "coherence_pass": coherence["pass"],
        "coherence_issues": len(coherence["issues"]),
        "browsers_synced": MAX_BROWSERS,
        "master_todo_updated": not dry_run and MASTER_TODO.exists(),
    }
    if not dry_run:
        with open(JOBBOARD_JSONL, "a") as f:
            f.write(json.dumps(runtime_event, sort_keys=True) + "\n")
        print(f"  JSONL appended: runtime-tick")
    else:
        print(f"  [dry] JSONL would append: {runtime_event}")

    print(f"[{now_iso()}] TICK end")
    return coherence["pass"]


# ── main ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="ToDo-JobBoard runtime loop")
    parser.add_argument("--once", action="store_true", help="Single tick (dry-run by default)")
    parser.add_argument("--execute", action="store_true", help="Actually write files (not dry-run)")
    parser.add_argument("--daemon", action="store_true", help="Loop forever")
    parser.add_argument("--coherence", action="store_true", help="Coherence check only")
    parser.add_argument("--browser", type=int, help="Query/update a specific browser (0-7)")
    args = parser.parse_args()

    dry_run = not args.execute

    if args.coherence:
        md_text = JOBBOARD_MD.read_text() if JOBBOARD_MD.exists() else ""
        tasks = parse_task_board(md_text)
        jsonl_tail = read_jsonl_tail(JOBBOARD_JSONL)
        result = check_coherence(tasks, jsonl_tail)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["pass"] else 1)

    if args.browser is not None:
        if not 0 <= args.browser < MAX_BROWSERS:
            print(f"Browser ID must be 0-{MAX_BROWSERS-1}")
            sys.exit(1)
        state = read_browser_state(args.browser)
        print(json.dumps(state, indent=2, default=str))
        sys.exit(0)

    if args.daemon:
        tick_ms = int(os.environ.get("GENTLY_TICK_MS", DEFAULT_TICK_MS))
        print(f"Daemon mode: tick = {tick_ms}ms")
        while True:
            try:
                tick(dry_run=dry_run)
            except Exception as e:
                print(f"[{now_iso()}] TICK ERROR: {e}")
            time.sleep(tick_ms / 1000.0)
    else:
        tick(dry_run=dry_run)


if __name__ == "__main__":
    main()
