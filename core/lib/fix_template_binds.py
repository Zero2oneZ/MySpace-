#!/usr/bin/env python3
"""fix_template_binds.py — repair the Claude-template terminal-bind bug.

Claude's workflow_templates frequently end with a "sink" / "emit final"
step whose binds reference the original `$input_X` user inputs instead
of the upstream processed output. The walker exposed this in 3 of 3
templates spot-checked. This script scans all 53 templates and fixes
the same class of bug deterministically.

Rule:
  For each template's LAST non-`__BRANCH__` step:
    for each bind slot whose value is `$input_<modality>`:
      look upstream (most recent first) for a non-`__BRANCH__` step
      whose output modality matches the slot's modality (case-fold).
      If found, rewrite the bind to `$<that_step.out>`.

Conservative — only touches the final step. Doesn't touch intermediate
steps even if they have similar issues (those are usually intentional,
e.g. the second lipsync step legitimately re-reads the original audio
for the actual lipsync render).

Run:
    fix_template_binds.py            # dry-run by default (preview)
    fix_template_binds.py --apply    # actually write changes
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

DB_PATH = (os.environ.get("CC_DB")
           or os.environ.get("CC_GLOBAL_DB")
           or str(Path.home() / ".cc" / "cc.db"))


def db() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def opcode_outputs(c: sqlite3.Connection, opcode: str) -> list[str]:
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


def repair_template(tpl: dict, c: sqlite3.Connection
                    ) -> tuple[bool, list[str]]:
    """Mutate tpl in place. Returns (changed, change_log)."""
    steps = tpl.get("steps") or []
    if not steps:
        return False, []

    # Build history of non-BRANCH steps with their output modalities
    history: list[dict] = []
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        if s.get("opcode") == "__BRANCH__":
            continue
        out_var = s.get("out") or f"step_{i}_out"
        outs = opcode_outputs(c, s.get("opcode") or "")
        history.append({
            "step_idx": i, "out": out_var, "outputs": outs,
        })

    if len(history) < 2:
        # Single-step or empty — nothing to repair.
        return False, []

    last_h = history[-1]
    last_step = steps[last_h["step_idx"]]
    binds = last_step.get("binds")
    if not isinstance(binds, dict):
        return False, []

    changed = False
    log: list[str] = []
    upstream = history[:-1]

    for slot, src in list(binds.items()):
        if not isinstance(src, str) or not src.startswith("$input_"):
            continue
        slot_mod_upper = slot.upper()
        # Find most recent upstream step whose outputs include this slot's
        # modality. Iterate reverse so we get the freshest source.
        chosen = None
        for h in reversed(upstream):
            if slot_mod_upper in [m.upper() for m in h["outputs"]]:
                chosen = h
                break
        if chosen is None:
            # Couldn't find a matching upstream output — leave bind alone.
            continue
        new_src = f"${chosen['out']}"
        if new_src == src:
            continue
        binds[slot] = new_src
        changed = True
        log.append(
            f"step {last_h['step_idx']} bind `{slot}`: "
            f"`{src}` → `{new_src}` "
            f"(from step {chosen['step_idx']} out)"
        )

    return changed, log


TERMINAL_PASS_KEYWORDS = (
    "sink", "final", "emit", "passthrough", "pass-through", "pass through",
    "finalize", "finalization", "approval", "deliver", "package",
    "no-op", "no re-inference", "no reinference",
    "anchor", "canonicalization", "consolidated", "stable",
    # Approval-flavored synonyms — added 2026-05-26 after rlhf template:
    "confirm", "promote", "promotion", "ready", "ship", "release",
    "publish", "accept",
)


def repair_passthrough(tpl: dict, c: sqlite3.Connection
                       ) -> tuple[bool, list[str]]:
    """Detect "terminal redundant opcode" pattern + rewrite to the
    synthetic `__PASSTHROUGH__` opcode (parallel to `__BRANCH__`).

    Pattern:
      - Last non-BRANCH step uses an opcode that ALSO appeared earlier
      - The step's `purpose` mentions sink/final/passthrough/emit/etc.
      - The step's binds reference at least one `$input_*` variable

    Rewrite:
      - opcode → `__PASSTHROUGH__`
      - binds → single `{"value": "$<latest_upstream_out>"}`
      - keep `human_checkpoint` if present (HITL pause still applies)
      - keep `out` so downstream still resolves
    """
    steps = tpl.get("steps") or []
    if not steps:
        return False, []

    non_br = [(i, s) for i, s in enumerate(steps)
              if isinstance(s, dict) and s.get("opcode") != "__BRANCH__"]
    if len(non_br) < 2:
        return False, []
    last_idx, last_step = non_br[-1]
    earlier_ops = {s.get("opcode") for _, s in non_br[:-1]}
    purpose = (last_step.get("purpose") or "").lower()
    last_op = last_step.get("opcode")

    if last_op not in earlier_ops:
        return False, []
    binds = last_step.get("binds") or {}
    has_input_bind = any(isinstance(v, str) and v.startswith("$input_")
                         for v in binds.values())
    if not has_input_bind:
        return False, []
    # Trigger conditions (either is enough):
    #   1. purpose contains a known passthrough keyword
    #   2. step has a human_checkpoint (HITL approval gate — running the
    #      opcode again would be wasted compute since the artifact already
    #      exists upstream)
    has_hitl = isinstance(last_step.get("human_checkpoint"), dict)
    keyword_hit = any(k in purpose for k in TERMINAL_PASS_KEYWORDS)
    if not (keyword_hit or has_hitl):
        return False, []

    # Choose the upstream `out` to pass through. Three-pass cascade:
    #   1. Match this step's OWN output modality (best — picks the
    #      same kind of artifact we'd have produced)
    #   2. Match any content-shaped modality (avoids picking a control
    #      label when a real artifact is available)
    #   3. Most recent (fallback if no content modality found)
    CONTENT_MODS = {"VIDEO", "IMAGE", "AUDIO", "TEXT", "3D", "DOC",
                    "MASK", "TIMESERIES", "TABULAR", "EMBEDDING",
                    "ACTION", "KEYPOINTS", "BOXES", "DEPTH_MAP", "GRAPH"}
    this_outs = [m.upper() for m in opcode_outputs(c, last_op or "")]
    this_mod = this_outs[0] if this_outs else None

    upstream_out = None
    # Pass 1: match THIS step's output modality
    if this_mod:
        for prev_idx, prev_step in reversed(non_br[:-1]):
            outs = [m.upper() for m
                    in opcode_outputs(c, prev_step.get("opcode") or "")]
            if this_mod in outs:
                upstream_out = prev_step.get("out") or f"step_{prev_idx}_out"
                break
    # Pass 2: content modality
    if not upstream_out:
        for prev_idx, prev_step in reversed(non_br[:-1]):
            outs = [m.upper() for m
                    in opcode_outputs(c, prev_step.get("opcode") or "")]
            if any(m in CONTENT_MODS for m in outs):
                upstream_out = prev_step.get("out") or f"step_{prev_idx}_out"
                break
    # Pass 3: most recent
    if not upstream_out:
        for prev_idx, prev_step in reversed(non_br[:-1]):
            upstream_out = prev_step.get("out") or f"step_{prev_idx}_out"
            break
    if not upstream_out:
        return False, []

    old_op = last_op
    old_binds = json.dumps(binds, sort_keys=True)
    last_step["opcode"] = "__PASSTHROUGH__"
    last_step["binds"] = {"value": f"${upstream_out}"}
    # Keep model_candidates removed (irrelevant for passthrough)
    last_step.pop("model_candidates", None)

    log = [
        f"step {last_idx} opcode: `{old_op}` → `__PASSTHROUGH__`",
        f"step {last_idx} binds: `{old_binds}` → `{{\"value\": \"${upstream_out}\"}}`",
    ]
    return True, log


def main():
    ap = argparse.ArgumentParser(prog="fix_template_binds.py")
    ap.add_argument("--apply", action="store_true",
                    help="actually persist changes (default: dry-run preview)")
    ap.add_argument("--name", default=None,
                    help="repair only this template (default: all)")
    ap.add_argument("--mode", choices=["binds", "passthrough", "both"],
                    default="both",
                    help="`binds` = rewrite $input_X→$step_N_out where slot "
                         "modality matches upstream output (conservative); "
                         "`passthrough` = detect terminal redundant opcodes + "
                         "rewrite to __PASSTHROUGH__; `both` runs both passes")
    args = ap.parse_args()

    n_repaired = 0
    n_unchanged = 0
    total_fixes = 0

    with db() as c:
        # Snapshot rows so the iterating cursor isn't disturbed by updates.
        if args.name:
            rows = c.execute(
                "SELECT name, template_json FROM workflow_templates "
                "WHERE name=?",
                (args.name,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT name, template_json FROM workflow_templates "
                "ORDER BY name"
            ).fetchall()

        for name, blob in rows:
            try:
                tpl = json.loads(blob)
            except json.JSONDecodeError as e:
                print(f"⚠ {name}: bad JSON, skipping ({e})", file=sys.stderr)
                continue
            total_log: list[str] = []
            any_changed = False
            if args.mode in ("binds", "both"):
                changed, log = repair_template(tpl, c)
                if changed:
                    any_changed = True
                    total_log.extend(log)
            if args.mode in ("passthrough", "both"):
                changed, log = repair_passthrough(tpl, c)
                if changed:
                    any_changed = True
                    total_log.extend(log)
            if not any_changed:
                n_unchanged += 1
                continue
            n_repaired += 1
            total_fixes += len(total_log)
            tag = "[APPLY]" if args.apply else "[dry-run]"
            print(f"{tag} {name}:")
            for line in total_log:
                print(f"    {line}")
            if args.apply:
                c.execute(
                    "UPDATE workflow_templates SET template_json=? "
                    "WHERE name=?",
                    (json.dumps(tpl), name),
                )

    print()
    print(f"scanned    : {n_repaired + n_unchanged} templates")
    print(f"repaired   : {n_repaired}  ({total_fixes} bind rewrites total)")
    print(f"unchanged  : {n_unchanged}")
    if not args.apply and n_repaired:
        print()
        print("→ run with --apply to persist these changes")


if __name__ == "__main__":
    main()
