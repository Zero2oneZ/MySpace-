#!/usr/bin/env python3
"""author_templates.py — Claude writes rich workflow templates against
the seeded library (capability_cards + gui_cards + path_builder paths).

This is W2-claude (per WORKFLOW_LIBRARY.md). It produces ONE row in
workflow_templates per call. Costs ~$0.02 per template (Claude
Sonnet pricing). Reused thousands of times.

The frontier-model call is GATED by default — running this script
WITHOUT --execute prints the prompt that WOULD be sent and exits.
You need --execute to actually call Claude. This is intentional: it's
the one place in MySpace++ that spends money.

Usage:
    author_templates.py <opcode> [--goal "free-form goal"]   # --dry (default)
    author_templates.py <opcode> --execute                    # ACTUALLY calls Claude
    author_templates.py --all --execute                       # author for every opcode
    author_templates.py --missing --execute                   # only opcodes without a template

The prompt builder reads:
  - capability_card[opcode]   from the global DB
  - gui_card[opcode]          from the global DB
  - path_builder top-5        chains involving this opcode
  - taxonomy entry            from hf_task_evolution.jsonl

…and asks Claude to emit a workflow_templates row with:
  - steps[] (opcodes + binds + purpose + model_candidates + human_checkpoint)
  - preconditions[]
  - fallbacks{}
  - __BRANCH__ steps where the chain benefits from quality loops

Output is validated against the schema before persistence:
  - every step.opcode must exist in the taxonomy
  - every step.binds[*] must reference either $input_* or a prior step
  - every step.opcode's inputs[] must be satisfiable by upstream outputs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
CC_BIN = os.environ.get("CC_BIN") or "cc"
DB_BIN = HERE / "db.py"


# ---- taxonomy + card loaders -------------------------------------------

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


def _find_path_builder() -> Optional[Path]:
    candidates = [
        HERE.parent.parent / "planning" / "path_builder.py",
        HERE.parent / "planning" / "path_builder.py",
        HERE / "path_builder.py",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_taxonomy(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        rows[r["task"]] = r
    return rows


def load_card(table: str, opcode: str) -> Optional[dict]:
    db_path = (os.environ.get("CC_DB")
               or os.environ.get("CC_GLOBAL_DB")
               or str(Path.home() / ".cc" / "cc.db"))
    import sqlite3
    c = sqlite3.connect(db_path)
    try:
        r = c.execute(
            f"SELECT card_json FROM {table} WHERE opcode=?",
            (opcode,),
        ).fetchone()
    finally:
        c.close()
    if not r:
        return None
    try:
        return json.loads(r[0])
    except json.JSONDecodeError:
        return None


def load_template(name: str) -> Optional[dict]:
    db_path = (os.environ.get("CC_DB")
               or os.environ.get("CC_GLOBAL_DB")
               or str(Path.home() / ".cc" / "cc.db"))
    import sqlite3
    c = sqlite3.connect(db_path)
    try:
        r = c.execute(
            "SELECT template_json FROM workflow_templates WHERE name=?",
            (name,),
        ).fetchone()
    finally:
        c.close()
    if not r:
        return None
    try:
        return json.loads(r[0])
    except json.JSONDecodeError:
        return None


def existing_template_names() -> set[str]:
    db_path = (os.environ.get("CC_DB")
               or os.environ.get("CC_GLOBAL_DB")
               or str(Path.home() / ".cc" / "cc.db"))
    import sqlite3
    c = sqlite3.connect(db_path)
    try:
        return {r[0] for r in
                c.execute("SELECT primary_opcode FROM workflow_templates "
                          "WHERE primary_opcode IS NOT NULL")}
    finally:
        c.close()


def load_top_paths(opcode: str, tax: dict[str, dict],
                   top: int = 5) -> list[list[str]]:
    """Use path_builder.py's rank to find top chains FROM and TO this
    opcode's modality. Returns up to `top` distinct paths combining both
    directions."""
    pb = _find_path_builder()
    if pb is None:
        return []
    row = tax.get(opcode)
    if not row:
        return []
    ins = row.get("inputs") or []
    outs = row.get("outputs") or []
    paths: list[list[str]] = []
    # Use each input modality as a "from" and each output modality as
    # a "to". Run two queries: from_in → from_out (this opcode acts
    # as a starter) and from_out → external_out (continuations).
    seen_keys: set[tuple] = set()
    for in_mod in ins[:1]:  # first input only — keep prompt small
        for out_mod in outs[:1]:
            try:
                r = subprocess.run(
                    [sys.executable, str(pb), "rank", in_mod, out_mod,
                     "--top", str(top)],
                    capture_output=True, text=True, timeout=30,
                )
                for line in r.stdout.splitlines():
                    m = re.match(r"^\[\s*\d+\].*?  (.+)$", line)
                    if not m:
                        continue
                    chain = [s.strip() for s in m.group(1).split("→")]
                    if opcode not in chain:
                        continue
                    key = tuple(chain)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    paths.append(chain)
                    if len(paths) >= top:
                        return paths
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
    return paths


# ---- prompt builder ----------------------------------------------------

TEMPLATE_SCHEMA_SPEC = """\
{
  "name": "<kebab-case-name>",
  "primary_opcode": "<opcode from taxonomy>",
  "description": "<one short paragraph>",
  "tags": ["<keyword>", ...],
  "preconditions": [
    {"check": "<name>", "value": <any>}
  ],
  "fallbacks": {
    "<opcode>": ["<fallback opcode>", ...]
  },
  "steps": [
    {
      "idx": 0,
      "opcode": "<opcode>",
      "purpose": "<one line>",
      "binds": {"<INPUT_MOD>": "$<varname>", ...},
      "out": "<varname>",
      "model_candidates": ["<concrete model id>", ...],
      "human_checkpoint": null | {"type": "y/n"|"text"|"redo",
                                  "prompt": "<question>",
                                  "default": "<y|n|...>"}
    },
    {
      "idx": <int>,
      "opcode": "__BRANCH__",
      "purpose": "<one line>",
      "branch_on": "$<varname or step_out>",
      "branches": {
        "<predicate>": {"goto": <step_idx>, "max_retries": <int>?,
                        "mutate": "<optional mutation directive>"}
      }
    }
  ],
  "outputs": [{"name": "<varname>", "modality": "<MOD>"}]
}
"""


def build_prompt(opcode_row: dict, cap_card: dict, gui_card: dict,
                 top_paths: list[list[str]], goal: Optional[str]) -> str:
    op = opcode_row["task"]
    ins = "+".join(opcode_row.get("inputs", []) or ["-"])
    outs = "+".join(opcode_row.get("outputs", []) or ["-"])
    goal_block = f"\n## User goal\n{goal}\n" if goal else ""

    paths_block = ""
    if top_paths:
        paths_block = "\n## Top chains involving this opcode\n" + "\n".join(
            f"  - {' → '.join(p)}" for p in top_paths
        ) + "\n"

    return (
        "You are authoring ONE row of MySpace++'s workflow_templates library.\n"
        "These templates are reused thousands of times across user projects, so\n"
        "they should encode best practices: quality loops, fallbacks, sensible\n"
        "model candidates, and human-checkpoint moments where a person should\n"
        "review output before continuing.\n"
        "\n"
        f"## Target opcode\n"
        f"  task:     {op}\n"
        f"  inputs:   {ins}\n"
        f"  outputs:  {outs}\n"
        f"  era:      {opcode_row.get('era')}\n"
        f"  layer:    L{opcode_row.get('layer')}\n"
        f"  role:     {opcode_row.get('role_in_avatar')}\n"
        f"  exemplars:{', '.join(opcode_row.get('exemplars', []))}\n"
        "\n"
        "## Capability card (tiny-drafted; user params, failure modes, candidate models)\n"
        f"{json.dumps(cap_card, indent=2)}\n"
        "\n"
        "## GUI card (tiny-drafted; widget specs the frontend will render)\n"
        f"{json.dumps(gui_card, indent=2)}\n"
        f"{paths_block}"
        f"{goal_block}"
        "\n"
        "## Your job\n"
        "Author a workflow template centered on this opcode. The template can:\n"
        " - be a SIMPLE chain (one opcode, end-to-end) if the user request is direct\n"
        " - or chain through 2-4 related opcodes when quality benefits (e.g.\n"
        "   rewrite-prompt → generate → quality-check → branch-back-if-low)\n"
        " - include `__BRANCH__` steps for retry / quality loops (max_retries: 3)\n"
        " - include `human_checkpoint` ONLY where a person would meaningfully\n"
        "   review (e.g. before saving a generated video, before sending output\n"
        "   to a third party). Do NOT add checkpoints just because.\n"
        " - propose 3-5 `model_candidates` per step, ORDERED preference (best first)\n"
        " - include `fallbacks` mapping each opcode that COULD be unavailable\n"
        "   (e.g. closed APIs) to an open-weight alternative\n"
        "\n"
        "## Output rules\n"
        "Reply with ONLY a valid JSON object matching this schema. No markdown\n"
        "fences. No preamble. No commentary. No keys outside the schema.\n"
        "\n"
        f"{TEMPLATE_SCHEMA_SPEC}\n"
        "\n"
        "Begin with `{`, end with `}`. Validate mentally that every opcode you\n"
        "reference appears in the capability card's vocabulary or the listed\n"
        "exemplars/paths. Use kebab-case for `name`. Keep `description` to ≤2 sentences."
    )


# ---- JSON salvage + schema validation ----------------------------------

def _salvage_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    # Find first { and last balanced }
    i = text.find("{")
    if i < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(i, len(text)):
        c = text[j]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i:j + 1])
                except json.JSONDecodeError:
                    return None
    return None


# Common alias map for Claude's name variants — keep tight; only known
# safe substitutions. Order matters (longer matches first).
OPCODE_ALIASES = {
    "Text2Text Generation": "Text Generation",
    "Text-to-Text Generation": "Text Generation",
    "Text2Text": "Text Generation",
}


def _resolve_opcode(name: str, tax: dict[str, dict]) -> str | None:
    """Try to resolve a Claude-invented opcode name to a taxonomy
    member. Returns canonical name or None."""
    if name in tax:
        return name
    # Exact alias map
    if name in OPCODE_ALIASES and OPCODE_ALIASES[name] in tax:
        return OPCODE_ALIASES[name]
    # Hyphens → spaces (Visual-Question-Answering → Visual Question Answering)
    spaced = name.replace("-", " ").replace("_", " ")
    if spaced in tax:
        return spaced
    # Case-insensitive exact
    lower_map = {t.lower(): t for t in tax}
    if name.lower() in lower_map:
        return lower_map[name.lower()]
    return None


def validate_template(tpl: dict, tax: dict[str, dict]) -> tuple[bool, list[str]]:
    """Return (ok, errors). Light-touch validation — the template
    library is meant to be iterable, not perfect on first author.

    Also auto-corrects opcode names via OPCODE_ALIASES / hyphen->space /
    case-insensitive match. The template is mutated in place when a
    correction lands so it persists with the canonical name."""
    errs: list[str] = []
    for key in ("name", "primary_opcode", "description", "steps"):
        if key not in tpl:
            errs.append(f"missing required key: {key!r}")
    if not isinstance(tpl.get("steps"), list):
        errs.append("steps must be a list")
        return False, errs
    # primary_opcode: try resolution
    resolved = _resolve_opcode(tpl["primary_opcode"], tax)
    if resolved is None:
        errs.append(f"primary_opcode {tpl['primary_opcode']!r} not in taxonomy")
    elif resolved != tpl["primary_opcode"]:
        tpl["primary_opcode"] = resolved
    for i, step in enumerate(tpl["steps"]):
        if not isinstance(step, dict):
            errs.append(f"step[{i}] not a dict")
            continue
        op = step.get("opcode")
        if op is None:
            errs.append(f"step[{i}] missing opcode")
            continue
        if op != "__BRANCH__":
            resolved = _resolve_opcode(op, tax)
            if resolved is None:
                errs.append(f"step[{i}] opcode {op!r} not in taxonomy")
            elif resolved != op:
                step["opcode"] = resolved
            if "binds" not in step or not isinstance(step["binds"], dict):
                errs.append(f"step[{i}] missing or invalid binds")
            if "out" not in step:
                errs.append(f"step[{i}] missing out")
    return len(errs) == 0, errs


# ---- Claude invocation -------------------------------------------------

def call_claude(prompt: str, timeout: int = 300) -> str:
    """Shell out to `cc claude -p <prompt>`. This DOES cost money.
    The caller must have intended this path (default is --dry)."""
    args = [CC_BIN, "claude", "-p", prompt]
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def persist_template(tpl: dict, authored_by: str, prompt_hash: str) -> None:
    name = tpl.get("name", "untitled")
    primary = tpl.get("primary_opcode", "")
    desc = tpl.get("description", "")
    tags = ",".join(tpl.get("tags") or [])
    template_json = json.dumps(tpl, ensure_ascii=False)
    pre_json = json.dumps(tpl.get("preconditions") or [])
    fb_json = json.dumps(tpl.get("fallbacks") or {})
    env = {**os.environ, "CC_DB": (os.environ.get("CC_DB")
                                    or os.environ.get("CC_GLOBAL_DB")
                                    or str(Path.home() / ".cc" / "cc.db"))}
    subprocess.run(
        [sys.executable, str(DB_BIN), "template-add",
         name, primary, desc, tags, template_json, pre_json, fb_json,
         authored_by, prompt_hash],
        check=True, env=env,
    )


# ---- main --------------------------------------------------------------

def author_one(opcode: str, tax: dict[str, dict],
               goal: Optional[str], dry: bool) -> Optional[dict]:
    row = tax.get(opcode)
    if not row:
        print(f"unknown opcode: {opcode!r}", file=sys.stderr)
        return None

    cap = load_card("capability_cards", opcode)
    gui = load_card("gui_cards", opcode)
    if cap is None:
        print(f"  ⚠ no capability card for {opcode} — run `cc -author-cards "
              f"{opcode}` first", file=sys.stderr)
        return None
    if gui is None:
        print(f"  ⚠ no gui card for {opcode} — run `cc -author-gui-cards "
              f"{opcode}` first", file=sys.stderr)
        return None

    paths = load_top_paths(opcode, tax, top=5)
    prompt = build_prompt(row, cap, gui, paths, goal)
    prompt_hash = "sha256:" + hashlib.sha256(prompt.encode()).hexdigest()[:16]

    if dry:
        print("─── PROMPT (dry — Claude NOT called, no cost incurred) ───",
              file=sys.stderr)
        print(prompt)
        print(f"─── prompt hash: {prompt_hash} ───", file=sys.stderr)
        print(f"─── est. ~{len(prompt) // 4} input tokens, "
              "~$0.01-0.03 to author with Claude Sonnet ───",
              file=sys.stderr)
        return None

    print(f"  → calling Claude ({len(prompt) // 4} input tokens)…",
          file=sys.stderr, flush=True)
    t0 = time.monotonic()
    try:
        raw = call_claude(prompt)
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT calling Claude — skipping", file=sys.stderr)
        return None
    ms = int((time.monotonic() - t0) * 1000)
    tpl = _salvage_json(raw)
    if tpl is None:
        print(f"  ⚠ Claude response was not valid JSON ({len(raw)} bytes); "
              "skipping. Raw response written to /tmp/cc-author-fail.txt",
              file=sys.stderr)
        Path("/tmp/cc-author-fail.txt").write_text(raw)
        return None
    ok, errs = validate_template(tpl, tax)
    if not ok:
        print(f"  ⚠ template failed validation:", file=sys.stderr)
        for e in errs:
            print(f"      - {e}", file=sys.stderr)
        Path("/tmp/cc-author-fail.json").write_text(
            json.dumps(tpl, indent=2))
        print(f"      raw template at /tmp/cc-author-fail.json",
              file=sys.stderr)
        return None
    print(f"  ✓ valid template '{tpl['name']}' with {len(tpl['steps'])} step(s)"
          f" ({ms}ms)", file=sys.stderr)
    persist_template(tpl, authored_by="claude", prompt_hash=prompt_hash)
    return tpl


def main():
    ap = argparse.ArgumentParser(prog="author_templates.py")
    ap.add_argument("opcode", nargs="?", default=None)
    ap.add_argument("--all", action="store_true",
                    help="every opcode that has both cards")
    ap.add_argument("--missing", action="store_true",
                    help="only opcodes without an existing template")
    ap.add_argument("--goal", default=None,
                    help="optional free-form goal to bias the template")
    ap.add_argument("--execute", action="store_true",
                    help="actually call Claude (default is --dry)")
    ap.add_argument("--taxonomy", default=str(_find_taxonomy()))
    args = ap.parse_args()

    tax = load_taxonomy(Path(args.taxonomy))

    if args.opcode:
        targets = [args.opcode]
    elif args.all or args.missing:
        # Opcodes that have both cards
        db_path = (os.environ.get("CC_DB")
                   or os.environ.get("CC_GLOBAL_DB")
                   or str(Path.home() / ".cc" / "cc.db"))
        import sqlite3
        c = sqlite3.connect(db_path)
        try:
            cap_set = {r[0] for r in
                       c.execute("SELECT opcode FROM capability_cards")}
            gui_set = {r[0] for r in
                       c.execute("SELECT opcode FROM gui_cards")}
            if args.missing:
                done = existing_template_names()
                targets = sorted((cap_set & gui_set) - done)
            else:
                targets = sorted(cap_set & gui_set)
        finally:
            c.close()
    else:
        ap.print_help()
        sys.exit(2)

    dry = not args.execute
    if dry:
        print("# DRY MODE — no Claude API calls will be made. Add --execute to "
              "actually spend tokens.", file=sys.stderr)
    print(f"# {'authoring' if not dry else 'previewing'} {len(targets)} "
          f"template(s)…", file=sys.stderr)

    n_ok = 0
    for i, op in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}] {op}", file=sys.stderr, flush=True)
        r = author_one(op, tax, args.goal, dry=dry)
        if r is not None:
            n_ok += 1

    print(f"\n# done. {n_ok}/{len(targets)} successful.",
          file=sys.stderr)


if __name__ == "__main__":
    main()
