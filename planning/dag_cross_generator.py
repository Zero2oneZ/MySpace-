#!/usr/bin/env python3
"""dag_cross_generator.py — emits planning/DAG_CROSS.md

Takes the per-opcode GUI DAGs from DAG.md and asks: when the user
reaches the `✓ done` terminal node of an opcode's flow, WHICH OPCODES
can they continue into next? Predicts the top-5 successors per opcode
by matching output → input modalities, then ranking by:

  - recency (era 5+ Era-collapse models score higher)
  - layer (L3 / L5 compound tasks score higher)
  - pipeline-step continuity (opcode B is in step A+1 → +1.0 bonus)
  - Any-to-Any penalty (it trivially consumes everything; demote it)

Also renders a MODALITY FLOW LATTICE showing producer → consumer
graphs per primitive modality (TEXT, IMAGE, AUDIO, VIDEO, 3D, etc.).

Run:
    python3 planning/dag_cross_generator.py > planning/DAG_CROSS.md
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAXONOMY_PATH = HERE / "hf_task_evolution.jsonl"
PATH_BUILDER = HERE / "path_builder.py"
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


# ---- loaders -----------------------------------------------------------

def load_taxonomy() -> list[dict]:
    rows = []
    for line in TAXONOMY_PATH.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


# ---- ranking -----------------------------------------------------------

# Modalities that aren't useful pipeline-output types — chains terminate
# here. (LABEL/MASK/BOXES/SCALAR are typically terminal; few opcodes
# consume them downstream.)
TERMINAL_MODALITIES = {"LABEL", "LABEL_SEQ", "SCALAR", "ACTION"}

# Modalities that "carry" the pipeline forward.
PIPELINE_MODALITIES = {"TEXT", "IMAGE", "AUDIO", "VIDEO", "3D", "DOC",
                       "TABULAR", "GRAPH", "EMBEDDING", "MASK",
                       "KEYPOINTS", "DEPTH_MAP", "TIMESERIES"}


def ranked_successors(opcode_row: dict, all_rows: list[dict],
                      top: int = 5) -> list[tuple[float, dict, set[str]]]:
    """Return top N (score, row, matched_modalities) for opcodes whose
    inputs intersect this opcode's outputs."""
    outs = set(opcode_row.get("outputs") or [])
    if not outs:
        return []
    a_step = opcode_row.get("pipeline_step")
    candidates: list[tuple[float, dict, set[str]]] = []
    for r in all_rows:
        if r["task"] == opcode_row["task"]:
            continue
        ins = set(r.get("inputs") or [])
        match = outs & ins
        if not match:
            continue
        score = 0.0
        # Recency: era 5 = +1.0, era 7 = +1.4
        score += (r.get("era", 1)) * 0.2
        # Compound-task bonus: L3 (multi-input) and L5 (Any/universal)
        layer = r.get("layer")
        if layer in (3, 5):
            score += 0.5
        # Pipeline-step continuity (avatar-pipeline-aware)
        b_step = r.get("pipeline_step")
        if a_step is not None and b_step is not None:
            if b_step == a_step + 1:
                score += 1.5
            elif b_step > a_step:
                score += 0.4
        # Pipeline-carrying modality bonus (prefer outputs that propagate)
        if match & PIPELINE_MODALITIES:
            score += 0.2
        # Any-to-Any penalty — trivially eats everything; demote
        if r["task"] == "Any-to-Any":
            score -= 1.2
        # Self-modal opcodes (TEXT→TEXT, AUDIO→AUDIO) score lower unless
        # they're explicitly transformative
        if outs == set(r.get("outputs") or []) and len(outs) == 1:
            score -= 0.2
        candidates.append((score, r, match))
    candidates.sort(key=lambda x: (-x[0], x[1]["task"]))
    return candidates[:top]


# ---- chain continuations via path_builder ------------------------------

def continuation_chains(opcode: str, opcode_row: dict,
                        n: int = 3) -> list[list[str]]:
    """Find 2-3 step chains that START at this opcode. Uses path_builder
    rank with this opcode's first output modality as SRC, and a popular
    target modality as DST."""
    outs = opcode_row.get("outputs") or []
    if not outs:
        return []
    src = outs[0]
    if src in TERMINAL_MODALITIES:
        return []  # nothing meaningful to chain to
    chains: list[list[str]] = []
    seen: set[tuple] = set()
    # Try a few target modalities — focus on the ones that carry forward
    targets = ["VIDEO", "AUDIO", "IMAGE", "TEXT", "3D"]
    for dst in targets:
        if dst == src:
            continue
        try:
            r = subprocess.run(
                [sys.executable, str(PATH_BUILDER), "rank",
                 src, dst, "--top", "10"],
                capture_output=True, text=True, timeout=15,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return chains
        for line in r.stdout.splitlines():
            m = re.match(
                r"^\[\s*\d+\][^A-Za-z]*score=[\d.]+\s+(.+?)\s*$",
                line,
            )
            if not m:
                continue
            chain = [s.strip() for s in m.group(1).split("→")]
            # We want chains where the user is INSIDE the flow after our
            # opcode finishes. Prepend the opcode and dedup.
            if chain[0] == opcode:
                pass  # already starts with the opcode
            else:
                chain = [opcode] + chain
            if len(chain) < 2:
                continue
            key = tuple(chain)
            if key in seen:
                continue
            seen.add(key)
            chains.append(chain)
            if len(chains) >= n:
                return chains
    return chains


# ---- modality flow lattice ---------------------------------------------

def modality_flow(rows: list[dict]) -> tuple[dict[str, list[str]],
                                              dict[str, list[str]]]:
    """Return (producers, consumers) maps: modality -> sorted opcode names."""
    producers: dict[str, list[str]] = defaultdict(list)
    consumers: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        for o in (r.get("outputs") or []):
            producers[o].append(r["task"])
        for i in (r.get("inputs") or []):
            consumers[i].append(r["task"])
    for m in producers:
        producers[m].sort()
    for m in consumers:
        consumers[m].sort()
    return producers, consumers


# ---- Mermaid rendering -------------------------------------------------

def _safe_id(s: str, prefix: str = "n") -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    if not clean:
        clean = "x"
    if clean[0].isdigit():
        clean = "_" + clean
    return f"{prefix}_{clean}"


def successor_mermaid(opcode: str, opcode_row: dict,
                      successors: list[tuple[float, dict, set[str]]]) -> str:
    """Mermaid flowchart: this opcode as root, top successors as fan-out."""
    if not successors:
        return ("flowchart LR\n"
                f'    this["{opcode}<br/>(no successors — terminal output)"]')
    lines = ["flowchart LR"]
    lines.append("    classDef root fill:#fff3e0,stroke:#f4511e,stroke-width:2px")
    lines.append("    classDef succ fill:#e3f2fd,stroke:#1976d2")
    lines.append("    classDef succHi fill:#fff8e1,stroke:#f57c00,stroke-width:2px")
    root_id = _safe_id(opcode, "this")
    outs = "+".join(opcode_row.get("outputs", []) or ["-"])
    lines.append(f'    {root_id}["{opcode}<br/><i>outputs: {outs}</i>"]')
    lines.append(f"    class {root_id} root")
    for i, (score, r, match) in enumerate(successors):
        sid = _safe_id(r["task"], f"s{i}")
        layer = r.get("layer", "?")
        era = r.get("era", "?")
        lines.append(f'    {sid}["{r["task"]}<br/>'
                     f'<i>era {era}, L{layer}</i>"]')
        # First two get highlighted
        klass = "succHi" if i < 2 else "succ"
        lines.append(f"    class {sid} {klass}")
        match_str = ",".join(sorted(match))
        lines.append(f"    {root_id} -->|{match_str}| {sid}")
    return "\n".join(lines)


def modality_flow_mermaid(mod: str, producers: list[str],
                          consumers: list[str], by_name: dict[str, dict],
                          max_per_side: int = 8) -> str:
    """For one modality, show producers on the left flowing into consumers
    on the right. Cap to keep readable."""
    prods = producers[:max_per_side]
    cons = consumers[:max_per_side]
    if not prods or not cons:
        return None
    lines = ["flowchart LR"]
    lines.append("    classDef p fill:#e8f5e9,stroke:#388e3c")
    lines.append("    classDef c fill:#e3f2fd,stroke:#1976d2")
    lines.append("    classDef m fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px")
    mod_id = _safe_id(mod, "mod")
    lines.append(f'    {mod_id}(("{mod}"))')
    lines.append(f"    class {mod_id} m")
    for p in prods:
        pid = _safe_id(p, "p")
        era = by_name[p].get("era", "?")
        lines.append(f'    {pid}["{p}<br/><i>era {era}</i>"]')
        lines.append(f"    class {pid} p")
        lines.append(f"    {pid} --> {mod_id}")
    for c in cons:
        cid = _safe_id(c, "c")
        era = by_name[c].get("era", "?")
        lines.append(f'    {cid}["{c}<br/><i>era {era}</i>"]')
        lines.append(f"    class {cid} c")
        lines.append(f"    {mod_id} --> {cid}")
    return "\n".join(lines)


# ---- emit --------------------------------------------------------------

HEADER = """\
# DAG_CROSS.md — Successor predictions across the opcode graph

> Companion to `DAG.md`. While DAG.md lays out how to INTERACT with one
> opcode at a time, this doc predicts what comes AFTER. At the `✓ done`
> terminal node of any opcode's GUI flow, the user can either stop or
> continue into another opcode's flow. The "continue" edges are the
> cross-DAG.
>
> Regenerate with:
> ```
> python3 planning/dag_cross_generator.py > planning/DAG_CROSS.md
> ```

## How successors are ranked

For an opcode A with outputs `outs`, every opcode B is a candidate
successor IFF `outs ∩ B.inputs ≠ ∅`. Candidates are then scored:

| Factor | Δ |
|---|---|
| Era recency (×0.2 per era) | +0.2 to +1.4 |
| Layer-3 or Layer-5 compound | +0.5 |
| Pipeline-step continuity (`b_step == a_step + 1`) | +1.5 |
| Pipeline-step lookahead (`b_step > a_step`) | +0.4 |
| Pipeline-carrying modality match | +0.2 |
| Any-to-Any (trivially eats everything) | −1.2 |
| Self-modal (A→A type) | −0.2 |

Top 5 candidates surface per opcode + a Mermaid mini-graph rendering
the fan-out.

---

## Modality flow lattice

For each primitive modality, the opcodes that PRODUCE it and the
opcodes that CONSUME it. The lattice shows where chains can branch
and where they terminate.

"""


FOOTER = """\
---

## Reading the cross-DAG in practice

When a user's session reaches the `✓ done` terminal of an opcode's GUI
flow, three behaviors are reasonable:

1. **Stop and save.** Most common. The user has what they came for.
2. **Continue into a top-ranked successor.** The UI offers the top 3
   successors as a "what's next" panel under the output. One click
   loads that opcode's GUI with the previous output pre-bound.
3. **Branch into a workflow template.** If the current `done` state
   matches the entry of a workflow_templates row (one whose first
   step.opcode equals this opcode's task), surface the template name
   as a "deeper workflow" suggestion.

The Phase-5 decomposer uses this same successor map: when the user
types "make a YouTube avatar", the decomposer searches outgoing edges
from `Video-Text-to-Text` (the entry opcode for "consume YT video"),
follows them through Text Generation → Text-to-Speech → Audio-Image-
to-Video, and produces the avatar workflow template seeded with the
top-ranked model candidate per step.

## How to extend

- Add an opcode → it shows up here automatically next regen.
- Tune the ranking heuristic → edit `ranked_successors` in
  `dag_cross_generator.py`. The 7 factors above are the surface area.
- Add a "blocklist" for specific opcode pairs that match by type but
  are semantically nonsense → add to `BLOCKED_PAIRS` (not yet defined,
  but the hook is here when needed).
"""


def emit() -> str:
    rows = load_taxonomy()
    by_name = {r["task"]: r for r in rows}
    producers, consumers = modality_flow(rows)

    out: list[str] = [HEADER]

    # Modality lattice — only show modalities with both producers AND
    # consumers (i.e. those that actually flow forward).
    flowing_mods = sorted(set(producers.keys()) & set(consumers.keys()))
    out.append(f"**{len(flowing_mods)} modalities** carry the pipeline forward "
               "(both producers AND consumers exist):")
    out.append("")
    out.append("| Modality | Producers | Consumers |")
    out.append("|---|---|---|")
    for mod in flowing_mods:
        ps = producers.get(mod, [])
        cs = consumers.get(mod, [])
        out.append(f"| `{mod}` | {len(ps)} | {len(cs)} |")
    out.append("")
    for mod in flowing_mods:
        ps = producers.get(mod, [])
        cs = consumers.get(mod, [])
        if not ps or not cs:
            continue
        out.append(f"### `{mod}` flow lattice")
        out.append("")
        out.append(f"**Producers ({len(ps)}):** "
                   + ", ".join(f"`{p}`" for p in ps))
        out.append("")
        out.append(f"**Consumers ({len(cs)}):** "
                   + ", ".join(f"`{c}`" for c in cs))
        out.append("")
        flow = modality_flow_mermaid(mod, ps, cs, by_name, max_per_side=8)
        if flow:
            out.append("```mermaid")
            out.append(flow)
            out.append("```")
            if len(ps) > 8 or len(cs) > 8:
                out.append(f"_(graph capped at 8/side; lattice has "
                           f"{len(ps)} producers × {len(cs)} consumers "
                           f"= {len(ps) * len(cs)} potential edges)_")
        out.append("")
    out.append("---")
    out.append("")

    # Per-opcode successor predictions, grouped by category
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r.get("category", "Other")].append(r)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda r: (r.get("layer", 99), r["task"]))

    out.append("## Per-opcode successor predictions")
    out.append("")
    out.append("Each opcode below lists its top 5 ranked successors, a "
               "Mermaid fan-out diagram, and 2-3 example chain "
               "continuations starting from this opcode.")
    out.append("")

    for cat in CATEGORY_ORDER:
        rows_in_cat = by_cat.get(cat, [])
        if not rows_in_cat:
            continue
        out.append(f"### {cat}  ({len(rows_in_cat)} opcodes)")
        out.append("")
        for row in rows_in_cat:
            op = row["task"]
            outs = row.get("outputs") or []
            outs_str = "+".join(outs) if outs else "—"
            successors = ranked_successors(row, rows, top=5)
            out.append(f"#### {op}")
            out.append(f"  **outputs:** `{outs_str}`")
            if not successors:
                out.append("")
                if outs and all(o in TERMINAL_MODALITIES for o in outs):
                    out.append("  _Terminal opcode — outputs are not consumed "
                               "by any other opcode in the taxonomy._")
                else:
                    out.append("  _No successors found._")
                out.append("")
                continue
            out.append("")
            out.append("  **Top successors (ranked):**")
            out.append("")
            out.append("  | # | Successor | Era | Layer | Match | Score |")
            out.append("  |---|---|---|---|---|---|")
            for i, (score, r, match) in enumerate(successors, 1):
                m = "+".join(sorted(match))
                out.append(f"  | {i} | `{r['task']}` | {r.get('era')} | "
                           f"L{r.get('layer')} | `{m}` | {round(score, 2)} |")
            out.append("")
            out.append("  **Fan-out:**")
            out.append("")
            out.append("```mermaid")
            out.append(successor_mermaid(op, row, successors))
            out.append("```")
            out.append("")
            # Continuations
            conts = continuation_chains(op, row, n=3)
            if conts:
                out.append("  **Example continuations:**")
                out.append("")
                for c in conts:
                    out.append(f"  - `{' → '.join(c)}`")
                out.append("")
            out.append("")
        out.append("---")
        out.append("")

    out.append(FOOTER)
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.write(emit())
