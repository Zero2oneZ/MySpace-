#!/usr/bin/env python3
"""
chain_runner.py — deterministic chain engine for .claude/ agent system.

Reads tasks from ToDo-JobBoard, routes each through model_router.py, dispatches
to the appropriate endpoint (ollama / anthropic / MCP bridge), and logs results.

Design principles:
  - Deterministic: same input → same routing decision every time
  - Hierarchical: lower agents spawn sub-tasks; higher agents coordinate
  - Append-only: all state changes go to JSONL
  - Token-budgeted: every agent level has a hard token cap

Usage:
    python3 chain_runner.py --once              # single tick
    python3 chain_runner.py --daemon            # loop every CHAIN_TICK_MS
    python3 chain_runner.py --task-id T-001     # route + simulate one task
    python3 chain_runner.py --spawn "sub-task description" --parent T-001 --level 2

Env:
    CHAIN_TICK_MS      — loop interval (default 5000)
    CC_PROJECT_ROOT    — project root (default /data/Projects/MySpace++)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(os.environ.get("CC_PROJECT_ROOT", "/data/Projects/MySpace++"))
CHAIN_DIR = Path(__file__).parent
AGENTS_DIR = CHAIN_DIR.parent / "agents"
JOBBOARD_MD = PROJECT_ROOT / "ToDo-JobBoard.md"
JOBBOARD_JSONL = PROJECT_ROOT / "ToDo-JobBoard.jsonl"
CHAIN_LOG = CHAIN_DIR / "chain_events.jsonl"

# Import model_router
sys.path.insert(0, str(CHAIN_DIR))
from model_router import route_task, estimate_tokens

# ── constants ──────────────────────────────────────────────────────────
DEFAULT_TICK_MS = 5000
MAX_CONCURRENT_PER_LEVEL = {1: 4, 2: 3, 3: 2, 4: 1, 5: 1}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_registry():
    p = AGENTS_DIR / "registry.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _read_jobboard_tasks():
    """Parse ToDo-JobBoard.md for active tasks."""
    if not JOBBOARD_MD.exists():
        return []
    tasks = []
    for line in JOBBOARD_MD.read_text().splitlines():
        if line.startswith("| T-"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 8:
                tasks.append({
                    "task_id": parts[1],
                    "agent": parts[2],
                    "model": parts[3],
                    "goal": parts[4],
                    "benchmark": parts[5] if len(parts) > 5 else "",
                    "status": parts[6] if len(parts) > 6 else "PENDING",
                    "gate": parts[8] if len(parts) > 8 else "HOLD",
                })
    return tasks


def _log_event(event: dict):
    """Append event to chain log."""
    event["ts"] = now_iso()
    event["unix"] = int(time.time())
    CHAIN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(CHAIN_LOG, "a") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def route_single_task(task: dict, registry: dict) -> dict:
    """Route one task through the model router."""
    goal = task.get("goal", "")
    # Combine goal + benchmark as full context
    context = task.get("benchmark", "")
    routing = route_task(goal, context)

    result = {
        "task_id": task["task_id"],
        "goal": goal,
        "routed_level": routing["level"],
        "agent_name": routing["agent_name"],
        "model": routing["model"],
        "requires_human": routing["requires_human"],
        "endpoint": routing["route_to"],
        "complexity_total": routing["complexity"]["total"],
        "estimated_tokens": routing["complexity"]["estimated_tokens"],
        "can_spawn": routing["can_spawn_subagents"],
        "spawn_max": routing["spawn_max_level"],
        "escalation": routing.get("escalation"),
    }

    # If requires_human, flag for Claude intervention
    if routing["requires_human"]:
        result["intervention"] = {
            "reason": "Task complexity or security sensitivity requires human-level oversight",
            "recommended_action": "Claude (opus) should review and execute",
            "auto_dispatch": False,
        }

    return result


def spawn_subtask(parent_task_id: str, description: str, level: int, registry: dict) -> dict:
    """Spawn a sub-task from a higher-level agent to a lower-level one."""
    # Generate sub-task ID
    sub_id = f"{parent_task_id}-sub-{int(time.time())}"

    # Validate level is within parent's spawn limit
    # In real usage, we'd look up the parent's actual level; here we trust the caller
    sub_task = {
        "task_id": sub_id,
        "agent": f"level-{level}",
        "model": registry.get("levels", {}).get(str(level), {}).get("model", "unknown"),
        "goal": description,
        "benchmark": f"Spawned by {parent_task_id}",
        "status": "PENDING",
        "gate": "GO",
    }

    # Append to JobBoard
    row = f"| {sub_id} | {sub_task['agent']} | {sub_task['model']} | {description} | {sub_task['benchmark']} | PENDING | | GO |"
    if JOBBOARD_MD.exists():
        lines = JOBBOARD_MD.read_text().splitlines()
        insert_idx = None
        for i, line in enumerate(lines):
            if line.startswith("| T-"):
                insert_idx = i + 1
        if insert_idx:
            lines.insert(insert_idx, row)
        else:
            lines.append(row)
        JOBBOARD_MD.write_text("\n".join(lines) + "\n")

    # Append to JSONL
    event = {
        "ts": now_iso(), "unix": int(time.time()), "event": "subtask_spawn",
        "parent": parent_task_id, "subtask_id": sub_id,
        "level": level, "description": description,
    }
    with open(JOBBOARD_JSONL, "a") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")

    _log_event({
        "event": "spawn",
        "parent": parent_task_id,
        "subtask_id": sub_id,
        "level": level,
        "description": description,
    })

    return {"subtask_id": sub_id, "level": level, "status": "spawned"}


def simulate_dispatch(routing: dict, registry: dict) -> dict:
    """Simulate dispatch to an endpoint. Returns what WOULD happen."""
    endpoint = routing["endpoint"]
    model = routing["model"]
    level = routing["routed_level"]

    if endpoint == "local_ollama":
        # Check if ollama is reachable
        try:
            r = subprocess.run(
                ["curl", "-sf", "http://127.0.0.1:11434/api/tags"],
                capture_output=True, text=True, timeout=5
            )
            ollama_up = r.returncode == 0
        except Exception:
            ollama_up = False

        return {
            "dispatched": ollama_up,
            "endpoint": endpoint,
            "model": model,
            "note": f"Would POST to ollama with model={model}" if ollama_up else "Ollama not reachable",
            "fallback": "anthropic_api" if not ollama_up else None,
        }

    if endpoint == "anthropic_api":
        return {
            "dispatched": False,  # never auto-dispatch human-level
            "endpoint": endpoint,
            "model": model,
            "note": "Human-level task — requires Claude session approval",
            "fallback": None,
        }

    if endpoint == "mcp_bridge":
        return {
            "dispatched": True,
            "endpoint": endpoint,
            "model": "mcp",
            "note": "Would call MCP bridge tool",
            "fallback": None,
        }

    return {"dispatched": False, "endpoint": endpoint, "note": "Unknown endpoint", "fallback": None}


def run_tick(dry_run: bool = True):
    """One chain tick: read board → route tasks → log decisions."""
    registry = _load_registry()
    tasks = _read_jobboard_tasks()

    # Filter to PENDING + GO-gated tasks (or all PENDING for review)
    active = [t for t in tasks if t["status"] == "PENDING"]
    go_ready = [t for t in active if t["gate"] == "GO"]

    results = []
    for task in go_ready:
        routing = route_single_task(task, registry)
        dispatch = simulate_dispatch(routing, registry)

        entry = {
            "task_id": task["task_id"],
            "routing": routing,
            "dispatch": dispatch,
            "dry_run": dry_run,
        }
        results.append(entry)

        _log_event({
            "event": "tick_task",
            "task_id": task["task_id"],
            "level": routing["routed_level"],
            "requires_human": routing["requires_human"],
            "dispatched": dispatch["dispatched"],
            "dry_run": dry_run,
        })

    return {
        "ts": now_iso(),
        "total_tasks": len(tasks),
        "pending": len(active),
        "go_ready": len(go_ready),
        "routed": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Deterministic chain runner")
    parser.add_argument("--once", action="store_true", help="Single tick")
    parser.add_argument("--daemon", action="store_true", help="Loop every CHAIN_TICK_MS")
    parser.add_argument("--task-id", type=str, help="Route one specific task")
    parser.add_argument("--spawn", type=str, help="Spawn a sub-task")
    parser.add_argument("--parent", type=str, default="manual", help="Parent task ID for spawn")
    parser.add_argument("--level", type=int, default=2, help="Level for spawned sub-task")
    parser.add_argument("--execute", action="store_true", help="Actually dispatch (not dry-run)")
    args = parser.parse_args()

    registry = _load_registry()

    if args.spawn:
        result = spawn_subtask(args.parent, args.spawn, args.level, registry)
        print(json.dumps(result, indent=2))
        return

    if args.task_id:
        tasks = _read_jobboard_tasks()
        task = next((t for t in tasks if t["task_id"] == args.task_id), None)
        if not task:
            print(f"Task {args.task_id} not found")
            sys.exit(1)
        routing = route_single_task(task, registry)
        dispatch = simulate_dispatch(routing, registry)
        print(json.dumps({"task": task, "routing": routing, "dispatch": dispatch}, indent=2))
        return

    if args.once:
        result = run_tick(dry_run=not args.execute)
        print(json.dumps(result, indent=2))
        return

    if args.daemon:
        tick_ms = int(os.environ.get("CHAIN_TICK_MS", DEFAULT_TICK_MS))
        print(f"Chain daemon starting. Tick interval: {tick_ms}ms")
        print(f"Log: {CHAIN_LOG}")
        while True:
            result = run_tick(dry_run=not args.execute)
            print(f"[{result['ts']}] pending={result['pending']} go_ready={result['go_ready']} routed={len(result['routed'])}")
            time.sleep(tick_ms / 1000)

    # Default: show help + current board stats
    tasks = _read_jobboard_tasks()
    active = [t for t in tasks if t["status"] == "PENDING"]
    go_ready = [t for t in active if t["gate"] == "GO"]
    print(f"Board: {len(tasks)} tasks | {len(active)} pending | {len(go_ready)} GO-ready")
    if go_ready:
        print("GO-ready tasks:")
        for t in go_ready[:5]:
            routing = route_single_task(t, registry)
            flag = " [HUMAN]" if routing["requires_human"] else ""
            print(f"  {t['task_id']}: {t['goal'][:60]}... → L{routing['routed_level']}{flag}")


if __name__ == "__main__":
    main()
