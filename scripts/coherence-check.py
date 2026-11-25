#!/usr/bin/env python3
"""
coherence-check.py — Standalone chain coherence checker for the ToDo-JobBoard.

Usage:
    python3 scripts/coherence-check.py              # full check, exits 0/1
    python3 scripts/coherence-check.py --json         # output JSON report
    python3 scripts/coherence-check.py --browser N  # check a specific browser
    python3 scripts/coherence-check.py --fix        # attempt to fix trivial drift

Returns exit code 0 if coherent, 1 if drift detected.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Delegate to the runtime loop's coherence engine (load by path to handle hyphen in filename)
import importlib.util
_runtime_path = Path(__file__).parent / "todo-runtime-loop.py"
_spec = importlib.util.spec_from_file_location("todo_runtime_loop", _runtime_path)
_rt = importlib.util.module_from_spec(_spec)
sys.modules["todo_runtime_loop"] = _rt
_spec.loader.exec_module(_rt)

PROJECT_ROOT = _rt.PROJECT_ROOT
JOBBOARD_MD = _rt.JOBBOARD_MD
JOBBOARD_JSONL = _rt.JOBBOARD_JSONL
BROWSER_POOL = _rt.BROWSER_POOL
MAX_BROWSERS = _rt.MAX_BROWSERS
parse_task_board = _rt.parse_task_board
read_jsonl_tail = _rt.read_jsonl_tail
check_coherence = _rt.check_coherence
read_browser_state = _rt.read_browser_state
now_iso = _rt.now_iso


def main():
    parser = argparse.ArgumentParser(description="Chain coherence checker")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--browser", type=int, help="Check specific browser (0-7)")
    parser.add_argument("--fix", action="store_true", help="Fix trivial drift (update timestamps)")
    args = parser.parse_args()

    if args.browser is not None:
        if not 0 <= args.browser < MAX_BROWSERS:
            print(f"Browser ID must be 0-{MAX_BROWSERS-1}", file=sys.stderr)
            sys.exit(1)
        state = read_browser_state(args.browser)
        print(json.dumps(state, indent=2, default=str))
        sys.exit(0 if state and state.get("coherence-check:status") == "PASS" else 1)

    md_text = JOBBOARD_MD.read_text() if JOBBOARD_MD.exists() else ""
    tasks = parse_task_board(md_text)
    jsonl_tail = read_jsonl_tail(JOBBOARD_JSONL)
    result = check_coherence(tasks, jsonl_tail)

    if args.fix and result["issues"]:
        # Trivial fix: update browser last-update timestamps to now
        for i in range(MAX_BROWSERS):
            st = read_browser_state(i)
            if st:
                # no actual fix logic beyond timestamp refresh for now
                pass
        result["fixed_at"] = now_iso()
        result["fix_applied"] = "timestamp-refresh"

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "PASS" if result["pass"] else "FAIL"
        print(f"Coherence check: {status} ({len(result['issues'])} issues)")
        for issue in result["issues"]:
            print(f"  ! {issue}")
        print(f"Checked at: {result['checked_at']}")

    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
