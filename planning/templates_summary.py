#!/usr/bin/env python3
"""templates_summary.py — emits planning/TEMPLATES.md from the 53
Claude-authored workflow_templates rows. Companion to DAG.md (which
covers per-opcode interface design) and DAG_CROSS.md (successor
predictions).

Per template: name, primary opcode, step list, branch / HITL flags,
fallback model groups, output modalities. Grouped by HF category.

Run:
    python3 planning/templates_summary.py > planning/TEMPLATES.md
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAXONOMY_PATH = HERE / "hf_task_evolution.jsonl"
DB_PATH = (os.environ.get("CC_DB")
           or os.environ.get("CC_GLOBAL_DB")
           or str(Path.home() / ".cc" / "cc.db"))

CATEGORY_ORDER = [
    "Multimodal",
    "Computer Vision",
    "Natural Language Processing",
    "Audio",
    "Tabular",
    "Reinforcement Learning",
    "Other",
]


def load_taxonomy() -> dict[str, dict]:
    out = {}
    for line in TAXONOMY_PATH.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["task"]] = r
    return out


def load_templates() -> list[dict]:
    c = sqlite3.connect(DB_PATH)
    try:
        rows = c.execute(
            "SELECT name, primary_opcode, description, tags, "
            "       template_json, authored_by, created_at, use_count "
            "FROM workflow_templates ORDER BY primary_opcode"
        ).fetchall()
    finally:
        c.close()
    out = []
    for name, op, desc, tags, blob, by, ts, used in rows:
        try:
            tpl = json.loads(blob)
        except json.JSONDecodeError:
            tpl = {}
        out.append({
            "name": name,
            "primary_opcode": op,
            "description": desc,
            "tags": tags or "",
            "template": tpl,
            "authored_by": by,
            "created_at": ts,
            "use_count": used,
        })
    return out


def render_template(t: dict, tax: dict[str, dict]) -> str:
    out: list[str] = []
    name = t["name"]
    op = t["primary_opcode"]
    desc = t["description"]
    tpl = t["template"]
    steps = tpl.get("steps") or []
    preconditions = tpl.get("preconditions") or []
    fallbacks = tpl.get("fallbacks") or {}
    outputs = tpl.get("outputs") or []

    n_steps = len(steps)
    n_branches = sum(1 for s in steps if s.get("opcode") == "__BRANCH__")
    n_hitl = sum(1 for s in steps
                 if s.get("human_checkpoint") not in (None, "null"))

    out.append(f"### `{name}`")
    out.append("")
    flags = []
    if n_branches:
        flags.append(f"**{n_branches} branch{'es' if n_branches != 1 else ''}**")
    if n_hitl:
        flags.append(f"**{n_hitl} HITL**")
    flag_str = "  ·  " + "  ·  ".join(flags) if flags else ""
    out.append(f"_primary opcode: `{op}`_   ·   {n_steps} step(s){flag_str}")
    out.append("")
    if t.get("tags"):
        out.append(f"_tags:_ `{t['tags']}`")
        out.append("")
    out.append(desc)
    out.append("")

    # Steps
    out.append("**Steps:**")
    out.append("")
    for s in steps:
        idx = s.get("idx", "?")
        sop = s.get("opcode", "?")
        purp = s.get("purpose", "")
        if sop == "__BRANCH__":
            bo = s.get("branch_on", "?")
            branches = s.get("branches") or {}
            preds = list(branches.keys())
            out.append(f"  {idx}. **`__BRANCH__`** on `{bo}` → "
                       f"{', '.join(f'`{p}`' for p in preds)}")
            for pred, action in branches.items():
                goto = action.get("goto") if isinstance(action, dict) else None
                retries = action.get("max_retries") if isinstance(action, dict) else None
                mut = action.get("mutate") if isinstance(action, dict) else None
                detail = f"goto={goto}"
                if retries:
                    detail += f", max_retries={retries}"
                if mut:
                    detail += f", mutate: {mut[:70]}"
                out.append(f"     - `{pred}` → {detail}")
            if purp:
                out.append(f"     _{purp[:120]}_")
        else:
            hitl_mark = " 🟧 **HITL**" if s.get("human_checkpoint") not in (None, "null") else ""
            out.append(f"  {idx}. `{sop}`{hitl_mark}")
            if purp:
                out.append(f"     _{purp[:120]}_")
            cands = s.get("model_candidates") or []
            if cands:
                out.append(f"     candidates: " +
                           ", ".join(f"`{c}`" for c in cands[:5]))
            hc = s.get("human_checkpoint")
            if isinstance(hc, dict):
                out.append(f"     checkpoint: type=`{hc.get('type','?')}`  "
                           f"prompt: \"{hc.get('prompt','')[:80]}\"")
    out.append("")

    # Preconditions
    if preconditions:
        out.append(f"**Preconditions ({len(preconditions)}):**")
        for p in preconditions:
            if isinstance(p, dict):
                out.append(f"  - `{p.get('check','?')}` = `{p.get('value')}`")
        out.append("")

    # Fallbacks
    if fallbacks:
        out.append(f"**Fallbacks:**")
        for k, v in fallbacks.items():
            if isinstance(v, list):
                out.append(f"  - `{k}`: " + ", ".join(f"`{x}`" for x in v))
        out.append("")

    # Outputs
    if outputs:
        out.append(f"**Outputs:**")
        for o in outputs:
            if isinstance(o, dict):
                out.append(f"  - `{o.get('name','?')}` "
                           f"(`{o.get('modality','?')}`)")
        out.append("")

    return "\n".join(out)


HEADER = """\
# TEMPLATES.md — Claude-authored workflow library

> Companion to `DAG.md` (per-opcode interface design) and
> `DAG_CROSS.md` (successor predictions). This doc lists the 53
> rich workflow templates Claude authored against the seeded library
> (`capability_cards` + `gui_cards` + `path_builder` chains). Each
> template is a reusable recipe for one primary opcode, with multi-
> step orchestration, branch retry loops, optional HITL approval
> gates, and fallback model lists.
>
> Regenerate with:
> ```
> python3 planning/templates_summary.py > planning/TEMPLATES.md
> ```

## Library stats

"""


def emit() -> str:
    tax = load_taxonomy()
    tpls = load_templates()
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for t in tpls:
        cat = tax.get(t["primary_opcode"], {}).get("category", "Other")
        by_cat[cat].append(t)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda x: x["primary_opcode"])

    # Aggregate stats
    total = len(tpls)
    n_branches = sum(
        1 for t in tpls
        if any(s.get("opcode") == "__BRANCH__"
               for s in (t["template"].get("steps") or []))
    )
    n_hitl = sum(
        1 for t in tpls
        if any(s.get("human_checkpoint") not in (None, "null")
               for s in (t["template"].get("steps") or []))
    )
    n_fb = sum(1 for t in tpls if t["template"].get("fallbacks"))
    step_counts = [len(t["template"].get("steps") or []) for t in tpls]
    avg_steps = round(sum(step_counts) / max(1, total), 1)
    total_steps = sum(step_counts)
    total_branches = sum(
        sum(1 for s in (t["template"].get("steps") or [])
            if s.get("opcode") == "__BRANCH__")
        for t in tpls
    )

    out: list[str] = [HEADER]
    out.append(f"- **Templates:** {total} (one per opcode)")
    out.append(f"- **With `__BRANCH__` retry loops:** {n_branches} "
               f"({round(100*n_branches/total)}%)")
    out.append(f"- **With HITL approval gates:** {n_hitl} "
               f"({round(100*n_hitl/total)}%)")
    out.append(f"- **With fallback model lists:** {n_fb} "
               f"({round(100*n_fb/total)}%)")
    out.append(f"- **Average steps per template:** {avg_steps}")
    out.append(f"- **Total steps across library:** {total_steps}")
    out.append(f"- **Total branch nodes:** {total_branches}")
    out.append("")
    out.append("## Step-count distribution")
    out.append("")
    out.append("| Steps | Templates |")
    out.append("|---|---|")
    from collections import Counter
    for n, count in sorted(Counter(step_counts).items()):
        bar = "█" * count
        out.append(f"| {n} | {bar} {count} |")
    out.append("")
    out.append("---")
    out.append("")

    # Table of contents
    out.append("## Templates by HF category")
    out.append("")
    for cat in CATEGORY_ORDER:
        rows = by_cat.get(cat, [])
        if not rows:
            continue
        out.append(f"- **{cat}** ({len(rows)}): " +
                   ", ".join(f"[`{t['name']}`](#{t['name']})"
                             for t in rows))
    out.append("")
    out.append("---")
    out.append("")

    # Per-category details
    for cat in CATEGORY_ORDER:
        rows = by_cat.get(cat, [])
        if not rows:
            continue
        out.append(f"## {cat}  ({len(rows)} templates)")
        out.append("")
        for t in rows:
            out.append(render_template(t, tax))
        out.append("---")
        out.append("")

    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.write(emit())
