#!/usr/bin/env python3
"""author_cards.py — drafts per-opcode capability cards via the tiny
local model, chained through `cc -chain`.

The user's idea: chain a tiny local model to keep generating API content
that maps to what each model can do, so the global library has rich
metadata for each opcode without burning frontier-model tokens on it.

For each opcode in hf_task_evolution.jsonl, this runs a 3-step chain
on the local tiny model (qwen2.5-coder:1.5b or whatever CC_TINY_MODEL
is set to):

    1. List 4-6 user-facing parameters this opcode would expose
    2. List 3 common failure modes + mitigations
    3. List 4-6 concrete HF model IDs that serve this opcode + 1-line note

Each step's output is JSON-shaped (we strip code fences / commentary).
The three are bundled into a capability card and upserted into the
DB via `db.py card-upsert`.

Usage:
    author_cards.py <opcode>                    # one opcode
    author_cards.py --all                       # every opcode in JSONL
    author_cards.py --since 2026-01-01          # any opcode without a card or older than this
    author_cards.py --model qwen2.5:7b OP       # use a bigger drafter
    author_cards.py --dry OP                    # print prompts, don't call ollama
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent

def _find_taxonomy() -> Path:
    """Look in a few likely places. Repo checkout puts the JSONL in
    planning/; live installs bundle it next to this script in lib/."""
    candidates = [
        HERE / "hf_task_evolution.jsonl",                          # bundled (live install)
        HERE.parent.parent / "planning" / "hf_task_evolution.jsonl",  # repo layout
        HERE.parent / "planning" / "hf_task_evolution.jsonl",       # half-layout
    ]
    env = os.environ.get("CC_TAXONOMY")
    if env:
        candidates.insert(0, Path(env))
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]  # let the actual load error surface a useful path

DEFAULT_TAXONOMY = _find_taxonomy()

CC_BIN = os.environ.get("CC_BIN") or "cc"
DB_BIN = HERE / "db.py"


# ---- taxonomy IO -------------------------------------------------------

def load_taxonomy(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


# ---- prompt templates --------------------------------------------------

def prompts_for(opcode_row: dict) -> list[str]:
    """Three prompts forming the chain. Each asks for a compact JSON
    list — small models do best when the schema is explicit and the
    output is bounded."""
    op = opcode_row["task"]
    ins = "+".join(opcode_row.get("inputs", []) or ["-"])
    outs = "+".join(opcode_row.get("outputs", []) or ["-"])
    exemplars = ", ".join(opcode_row.get("exemplars", [])[:5]) or "n/a"
    role = opcode_row.get("role_in_avatar", "")

    p1 = (
        f"Opcode: {op} (inputs={ins}, outputs={outs}). Exemplar models: {exemplars}.\n"
        "List 4-6 user-facing parameters this opcode should expose. "
        "Reply with ONLY a compact JSON array of "
        '{"name":<str>,"type":<str>,"required":<bool>,"description":<str>}. '
        "No commentary, no markdown fences, no preamble."
    )
    p2 = (
        f"Opcode: {op}.\n"
        "List 3 common failure modes for THIS specific opcode plus a one-line "
        "mitigation each. Reply with ONLY a compact JSON array of "
        '{"failure":<str>,"mitigation":<str>}. '
        "No commentary, no markdown fences."
    )
    p3 = (
        f"Opcode: {op}. Known exemplar models: {exemplars}.\n"
        "List 4-6 concrete model identifiers (HF Hub IDs or service names) "
        "that serve this opcode well. Reply with ONLY a compact JSON array of "
        '{"id":<str>,"note":<str>}. '
        "Note should be 1 sentence covering speed, quality, or licence. "
        "No commentary, no markdown fences."
    )
    return [p1, p2, p3]


# ---- JSON salvage -------------------------------------------------------

# Small models occasionally wrap output in ``` or add a prefix. Pull the
# first balanced [...] or {...} block out.
def _salvage_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # find first '[' or '{' and try to parse from there
    for start_char, end_char in (('[', ']'), ('{', '}')):
        i = text.find(start_char)
        if i < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(text)):
            c = text[j]
            if esc:
                esc = False
                continue
            if c == '\\':
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == start_char:
                depth += 1
            elif c == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[i:j + 1])
                    except json.JSONDecodeError:
                        break
    return None


# ---- chain runner ------------------------------------------------------

def run_step(prompt: str, model: Optional[str] = None,
             dry: bool = False) -> str:
    """Call `cc tiny`. The chain semantics aren't needed for this
    drafter (each prompt is independent) — running tiny once per prompt
    is simpler and faster than wrapping in `cc -chain`. Each call still
    benefits from the model_call cache."""
    if dry:
        return f"[DRY] {prompt[:80]}…"
    args = [CC_BIN, "tiny"]
    if model:
        args += ["-model", model]
    args.append(prompt)
    r = subprocess.run(args, capture_output=True, text=True, timeout=120)
    return r.stdout.rstrip()


def author_card(opcode_row: dict, model: Optional[str] = None,
                dry: bool = False) -> dict:
    """Run the 3-prompt chain, salvage JSON from each, bundle into a card."""
    op = opcode_row["task"]
    prompts = prompts_for(opcode_row)
    raw_outputs: list[str] = []
    parsed: list = []
    t0 = time.monotonic()
    for i, p in enumerate(prompts):
        raw = run_step(p, model=model, dry=dry)
        raw_outputs.append(raw)
        if dry:
            parsed.append(None)
            continue
        salvaged = _salvage_json(raw)
        parsed.append(salvaged if salvaged is not None else
                      {"raw": raw, "parse_error": True})
    ms = int((time.monotonic() - t0) * 1000)

    card = {
        "opcode": op,
        "inputs": opcode_row.get("inputs"),
        "outputs": opcode_row.get("outputs"),
        "drafted_by": model or os.environ.get("CC_TINY_MODEL",
                                              "qwen2.5-coder:1.5b"),
        "drafted_ms": ms,
        "user_params": parsed[0] if isinstance(parsed[0], list) else None,
        "failure_modes": parsed[1] if isinstance(parsed[1], list) else None,
        "candidate_models": parsed[2] if isinstance(parsed[2], list) else None,
        "parse_failures": [
            i for i, p in enumerate(parsed) if isinstance(p, dict)
            and p.get("parse_error")
        ],
    }
    return card


def persist_card(opcode: str, card: dict, drafted_by: str) -> None:
    db_path = (os.environ.get("CC_DB")
               or os.environ.get("CC_GLOBAL_DB")
               or str(Path.home() / ".cc" / "cc.db"))
    env = {**os.environ, "CC_DB": db_path}
    subprocess.run(
        [sys.executable, str(DB_BIN), "card-upsert",
         opcode, drafted_by, json.dumps(card, ensure_ascii=False), "tiny-chain"],
        check=True, env=env,
    )


def main():
    ap = argparse.ArgumentParser(prog="author_cards.py")
    ap.add_argument("opcode", nargs="?", default=None,
                    help="opcode to draft a card for (or use --all)")
    ap.add_argument("--all", action="store_true",
                    help="author cards for every opcode in the taxonomy")
    ap.add_argument("--missing", action="store_true",
                    help="only opcodes without an existing card")
    ap.add_argument("--model", default=None,
                    help="override CC_TINY_MODEL for the drafter")
    ap.add_argument("--dry", action="store_true",
                    help="print prompts only, no ollama calls")
    ap.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY),
                    help="path to hf_task_evolution.jsonl")
    args = ap.parse_args()

    rows = load_taxonomy(Path(args.taxonomy))
    by_name = {r["task"]: r for r in rows}

    targets: list[dict]
    if args.all:
        targets = rows
    elif args.opcode:
        if args.opcode not in by_name:
            sys.exit(f"unknown opcode: {args.opcode!r}")
        targets = [by_name[args.opcode]]
    else:
        ap.print_help()
        sys.exit(2)

    if args.missing and not args.dry:
        # Filter out opcodes that already have cards in the DB
        db_path = (os.environ.get("CC_DB")
                   or os.environ.get("CC_GLOBAL_DB")
                   or str(Path.home() / ".cc" / "cc.db"))
        import sqlite3
        c = sqlite3.connect(db_path)
        try:
            existing = {r[0] for r in c.execute(
                "SELECT opcode FROM capability_cards")}
        finally:
            c.close()
        before = len(targets)
        targets = [t for t in targets if t["task"] not in existing]
        print(f"# --missing: filtered {before} → {len(targets)} opcodes "
              "(skipped ones already carded)", file=sys.stderr)

    print(f"# authoring {len(targets)} card(s)…", file=sys.stderr)

    for i, opcode_row in enumerate(targets, 1):
        op = opcode_row["task"]
        print(f"\n[{i}/{len(targets)}] {op}", file=sys.stderr, flush=True)
        try:
            card = author_card(opcode_row, model=args.model, dry=args.dry)
        except subprocess.TimeoutExpired:
            print(f"  TIMEOUT — skipping", file=sys.stderr)
            continue
        except FileNotFoundError as e:
            sys.exit(f"  cc binary not found: {e}")
        if args.dry:
            print(json.dumps(card, indent=2))
            continue
        # Sanity log + persist
        fails = card.get("parse_failures") or []
        if fails:
            print(f"  ⚠ {len(fails)} step(s) returned unparseable JSON",
                  file=sys.stderr)
        persist_card(op, card, drafted_by=card["drafted_by"])
        n_params = len(card["user_params"]) if card["user_params"] else 0
        n_fails = len(card["failure_modes"]) if card["failure_modes"] else 0
        n_models = len(card["candidate_models"]) if card["candidate_models"] else 0
        print(f"  ✓ params={n_params} failures={n_fails} models={n_models}  "
              f"({card['drafted_ms']}ms)", file=sys.stderr)

    print(f"\n# done.", file=sys.stderr)


if __name__ == "__main__":
    main()
