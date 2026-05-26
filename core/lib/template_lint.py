#!/usr/bin/env python3
"""template_lint.py — broader template quality passes beyond bind fixes.

Four lint passes (each runnable independently or together):

  outputs   — auto-populate missing `outputs` top-level field by finding
              the terminal step's `out` variable. AUTO-FIXABLE.
  unique    — detect duplicate `out` var names across non-control steps.
              Read-only warning (rename suggestions printed).
  flow      — validate that every bind referencing `$step_X_out` matches
              the upstream step's declared output modality. Read-only.
  cycles    — detect __BRANCH__ steps that loop back without max_retries.
              Read-only warning.

Usage:
    template_lint.py outputs --apply    # auto-fix missing outputs
    template_lint.py unique             # report-only
    template_lint.py flow               # report-only
    template_lint.py cycles             # report-only
    template_lint.py all                # run all four
    template_lint.py all --apply        # auto-fixes (outputs) + read-only checks
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

DB_PATH = (os.environ.get("CC_DB")
           or os.environ.get("CC_GLOBAL_DB")
           or str(Path.home() / ".cc" / "cc.db"))


def db() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def opcode_outputs(c: sqlite3.Connection, opcode: str) -> list[str]:
    if opcode in ("__BRANCH__", "__PASSTHROUGH__"):
        return []
    r = c.execute(
        "SELECT payload_json FROM dag_nodes "
        "WHERE node_kind='opcode' AND name=?",
        (opcode,),
    ).fetchone()
    if not r:
        return []
    try:
        return json.loads(r[0]).get("outputs", []) or []
    except json.JSONDecodeError:
        return []


def opcode_inputs(c: sqlite3.Connection, opcode: str) -> list[str]:
    if opcode in ("__BRANCH__", "__PASSTHROUGH__"):
        return []
    r = c.execute(
        "SELECT payload_json FROM dag_nodes "
        "WHERE node_kind='opcode' AND name=?",
        (opcode,),
    ).fetchone()
    if not r:
        return []
    try:
        return json.loads(r[0]).get("inputs", []) or []
    except json.JSONDecodeError:
        return []


def all_templates() -> list[tuple[str, dict]]:
    out = []
    with db() as c:
        for name, blob in c.execute(
            "SELECT name, template_json FROM workflow_templates ORDER BY name"
        ):
            try:
                tpl = json.loads(blob)
            except json.JSONDecodeError:
                continue
            out.append((name, tpl))
    return out


# ---- PASS A: outputs (auto-fix) ---------------------------------------

def check_outputs(name: str, tpl: dict) -> tuple[bool, str | None, dict | None]:
    """Returns (needs_fix, message, suggested_outputs).
    A template needs a top-level `outputs` field declaring the artifacts
    it returns. Auto-fix: pick the terminal step's `out` variable +
    declare its modality (from the opcode's outputs)."""
    existing = tpl.get("outputs")
    if existing and isinstance(existing, list) and len(existing) > 0:
        return False, None, None
    steps = tpl.get("steps") or []
    non_br = [s for s in steps if isinstance(s, dict)
              and s.get("opcode") not in ("__BRANCH__",)]
    if not non_br:
        return False, "no steps to derive outputs from", None
    last = non_br[-1]
    out_var = last.get("out")
    if not out_var:
        return False, "terminal step has no `out` var", None
    # Figure out modality. PASSTHROUGH carries the modality of its source.
    op = last.get("opcode")
    modality = None
    with db() as c:
        if op == "__PASSTHROUGH__":
            # Look for the bind's target var → find that var's producing step
            binds = last.get("binds") or {}
            src = binds.get("value", "")
            if src.startswith("$"):
                target_var = src[1:]
                for prev in steps:
                    if isinstance(prev, dict) and prev.get("out") == target_var:
                        prev_op = prev.get("opcode")
                        outs = opcode_outputs(c, prev_op)
                        if outs:
                            modality = outs[0]
                            break
        else:
            outs = opcode_outputs(c, op or "")
            if outs:
                modality = outs[0]
    suggested = [{"name": out_var, "modality": modality or "UNKNOWN"}]
    return True, f"missing `outputs` → suggest {suggested}", suggested


def apply_outputs(tpl: dict, suggested: list) -> None:
    tpl["outputs"] = suggested


# ---- PASS B: uniqueness (read-only) -----------------------------------

def check_uniqueness(name: str, tpl: dict) -> list[str]:
    steps = tpl.get("steps") or []
    out_vars = [s.get("out") for s in steps
                if isinstance(s, dict) and s.get("out")
                and s.get("opcode") not in ("__BRANCH__",)]
    counts = Counter(out_vars)
    dups = [v for v, n in counts.items() if n > 1]
    warns = []
    for d in dups:
        warns.append(f"duplicate `out` var: `{d}` (used by "
                     f"{counts[d]} steps — bind references are ambiguous)")
    return warns


# ---- PASS C: flow (read-only) -----------------------------------------

def _normalize_slot(slot: str) -> str:
    """Strip trailing numeric/underscore suffixes from slot names so
    `TEXT2` and `TEXT_2` normalize to `TEXT` for modality comparison."""
    import re
    return re.sub(r"[_]?\d+$", "", slot).upper()


def check_flow(name: str, tpl: dict) -> tuple[list[str], list[str]]:
    """Validate that for every bind `slot: $upstream_var`, the upstream
    step's output modality is compatible with the slot's expected
    modality (the slot name normalized → expected modality).

    Returns (hard_warns, soft_warns):
      hard: real type mismatch with no sub-field accessor
      soft: bind uses a `.field` accessor (Claude may be reaching into a
            structured output — the validator can't verify the sub-type)
    """
    hard: list[str] = []
    soft: list[str] = []
    steps = tpl.get("steps") or []
    # Build map: out_var -> producing-step opcode
    var_producer: dict[str, str] = {}
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("opcode") in ("__BRANCH__",):
            continue
        ov = s.get("out")
        if ov:
            var_producer[ov] = s.get("opcode") or ""
    with db() as c:
        for i, s in enumerate(steps):
            if not isinstance(s, dict):
                continue
            if s.get("opcode") in ("__BRANCH__", "__PASSTHROUGH__"):
                continue
            binds = s.get("binds") or {}
            for slot, src in binds.items():
                if not isinstance(src, str) or not src.startswith("$"):
                    continue
                src_inner = src[1:]
                has_subfield = "." in src_inner
                var = src_inner.split(".")[0]
                if var.startswith("input_"):
                    continue
                prev_op = var_producer.get(var)
                if not prev_op:
                    continue
                upstream_outs = [m.upper() for m
                                 in opcode_outputs(c, prev_op)]
                slot_mod = _normalize_slot(slot)
                if not upstream_outs:
                    continue
                if slot_mod in upstream_outs:
                    continue
                msg = (f"step {i} bind `{slot}={src}`: "
                       f"slot expects `{slot_mod}` but upstream "
                       f"`{prev_op}` outputs `{','.join(upstream_outs)}`")
                if has_subfield:
                    soft.append(msg + "  (sub-field accessor — may be intentional)")
                else:
                    hard.append(msg)
    return hard, soft


# ---- PASS D: cycles (read-only) ---------------------------------------

def fix_flow_hard(name: str, tpl: dict) -> tuple[bool, list[str]]:
    """For each hard flow mismatch (no sub-field accessor), find an
    upstream var whose modality matches the slot and rewrite. Prefer:
      1. `$input_<slot_mod>` if such an initial input exists
      2. Most-recent upstream `out` whose opcode outputs `slot_mod`
    Skips if no match found."""
    import re as _re
    steps = tpl.get("steps") or []
    var_producer: dict[str, str] = {}
    initial_inputs: set[str] = set()
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("opcode") in ("__BRANCH__",):
            continue
        ov = s.get("out")
        if ov:
            var_producer[ov] = s.get("opcode") or ""
        # Detect declared initial inputs
        for v in (s.get("binds") or {}).values():
            if isinstance(v, str) and v.startswith("$input_"):
                initial_inputs.add(v[1:])
    log: list[str] = []
    changed = False
    with db() as c:
        for i, s in enumerate(steps):
            if not isinstance(s, dict):
                continue
            if s.get("opcode") in ("__BRANCH__", "__PASSTHROUGH__"):
                continue
            binds = s.get("binds") or {}
            for slot, src in list(binds.items()):
                if not isinstance(src, str) or not src.startswith("$"):
                    continue
                src_inner = src[1:]
                if "." in src_inner:
                    continue   # sub-field — skip
                var = src_inner
                if var.startswith("input_"):
                    continue
                prev_op = var_producer.get(var)
                if not prev_op:
                    continue
                upstream_outs = [m.upper() for m
                                 in opcode_outputs(c, prev_op)]
                slot_mod = _re.sub(r"[_]?\d+$", "", slot).upper()
                if not upstream_outs or slot_mod in upstream_outs:
                    continue
                # MISMATCH — try to find a correct source.
                # 1. initial input with matching modality
                candidate = None
                want = f"input_{slot_mod.lower()}"
                if want in initial_inputs:
                    candidate = want
                # 2. most-recent upstream `out` with matching modality
                if not candidate:
                    for prev in reversed(steps[:i]):
                        if not isinstance(prev, dict):
                            continue
                        if prev.get("opcode") in ("__BRANCH__",):
                            continue
                        op = prev.get("opcode") or ""
                        prev_outs = [m.upper() for m in opcode_outputs(c, op)]
                        if op == "__PASSTHROUGH__":
                            # Passthrough carries its source modality; trust
                            # its `out` name as a generic candidate only if
                            # it looks like the right shape (heuristic: if
                            # the var name contains the slot modality)
                            pov = prev.get("out", "")
                            if slot_mod.lower() in pov.lower():
                                candidate = pov
                                break
                            continue
                        if slot_mod in prev_outs:
                            candidate = prev.get("out")
                            break
                if not candidate:
                    continue
                new_src = f"${candidate}"
                if new_src == src:
                    continue
                binds[slot] = new_src
                changed = True
                log.append(
                    f"step {i} bind `{slot}`: `{src}` → `{new_src}` "
                    f"(slot wants {slot_mod}; was bound to "
                    f"{prev_op}→{','.join(upstream_outs)})"
                )
    return changed, log


def check_cycles(name: str, tpl: dict) -> list[str]:
    """Detect __BRANCH__ steps whose branches `goto` a backward step
    (creates a loop) without a `max_retries` cap. These risk infinite
    execution at runtime."""
    warns = []
    steps = tpl.get("steps") or []
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        if s.get("opcode") != "__BRANCH__":
            continue
        branches = s.get("branches") or {}
        for pred, action in branches.items():
            if not isinstance(action, dict):
                continue
            goto = action.get("goto")
            if goto is None:
                continue
            if not isinstance(goto, int):
                continue
            # Backward goto = loop. Check for max_retries.
            if goto < i and "max_retries" not in action:
                warns.append(
                    f"step {i} branch `{pred}` → goto step {goto} "
                    f"(backward; no `max_retries` set — risks infinite loop)"
                )
    return warns


# ---- driver -----------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(prog="template_lint.py")
    ap.add_argument("mode", choices=["outputs", "unique", "flow",
                                      "flow-fix", "cycles", "all"])
    ap.add_argument("--apply", action="store_true",
                    help="persist auto-fixes (outputs + flow-fix)")
    ap.add_argument("--name", default=None,
                    help="lint only this template")
    args = ap.parse_args()

    tpls = all_templates()
    if args.name:
        tpls = [(n, t) for n, t in tpls if n == args.name]

    passes_to_run: list[str]
    if args.mode == "all":
        passes_to_run = ["outputs", "unique", "flow", "cycles"]
    else:
        passes_to_run = [args.mode]

    totals = {p: 0 for p in passes_to_run}
    output_fixes = 0
    flow_fixes = 0
    mutated_templates: set[str] = set()

    for name, tpl in tpls:
        tpl_lines: list[str] = []

        if "outputs" in passes_to_run:
            needs, msg, sug = check_outputs(name, tpl)
            if needs:
                tpl_lines.append(f"  [outputs] {msg}")
                totals["outputs"] += 1
                if args.apply:
                    apply_outputs(tpl, sug)
                    output_fixes += 1
                    mutated_templates.add(name)

        if "flow-fix" in passes_to_run:
            changed, log = fix_flow_hard(name, tpl)
            for w in log:
                tpl_lines.append(f"  [flow-fix] {w}")
            if changed:
                totals.setdefault("flow-fix", 0)
                totals["flow-fix"] += len(log)
                if args.apply:
                    flow_fixes += len(log)
                    mutated_templates.add(name)

        if "unique" in passes_to_run:
            warns = check_uniqueness(name, tpl)
            for w in warns:
                tpl_lines.append(f"  [unique]  {w}")
            totals["unique"] += len(warns)

        if "flow" in passes_to_run:
            hard, soft = check_flow(name, tpl)
            for w in hard:
                tpl_lines.append(f"  [flow!]   {w}")
            for w in soft:
                tpl_lines.append(f"  [flow~]   {w}")
            totals["flow"] += len(hard)
            totals.setdefault("flow_soft", 0)
            totals["flow_soft"] += len(soft)

        if "cycles" in passes_to_run:
            warns = check_cycles(name, tpl)
            for w in warns:
                tpl_lines.append(f"  [cycles]  {w}")
            totals["cycles"] += len(warns)

        if tpl_lines:
            print(f"\n{name}")
            for line in tpl_lines:
                print(line)

    if args.apply and mutated_templates:
        with db() as c:
            for name, tpl in tpls:
                if name not in mutated_templates:
                    continue
                c.execute(
                    "UPDATE workflow_templates SET template_json=? WHERE name=?",
                    (json.dumps(tpl), name),
                )

    print()
    print(f"═══ lint summary ═══")
    for p in passes_to_run:
        kind = "fixes applied" if (p == "outputs" and args.apply) else "warnings"
        if p == "flow":
            soft = totals.get("flow_soft", 0)
            print(f"  flow!       {totals[p]} hard warnings (real type mismatch)")
            print(f"  flow~       {soft} soft warnings (sub-field accessor — likely OK)")
        else:
            print(f"  {p:<10}  {totals[p]} {kind}")
    if not args.apply and totals.get("outputs", 0):
        print()
        print("→ run with --apply to persist the outputs auto-fixes")


if __name__ == "__main__":
    main()
