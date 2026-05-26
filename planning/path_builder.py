#!/usr/bin/env python3
"""path_builder.py — interactive walker for the MySpace++ opcode DAG.

Layers on top of task_dag.py:
  1. Scoring/ranking — orders BFS results so the top few are usually right.
  2. Two-mode REPL — Path mode (walk a chosen pipeline up/down/sideways) and
     DAG mode (walk node-by-node through the typed graph).
  3. Workflow emission — produces a JSON skeleton compatible with cc's
     `workflow define` schema (tool / binds / out per step).

Run modes:
  path_builder.py                            # interactive REPL (default)
  path_builder.py rank DOC AUDIO             # ranked one-shot
  path_builder.py build "Document Question Answering" "Translation" "Text-to-Speech"
                                             # build + emit workflow JSON

REPL commands:
  --- search ---
  goal SRC DST [--intent TEXT]   search ranked pipelines from SRC to DST modality
  list [N]                        list top N ranked candidates (default 10)
  show I                          load candidate I as the current working path
  rerank --intent TEXT            re-rank current candidates with new intent

  --- walk current path ---
  path                            show current working path
  alts I                          alternative tasks for step I (same IO slot)
  swap I TASK                     replace step I with TASK
  insert I TASK                   insert TASK before step I
  append TASK                     append TASK at the end
  remove I                        delete step I
  validate                        check the path's edges are still consistent
  emit [NAME]                     print workflow JSON
  save NAME                       remember the path under NAME

  --- DAG walk (no current path needed) ---
  node TASK                       switch to DAG mode at TASK
  in                              tasks whose outputs feed this node's inputs
  out                             tasks whose inputs accept this node's outputs
  goto TASK                       jump to another node

  --- info ---
  info TASK                       full metadata for TASK
  modalities                      list all known modality primitives
  catalog [REGEX]                 list tasks (optionally filtered)
  saved                           list saved paths
  help | ?                        this list
  quit | exit                     leave

Scoring heuristic (default, tunable):
  base 10.0
  - 0.7 per hop after the first
  - 2.0 if Fill-Mask appears in the interior of a chain (pretraining task)
  - 1.5 if a TEXT-only routing task appears when neither endpoint is TEXT
  + 0.3 per Layer-3/5 compound task (modality-collapsing)
  + 0.2 per Era-5+ task (modern multimodal LLM)
  + 0.4 per task whose role mentions intent keywords
  - 0.3 if both endpoints are the same modality and length > 1 (loopback)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

# Reuse task_dag's loader so the JSONL source-of-truth is single.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import task_dag as td  # noqa: E402


# ---- scoring ------------------------------------------------------------

INTENT_FIELDS = ("role_in_avatar", "notes", "category", "task")


def score_path(
    path_tasks: list[dict],
    src_mod: str,
    dst_mod: str,
    intent: str = "",
) -> float:
    s = 10.0
    n = len(path_tasks)

    # Length penalty: each hop after the first costs 0.9. Harsher than
    # the original 0.7 so coverage and name boosts can't easily inflate
    # a 5-step chain past a clean 2-step canonical (was happening on
    # voice→3D model — see PIPELINES.md #7).
    s -= max(0, (n - 1) * 0.9)

    # Loopback penalty: same modality both ends and chain length > 1
    # is usually unnecessary indirection.
    if src_mod == dst_mod and n > 1:
        s -= 0.3

    intent_words = [w.lower() for w in re.split(r"\W+", intent) if w]

    def _matched_words(text: str) -> set[str]:
        """Return SET of intent words matched against `text`. Uses 6-char
        prefix for long words so translate/translation match (share
        'transl') but transfer/translation do not (diverge at 'transl'
        vs 'transf'). Short words (<6 chars) require exact match."""
        if not intent_words:
            return set()
        words = [w for w in re.split(r"\W+", text.lower()) if w]
        word_set = set(words)
        out: set[str] = set()
        for iw in intent_words:
            if len(iw) < 6:
                if iw in word_set:
                    out.add(iw)
                continue
            for w in words:
                if len(w) >= 6 and iw[:6] == w[:6]:
                    out.add(iw)
                    break
        return out

    # Per-task: which intent words this task matches (in role/notes/category/name).
    per_task_matches: list[set[str]] = []
    for t in path_tasks:
        blob = " ".join(str(t.get(f, "")) for f in INTENT_FIELDS)
        per_task_matches.append(_matched_words(blob))
    intent_hits_per_task = [bool(m) for m in per_task_matches]
    unique_path_matches: set[str] = set().union(*per_task_matches) if per_task_matches else set()

    for i, t in enumerate(path_tasks):
        layer = t.get("layer")
        era = t.get("era", 0)
        name = t["task"]
        ins = t.get("inputs", [])
        outs = t.get("outputs", [])

        # Layer-collapse reward
        if layer in (3, 5):
            s += 0.3

        # Modern compound reward
        if era >= 5:
            s += 0.2

        # Pretraining task in the interior — almost never useful
        if name == "Fill-Mask" and 0 < i < n - 1:
            s -= 2.0

        # TEXT-only routing when neither endpoint is TEXT is wasteful UNLESS
        # this specific task matched the user's intent (e.g. "translate" for
        # Translation pulls it back in).
        if (
            set(ins) == {"TEXT"}
            and set(outs) == {"TEXT"}
            and "TEXT" not in (src_mod, dst_mod)
            and not intent_hits_per_task[i]
        ):
            s -= 1.5

    # Coverage-based intent bonus. Base +1.0 if any intent word matched,
    # plus +0.2 per ADDITIONAL distinct word covered, capped at +0.6
    # (3+ words contribute the same as 5). Keeps the bonus modest so a
    # 5-step chain matching 4 words can't run away from a clean 2-step.
    if unique_path_matches:
        s += 1.0 + min(0.6, 0.2 * len(unique_path_matches))

    # Per-task name boost: intent word matches the task NAME directly
    # (stronger signal than matching the role/notes blob). Hard-capped
    # at 2 boosts per path — beyond that it's just bloat.
    if intent_words:
        name_boosts = 0
        for t in path_tasks:
            if name_boosts >= 2:
                break
            if _matched_words(t["task"]):
                s += 0.7
                name_boosts += 1

    return round(s, 2)


# ---- workflow emission --------------------------------------------------

def emit_workflow(
    path_tasks: list[dict],
    name: str = "untitled",
    description: str = "",
) -> dict:
    """Build a JSON that's shaped to drop into `cc workflow define`. Each
    step's `tool` field is the task name (opcode) — concrete tool
    resolution is a downstream step (mapping opcode → registered cc tool)."""
    steps = []
    prev_out_var: Optional[str] = None
    for i, t in enumerate(path_tasks):
        ins = t.get("inputs", [])
        out_var = f"step_{i}_out"
        # Each non-modality input is bound to the previous step's output
        # if a modality match exists; otherwise the user is expected to
        # supply it as a top-level variable like $user_text.
        binds: dict[str, str] = {}
        for slot in ins:
            if i == 0:
                binds[slot] = f"$input_{slot.lower()}"
            else:
                prev_outs = path_tasks[i - 1].get("outputs", [])
                if slot in prev_outs and prev_out_var is not None:
                    binds[slot] = f"${prev_out_var}"
                else:
                    binds[slot] = f"$input_{slot.lower()}"
        steps.append({
            "tool": t["task"],
            "binds": binds,
            "out": out_var,
        })
        prev_out_var = out_var
    return {
        "name": name,
        "description": description or
            f"auto-built {len(path_tasks)}-step pipeline by path_builder.py",
        "steps": steps,
    }


# ---- REPL ---------------------------------------------------------------

class REPL:
    def __init__(self, jsonl: Path):
        self.tasks: list[dict] = td.load(jsonl)
        self.by_name = td.by_name(self.tasks)
        self.candidates: list[tuple[float, list[str]]] = []
        self.current_path: list[str] = []
        self.search = {"src": "", "dst": "", "intent": ""}
        self.saved: dict[str, list[str]] = {}
        self.dag_cursor: Optional[str] = None
        self.dispatch = {
            "goal": self.cmd_goal, "list": self.cmd_list,
            "show": self.cmd_show, "rerank": self.cmd_rerank,
            "path": self.cmd_path, "alts": self.cmd_alts,
            "swap": self.cmd_swap, "insert": self.cmd_insert,
            "append": self.cmd_append, "remove": self.cmd_remove,
            "validate": self.cmd_validate, "emit": self.cmd_emit,
            "save": self.cmd_save, "info": self.cmd_info,
            "modalities": self.cmd_modalities, "catalog": self.cmd_catalog,
            "saved": self.cmd_saved, "node": self.cmd_node,
            "in": self.cmd_in, "out": self.cmd_out, "goto": self.cmd_goto,
            "help": self.cmd_help, "?": self.cmd_help,
        }

    # --- helpers --------------------------------------------------------
    def _path_tasks(self) -> list[dict]:
        return [self.by_name[n] for n in self.current_path]

    def _print_path(self, names: list[str], with_io: bool = True) -> None:
        if not names:
            print("  (empty path)")
            return
        for i, name in enumerate(names):
            t = self.by_name[name]
            arrow = "  ─►" if i < len(names) - 1 else "    "
            if with_io:
                ins = "+".join(t.get("inputs", []) or ["-"])
                outs = "+".join(t.get("outputs", []) or ["-"])
                print(f"  [{i}] {name:<32}  {ins:>20} → {outs}")
            else:
                print(f"  [{i}] {name}")
            if i < len(names) - 1:
                print(f"      {arrow}")

    def _resolve_task_arg(self, raw: str) -> Optional[str]:
        """User can type partial names. Match case-insensitive prefix."""
        if raw in self.by_name:
            return raw
        cands = [n for n in self.by_name
                 if n.lower().startswith(raw.lower())]
        if len(cands) == 1:
            return cands[0]
        if len(cands) == 0:
            cands = [n for n in self.by_name if raw.lower() in n.lower()]
            if len(cands) == 1:
                return cands[0]
        if len(cands) > 1:
            print(f"  ambiguous '{raw}'; matches: {cands[:8]}")
        else:
            print(f"  unknown task '{raw}'")
        return None

    # --- commands -------------------------------------------------------
    def cmd_goal(self, args: list[str]) -> None:
        """goal SRC DST [--intent TEXT]"""
        if len(args) < 2:
            print("  usage: goal SRC_MODALITY DST_MODALITY [--intent TEXT]")
            return
        src, dst = args[0].upper(), args[1].upper()
        intent = ""
        if "--intent" in args:
            i = args.index("--intent")
            intent = " ".join(args[i + 1:])
        self.search = {"src": src, "dst": dst, "intent": intent}
        raw_paths = td.paths(self.tasks, src, dst, max_depth=5, exclude_any=True)
        ranked = []
        for p in raw_paths:
            path_tasks = [self.by_name[n] for n in p]
            s = score_path(path_tasks, src, dst, intent)
            ranked.append((s, p))
        ranked.sort(key=lambda x: (-x[0], len(x[1]), x[1]))
        self.candidates = ranked
        intent_tag = f" intent={intent!r}" if intent else ""
        print(f"  {len(ranked)} candidate(s) for {src} → {dst}{intent_tag}")
        self.cmd_list(["10"])

    def cmd_list(self, args: list[str]) -> None:
        if not self.candidates:
            print("  no candidates — run `goal SRC DST` first")
            return
        n = int(args[0]) if args else 10
        for i, (s, path) in enumerate(self.candidates[:n]):
            tag = " ★" if i == 0 else "  "
            print(f"  [{i:>2}]{tag} score={s:<5}  {' → '.join(path)}")

    def cmd_show(self, args: list[str]) -> None:
        if not args:
            print("  usage: show I")
            return
        idx = int(args[0])
        if idx >= len(self.candidates):
            print(f"  no candidate #{idx}")
            return
        score, names = self.candidates[idx]
        self.current_path = list(names)
        print(f"  loaded path #{idx} (score {score})")
        self._print_path(self.current_path)

    def cmd_rerank(self, args: list[str]) -> None:
        intent = ""
        if "--intent" in args:
            i = args.index("--intent")
            intent = " ".join(args[i + 1:])
        self.search["intent"] = intent
        src, dst = self.search["src"], self.search["dst"]
        if not src:
            print("  no active search; run `goal SRC DST` first")
            return
        ranked = []
        for _s, p in self.candidates:
            path_tasks = [self.by_name[n] for n in p]
            s = score_path(path_tasks, src, dst, intent)
            ranked.append((s, p))
        ranked.sort(key=lambda x: (-x[0], len(x[1]), x[1]))
        self.candidates = ranked
        print(f"  reranked {len(ranked)} candidates with intent={intent!r}")
        self.cmd_list(["10"])

    def cmd_path(self, args: list[str]) -> None:
        self._print_path(self.current_path)

    def cmd_alts(self, args: list[str]) -> None:
        if not args:
            print("  usage: alts STEP_INDEX")
            return
        i = int(args[0])
        if i < 0 or i >= len(self.current_path):
            print(f"  no step #{i}")
            return
        cur = self.by_name[self.current_path[i]]
        cur_ins = set(cur.get("inputs", []))
        cur_outs = set(cur.get("outputs", []))
        # Alternatives = tasks with matching IO shape, ranked by closeness.
        alts = []
        for t in self.tasks:
            if t["task"] == cur["task"]:
                continue
            t_ins = set(t.get("inputs", []))
            t_outs = set(t.get("outputs", []))
            # in_overlap = how many of current's inputs this task also accepts
            in_overlap = len(cur_ins & t_ins)
            out_overlap = len(cur_outs & t_outs)
            if in_overlap == 0 or out_overlap == 0:
                continue
            # Prefer exact IO match
            shape_score = (
                (3 if cur_ins == t_ins else in_overlap)
                + (3 if cur_outs == t_outs else out_overlap)
            )
            alts.append((shape_score, t))
        alts.sort(key=lambda x: (-x[0], x[1]["task"]))
        if not alts:
            print(f"  no alternatives for step {i} ({cur['task']})")
            return
        print(f"  alternatives for step {i} ({cur['task']} "
              f"[{'+'.join(cur_ins)} → {'+'.join(cur_outs)}]):")
        for shape, t in alts[:15]:
            t_ins = "+".join(t.get("inputs", []) or ["-"])
            t_outs = "+".join(t.get("outputs", []) or ["-"])
            print(f"    shape={shape}  era={t.get('era')}  "
                  f"L{t.get('layer')}  {t['task']:<32}  "
                  f"[{t_ins} → {t_outs}]")

    def cmd_swap(self, args: list[str]) -> None:
        if len(args) < 2:
            print("  usage: swap STEP_INDEX TASK")
            return
        i = int(args[0])
        name = self._resolve_task_arg(" ".join(args[1:]))
        if name is None or i < 0 or i >= len(self.current_path):
            return
        self.current_path[i] = name
        self._print_path(self.current_path)
        self.cmd_validate([])

    def cmd_insert(self, args: list[str]) -> None:
        if len(args) < 2:
            print("  usage: insert STEP_INDEX TASK")
            return
        i = int(args[0])
        name = self._resolve_task_arg(" ".join(args[1:]))
        if name is None:
            return
        self.current_path.insert(i, name)
        self._print_path(self.current_path)
        self.cmd_validate([])

    def cmd_append(self, args: list[str]) -> None:
        if not args:
            print("  usage: append TASK")
            return
        name = self._resolve_task_arg(" ".join(args))
        if name is None:
            return
        self.current_path.append(name)
        self._print_path(self.current_path)
        self.cmd_validate([])

    def cmd_remove(self, args: list[str]) -> None:
        if not args:
            print("  usage: remove STEP_INDEX")
            return
        i = int(args[0])
        if i < 0 or i >= len(self.current_path):
            print(f"  no step #{i}")
            return
        removed = self.current_path.pop(i)
        print(f"  removed: {removed}")
        self._print_path(self.current_path)
        self.cmd_validate([])

    def cmd_validate(self, args: list[str]) -> None:
        if len(self.current_path) < 2:
            return
        breaks = []
        for i in range(len(self.current_path) - 1):
            a = self.by_name[self.current_path[i]]
            b = self.by_name[self.current_path[i + 1]]
            if not set(a.get("outputs", [])) & set(b.get("inputs", [])):
                breaks.append((i, a["task"], b["task"]))
        if breaks:
            print("  ⚠ broken edges:")
            for i, a, b in breaks:
                print(f"      [{i}→{i+1}] {a} outputs={self.by_name[a]['outputs']} "
                      f"vs {b} inputs={self.by_name[b]['inputs']}")
        else:
            print("  ✓ path edges consistent")

    def cmd_emit(self, args: list[str]) -> None:
        name = args[0] if args else "untitled"
        if not self.current_path:
            print("  (empty path — load one with `show I`)")
            return
        wf = emit_workflow(self._path_tasks(), name=name)
        print(json.dumps(wf, indent=2))

    def cmd_save(self, args: list[str]) -> None:
        if not args:
            print("  usage: save NAME")
            return
        name = args[0]
        self.saved[name] = list(self.current_path)
        print(f"  saved as {name} ({len(self.current_path)} steps)")

    def cmd_info(self, args: list[str]) -> None:
        if not args:
            print("  usage: info TASK")
            return
        name = self._resolve_task_arg(" ".join(args))
        if name is None:
            return
        t = self.by_name[name]
        print(f"  {t['task']}")
        print(f"    category : {t.get('category')}")
        print(f"    layer    : L{t.get('layer')}     era: {t.get('era')}  "
              f"year: {t.get('year')}")
        print(f"    inputs   : {t.get('inputs')}")
        print(f"    outputs  : {t.get('outputs')}")
        print(f"    exemplars: {', '.join(t.get('exemplars', []))}")
        print(f"    role     : {t.get('role_in_avatar')}")
        print(f"    notes    : {t.get('notes')}")
        if t.get("depends_on"):
            print(f"    depends_on: {t['depends_on']}")
        if t.get("enables"):
            print(f"    enables  : {t['enables']}")

    def cmd_modalities(self, args: list[str]) -> None:
        ins = sorted({m for t in self.tasks for m in t.get("inputs", [])})
        outs = sorted({m for t in self.tasks for m in t.get("outputs", [])})
        print(f"  inputs : {ins}")
        print(f"  outputs: {outs}")

    def cmd_catalog(self, args: list[str]) -> None:
        pattern = args[0] if args else ""
        rx = re.compile(pattern, re.I) if pattern else None
        for t in sorted(self.tasks, key=lambda t: (t.get("layer", 99), t["task"])):
            if rx and not rx.search(t["task"]):
                continue
            print(f"  L{t.get('layer')}  era{t.get('era')}  {t['task']:<32}  "
                  f"{t.get('inputs')} → {t.get('outputs')}")

    def cmd_saved(self, args: list[str]) -> None:
        if not self.saved:
            print("  (none saved)")
            return
        for name, path in self.saved.items():
            print(f"  {name}: {' → '.join(path)}")

    # --- DAG mode -------------------------------------------------------
    def cmd_node(self, args: list[str]) -> None:
        if not args:
            print("  usage: node TASK")
            return
        name = self._resolve_task_arg(" ".join(args))
        if name is None:
            return
        self.dag_cursor = name
        t = self.by_name[name]
        print(f"  at: {name}  [{t.get('inputs')} → {t.get('outputs')}]")

    def cmd_in(self, args: list[str]) -> None:
        if not self.dag_cursor:
            print("  no DAG cursor; set with `node TASK`")
            return
        cur = self.by_name[self.dag_cursor]
        cur_ins = set(cur.get("inputs", []))
        parents = []
        for t in self.tasks:
            if t["task"] == cur["task"]:
                continue
            shared = set(t.get("outputs", [])) & cur_ins
            if shared:
                parents.append((sorted(shared), t["task"]))
        print(f"  PARENTS of {self.dag_cursor} ({len(parents)}):")
        for mods, name in sorted(parents):
            print(f"    via {','.join(mods):<20} ← {name}")

    def cmd_out(self, args: list[str]) -> None:
        if not self.dag_cursor:
            print("  no DAG cursor; set with `node TASK`")
            return
        cur = self.by_name[self.dag_cursor]
        cur_outs = set(cur.get("outputs", []))
        children = []
        for t in self.tasks:
            if t["task"] == cur["task"]:
                continue
            shared = cur_outs & set(t.get("inputs", []))
            if shared:
                children.append((sorted(shared), t["task"]))
        print(f"  CHILDREN of {self.dag_cursor} ({len(children)}):")
        for mods, name in sorted(children):
            print(f"    via {','.join(mods):<20} → {name}")

    def cmd_goto(self, args: list[str]) -> None:
        self.cmd_node(args)

    def cmd_help(self, args: list[str]) -> None:
        print(__doc__.split("REPL commands:")[1].split("Scoring heuristic")[0])

    # --- loop -----------------------------------------------------------
    def run(self) -> None:
        print(f"path_builder — {len(self.tasks)} tasks loaded. "
              "type `help` for commands, `quit` to exit.")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not line:
                continue
            if line in ("quit", "exit"):
                return
            parts = line.split()
            cmd, args = parts[0], parts[1:]
            handler = self.dispatch.get(cmd)
            if not handler:
                print(f"  unknown command: {cmd!r} — type `help`")
                continue
            try:
                handler(args)
            except Exception as e:
                print(f"  error: {type(e).__name__}: {e}")


# ---- non-interactive modes ---------------------------------------------

def cmd_rank(args):
    tasks = td.load(Path(args.jsonl))
    by_name = td.by_name(tasks)
    raw = td.paths(tasks, args.src.upper(), args.dst.upper(),
                   max_depth=args.max_depth, exclude_any=args.no_any)
    ranked = []
    for p in raw:
        s = score_path([by_name[n] for n in p],
                       args.src.upper(), args.dst.upper(), args.intent or "")
        ranked.append((s, p))
    ranked.sort(key=lambda x: (-x[0], len(x[1]), x[1]))
    print(f"# {len(ranked)} pipelines {args.src} → {args.dst}  "
          f"intent={args.intent!r}")
    for i, (s, p) in enumerate(ranked[:args.top]):
        tag = " ★" if i == 0 else "  "
        print(f"[{i:>2}]{tag} score={s:<5}  {' → '.join(p)}")


def cmd_build(args):
    tasks = td.load(Path(args.jsonl))
    by_name = td.by_name(tasks)
    path_tasks = []
    for name in args.steps:
        if name not in by_name:
            print(f"unknown task: {name!r}", file=sys.stderr)
            sys.exit(2)
        path_tasks.append(by_name[name])
    wf = emit_workflow(path_tasks, name=args.name or "untitled",
                       description=args.description or "")
    # Validate edges
    breaks = []
    for i in range(len(path_tasks) - 1):
        a = path_tasks[i]
        b = path_tasks[i + 1]
        if not set(a.get("outputs", [])) & set(b.get("inputs", [])):
            breaks.append((i, a["task"], b["task"]))
    if breaks:
        for i, a, b in breaks:
            print(f"warning: broken edge [{i}→{i+1}] {a} → {b}", file=sys.stderr)
    print(json.dumps(wf, indent=2))


def main():
    ap = argparse.ArgumentParser(prog="path_builder.py")
    ap.add_argument("--jsonl", default=str(HERE / "hf_task_evolution.jsonl"))
    sub = ap.add_subparsers(dest="cmd")

    p_rank = sub.add_parser("rank", help="ranked one-shot enumeration")
    p_rank.add_argument("src"); p_rank.add_argument("dst")
    p_rank.add_argument("--intent", default="")
    p_rank.add_argument("--top", type=int, default=20)
    p_rank.add_argument("--max-depth", type=int, default=5)
    p_rank.add_argument("--no-any", action="store_true", default=True)

    p_build = sub.add_parser("build", help="build workflow JSON from explicit steps")
    p_build.add_argument("steps", nargs="+")
    p_build.add_argument("--name", default="untitled")
    p_build.add_argument("--description", default="")

    args = ap.parse_args()
    if args.cmd == "rank":
        cmd_rank(args)
    elif args.cmd == "build":
        cmd_build(args)
    else:
        REPL(Path(args.jsonl)).run()


if __name__ == "__main__":
    main()
