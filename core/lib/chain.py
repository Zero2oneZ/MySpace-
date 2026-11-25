#!/usr/bin/env python3
"""cc chain executor — parse a structured chain spec and execute it.

Grammar (recursive):
    CHAIN  ::= '{' EXPR '}'
    EXPR   ::= TERM (OP TERM)*
    TERM   ::= STEP | BASHSTEP | GROUP | CCGROUP
    STEP   ::= '{' '"' TEXT '"' '}'        # leaf — single model prompt
    BASH   ::= '{' 'bash' '"' TEXT '"' '}' # leaf — run a bash command, stdout = output
    GROUP  ::= '{' EXPR '}'                # nested expr; inherits context
    CCGROUP::= 'cc' GROUP                  # nested expr; ISOLATED — no inherited context
    OP     ::= '|' | '+' | '-'

Operator semantics inside an expression (left-to-right evaluation):

    A | B   pipe       — B receives A's output as prepended context
    A + B   parallel   — A and B run concurrently; outputs join with "\\n---\\n"
    A - B   sequential — B runs after A but with NO context (reset)

The `cc` keyword preceding a group ISOLATES that subexpression's input
context. The subgroup still emits an output that participates in the
enclosing expression normally.

Every leaf (model prompt AND bash) is content-addressed through the unified
cell store: its output becomes a `cell` (cid = blake3(content)), and the
(recipe = upstream content + op + params) is checked against the transposition
table (`recipes`) BEFORE execution. A hit short-circuits with zero model
calls / zero bash runs — no repeated work, no wasted tokens. Bash cells
dry-run (echo the command) unless --trust-bash is passed.

Examples (informal):
    {"hello"}                          → single step
    {{"A"} | {"B"}}                    → pipe A→B
    {bash "git log -1"}                → run bash, stdout is the cell output
    {{"what changed?"} | {bash "git diff"}}  → model then bash, piped
    {{"A"} + {"B"} + {"C"}}            → three steps in parallel
    {{"A"} | {"B"} + {"C"} | {"D"}}   → A; then B and C in parallel both
                                          using A as context; then D with
                                          B+C combined as context
    {{"A"} | cc {{"B"} | {"C"}}}      → A runs; B starts fresh (no A
                                          context); C uses B's output;
                                          the cc-group emits C's output

Usage:
    chain.py <spec>          # execute
    chain.py --parse <spec>  # just parse + print AST, don't execute
    chain.py --dry <spec>    # parse + print execution plan, don't call models
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import List, Optional, Union

# Sibling cell_store.py is the unified content-addressed cell substrate.
# Ensure the lib dir is importable whether chain.py runs as a script or is
# imported by loop.py / cc.sh.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import cell_store  # type: ignore
except Exception:  # cell_store is optional — chain still runs without the cache
    cell_store = None  # type: ignore


# ---- tokenizer ----------------------------------------------------------

@dataclass
class Token:
    kind: str        # 'LBRACE' | 'RBRACE' | 'STRING' | 'OP' | 'CC' | 'BASH'
    value: str
    pos: int


def tokenize(spec: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    n = len(spec)

    while i < n:
        c = spec[i]

        # whitespace
        if c.isspace():
            i += 1
            continue

        # braces
        if c == '{':
            tokens.append(Token('LBRACE', '{', i))
            i += 1
            continue
        if c == '}':
            tokens.append(Token('RBRACE', '}', i))
            i += 1
            continue

        # operators
        if c in '|+-':
            tokens.append(Token('OP', c, i))
            i += 1
            continue

        # quoted string — supports backslash-escaped \" and \\
        if c == '"':
            j = i + 1
            buf = []
            while j < n:
                cc = spec[j]
                if cc == '\\' and j + 1 < n:
                    nxt = spec[j + 1]
                    buf.append(nxt)
                    j += 2
                    continue
                if cc == '"':
                    break
                buf.append(cc)
                j += 1
            if j >= n:
                raise ChainParseError(f"unterminated string starting at position {i}")
            tokens.append(Token('STRING', ''.join(buf), i))
            i = j + 1
            continue

        # cc keyword — must be followed by whitespace or '{'
        if c == 'c' and i + 1 < n and spec[i + 1] == 'c':
            after = spec[i + 2] if i + 2 < n else ''
            if after.isspace() or after == '{' or after == '':
                tokens.append(Token('CC', 'cc', i))
                i += 2
                continue

        # bash keyword — {bash "cmd"} leaf; must be followed by whitespace
        if spec.startswith('bash', i):
            after = spec[i + 4] if i + 4 < n else ''
            if after.isspace() or after == '':
                tokens.append(Token('BASH', 'bash', i))
                i += 4
                continue

        raise ChainParseError(f"unexpected character {c!r} at position {i}")

    return tokens


# ---- AST ----------------------------------------------------------------

@dataclass
class Step:
    text: str


@dataclass
class BashStep:
    """A leaf that runs a bash command; its stdout becomes the cell output."""
    cmd: str


@dataclass
class Group:
    expr: 'Expr'
    isolated: bool = False    # True if preceded by `cc`


@dataclass
class Expr:
    """Flat sequence: terms[0], ops[0], terms[1], ops[1], terms[2], ...
    so len(ops) == len(terms) - 1. First term has no preceding operator."""
    terms: List[Union[Step, Group]] = field(default_factory=list)
    ops: List[str] = field(default_factory=list)


class ChainParseError(ValueError):
    pass


# ---- parser -------------------------------------------------------------

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.i = 0

    def peek(self, offset: int = 0) -> Optional[Token]:
        idx = self.i + offset
        return self.tokens[idx] if idx < len(self.tokens) else None

    def consume(self, kind: str) -> Token:
        t = self.peek()
        if t is None or t.kind != kind:
            got = f"{t.kind}({t.value!r})" if t else "EOF"
            raise ChainParseError(f"expected {kind}, got {got}")
        self.i += 1
        return t

    # CHAIN ::= '{' EXPR '}'   — but for forgiveness we also accept a bare
    # EXPR (no outer braces) at the top level. Either way, we ALWAYS check
    # that all tokens were consumed — leftovers (e.g. two adjacent steps
    # without an operator) are a parse error.
    def parse_chain(self) -> Expr:
        if self.peek() is None:
            raise ChainParseError("empty chain spec")
        # Top-level: if it starts with { and the matching close is at the end,
        # treat the whole thing as a group's contents.
        if self.peek().kind == 'LBRACE':
            # Look ahead: is this { followed immediately by a STRING (leaf step)
            # or BASH (leaf bash step)? If so, top level is implicit — don't
            # strip outer braces.
            if self.peek(1) is not None and self.peek(1).kind in ('STRING', 'BASH'):
                expr = self.parse_expr()
            else:
                # Otherwise treat outermost { } as the chain wrapper
                self.consume('LBRACE')
                expr = self.parse_expr()
                self.consume('RBRACE')
        else:
            # No outer braces — just an expression
            expr = self.parse_expr()
        if self.peek() is not None:
            t = self.peek()
            raise ChainParseError(
                f"unexpected token after chain at pos {t.pos}: "
                f"{t.kind}({t.value!r}) — adjacent terms need an operator | + or -"
            )
        return expr

    # EXPR ::= TERM (OP TERM)*
    def parse_expr(self) -> Expr:
        expr = Expr()
        expr.terms.append(self.parse_term())
        while self.peek() is not None and self.peek().kind == 'OP':
            op = self.consume('OP').value
            expr.ops.append(op)
            expr.terms.append(self.parse_term())
        return expr

    # TERM ::= STEP | GROUP | CCGROUP
    def parse_term(self) -> Union[Step, Group]:
        t = self.peek()
        if t is None:
            raise ChainParseError("expected step or group, got EOF")
        if t.kind == 'CC':
            self.consume('CC')
            grp = self.parse_group()
            grp.isolated = True
            return grp
        if t.kind == 'LBRACE':
            return self.parse_step_or_group()
        raise ChainParseError(f"expected step or group at pos {t.pos}, got {t.kind}")

    # Disambiguate STEP vs BASHSTEP vs GROUP by lookahead.
    # STEP  := '{' STRING '}'
    # BASH  := '{' 'bash' STRING '}'
    # GROUP := '{' EXPR '}'    (where EXPR starts with LBRACE or CC)
    def parse_step_or_group(self) -> Union[Step, BashStep, Group]:
        self.consume('LBRACE')
        t = self.peek()
        if t is not None and t.kind == 'BASH':
            self.consume('BASH')
            cmd_tok = self.consume('STRING')
            self.consume('RBRACE')
            return BashStep(cmd_tok.value)
        if t is not None and t.kind == 'STRING':
            text_tok = self.consume('STRING')
            self.consume('RBRACE')
            return Step(text_tok.value)
        # otherwise it's a group with a nested expression
        expr = self.parse_expr()
        self.consume('RBRACE')
        return Group(expr=expr, isolated=False)

    # CCGROUP requires GROUP next (not a bare STEP — meaningless to isolate)
    def parse_group(self) -> Group:
        t = self.peek()
        if t is None or t.kind != 'LBRACE':
            raise ChainParseError(f"`cc` must be followed by a group {{...}} at pos {t.pos if t else 'EOF'}")
        node = self.parse_step_or_group()
        if isinstance(node, Step):
            # `cc {"single step"}` — isolation is a no-op for a leaf, but accept it.
            # Wrap in a trivial group so the AST shape is consistent.
            return Group(expr=Expr(terms=[node], ops=[]), isolated=False)
        return node


def parse(spec: str) -> Expr:
    return Parser(tokenize(spec)).parse_chain()


# ---- evaluator ----------------------------------------------------------

CC_BIN = os.environ.get("CC_BIN", "cc")
CHAIN_TIMEOUT = int(os.environ.get("CC_CHAIN_STEP_TIMEOUT", "180"))
CC_CACHE_DIR = Path(os.environ.get("CC_CACHE", str(Path.home() / ".cc" / "cache")))


def _cache_snapshot() -> set:
    """Return set of cache file basenames currently on disk."""
    try:
        return {p.name for p in CC_CACHE_DIR.iterdir() if p.suffix == ".txt"}
    except (FileNotFoundError, PermissionError):
        return set()


# Counter for monotonically-increasing step indices across the whole chain.
# (The AST may interleave concurrent steps, but step_idx is assigned at
# call_model entry so the DB log shows true call order.)
_step_counter = 0
_step_lock = Lock()


@dataclass
class StepRecord:
    step_idx: int
    op: str         # '|' '+' '-' or 'start' for the very first step
    isolated: bool
    context_in: str
    prompt: str
    output: str
    ms_elapsed: int
    from_cache: bool
    cell_cid: str = ""      # canonical output cell in the global cells table
    recipe_cid: str = ""    # the transposition-table key that produced this step


# Records buffered until the chain ends, then flushed to DB in order.
_records: List[StepRecord] = []
_records_lock = Lock()

# Bash cells dry-run (echo the command, don't execute) unless --trust-bash.
TRUST_BASH = False


def _cell_meta() -> dict:
    """Tag cells with scope inherited from cc's exported env vars."""
    return {
        "intent": os.environ.get("CC_CHAIN_INTENT", ""),
        "source": "chain",
        "project": os.environ.get("CC_SCOPE_LOCAL_PROJECT")
                   or os.environ.get("CC_SCOPE_GLOBAL_PROJECT", ""),
        "scope_cwd": os.environ.get("CC_SCOPE_CWD", ""),
        "agent_uuid": os.environ.get("CC_AGENT_UUID", ""),
    }


def _record(op: str, isolated: bool, context: str, prompt: str, output: str,
            ms: int, from_cache: bool, cell_cid: str = "",
            recipe_cid: str = "") -> None:
    """Append a StepRecord (thread-safe)."""
    with _step_lock:
        global _step_counter
        idx = _step_counter
        _step_counter += 1
    rec = StepRecord(
        step_idx=idx, op=op, isolated=isolated,
        context_in=context, prompt=prompt, output=output,
        ms_elapsed=ms, from_cache=from_cache,
        cell_cid=cell_cid, recipe_cid=recipe_cid,
    )
    with _records_lock:
        _records.append(rec)


def _store_io_cells(kind: str, output: str, prompt_text: str,
                    recipe_cid: str, op: str, model: str,
                    ms: int, meta: dict) -> str:
    """On a cache MISS: store the output cell + prompt cell + recipe + edge.
    Returns the output cell cid."""
    out_cid = cell_store.add_cell(
        "response" if kind == "model" else "bashout", output,
        intent=meta["intent"], source=meta["source"], project=meta["project"],
        scope_cwd=meta["scope_cwd"], agent_uuid=meta["agent_uuid"])
    p_cid = cell_store.add_cell(
        "prompt", prompt_text,
        intent=meta["intent"], source=meta["source"], project=meta["project"],
        scope_cwd=meta["scope_cwd"], agent_uuid=meta["agent_uuid"])
    cell_store.edge_add(p_cid, out_cid, "produced")
    cell_store.recipe_store(recipe_cid, out_cid, kind, op,
                            intent=meta["intent"], model=model, dt_ms=ms)
    return out_cid


def call_model(prompt: str, context: str,
               op: str = "start", isolated: bool = False) -> str:
    """Shell out to cc tiny — but only on a recipe cache MISS. On a hit the
    model is never called (zero cloud calls). Output is stored as a cell."""
    full = (context.rstrip() + "\n\n" + prompt) if context else prompt
    model = os.environ.get("CC_TINY_MODEL", "")
    meta = _cell_meta()

    # ── transposition-table lookup: identical recipe → identical output ──
    if cell_store is not None:
        rc = cell_store.recipe_hash(full, op, "model", model)
        out_cid = cell_store.recipe_lookup(rc)
        if out_cid is not None:
            cell_store.recipe_hit(rc)
            output = cell_store.cell_content(out_cid) or ""
            _record(op, isolated, context, prompt, output, 0, True, out_cid, rc)
            return output

    # ── miss: actually call the model ──
    before = _cache_snapshot()
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            [CC_BIN, "tiny", full],
            capture_output=True,
            text=True,
            timeout=CHAIN_TIMEOUT,
        )
        output = r.stdout.rstrip()
    except subprocess.TimeoutExpired:
        output = "[CHAIN: timeout]"
    except FileNotFoundError:
        output = f"[CHAIN: '{CC_BIN}' not on PATH]"
    ms = int((time.monotonic() - t0) * 1000)

    out_cid, rc = "", ""
    if cell_store is not None:
        rc = cell_store.recipe_hash(full, op, "model", model)
        out_cid = _store_io_cells("model", output, full, rc, op, model, ms, meta)
        from_cache = False
    else:
        # No cell_store — fall back to the file-cache snapshot heuristic.
        after = _cache_snapshot()
        from_cache = len(after - before) == 0

    _record(op, isolated, context, prompt, output, ms, from_cache, out_cid, rc)
    return output


def call_bash(cmd: str, context: str,
              op: str = "start", isolated: bool = False) -> str:
    """Run a bash command; stdout becomes the cell output. Context (the piped
    upstream output) is fed to the command's STDIN so `{"A"} | {bash "grep x"}`
    works naturally. Recipe-cached like call_model. Dry-runs unless TRUST_BASH."""
    meta = _cell_meta()
    # context is part of the recipe — same cmd on different input differs.
    rc = cell_store.recipe_hash(context, op, "bash", cmd) if cell_store else ""

    if cell_store is not None:
        out_cid = cell_store.recipe_lookup(rc)
        if out_cid is not None:
            cell_store.recipe_hit(rc)
            output = cell_store.cell_content(out_cid) or ""
            _record(op, isolated, context, cmd, output, 0, True, out_cid, rc)
            return output

    if not TRUST_BASH:
        output = f"[dry-run] {cmd}"
        _record(op, isolated, context, cmd, output, 0, False, "", rc)
        return output

    t0 = time.monotonic()
    try:
        r = subprocess.run(
            ["bash", "-c", cmd],
            input=context, capture_output=True, text=True,
            timeout=CHAIN_TIMEOUT,
        )
        output = r.stdout.rstrip()
    except subprocess.TimeoutExpired:
        output = "[CHAIN: timeout]"
    ms = int((time.monotonic() - t0) * 1000)

    out_cid = ""
    if cell_store is not None:
        out_cid = _store_io_cells("bash", output, cmd, rc, op, "bash", ms, meta)
    _record(op, isolated, context, cmd, output, ms, False, out_cid, rc)
    return output


def _db_path() -> Optional[Path]:
    """Resolve the local DB path for chain persistence. Returns None if
    we shouldn't persist (no local scope). Checks the env vars cc exports,
    falling back to walking up from cwd for .cc/local.db."""
    for var in ("CC_LOCAL_DB", "CC_SCOPE_LOCAL_DB"):
        v = os.environ.get(var, "").strip()
        if v and Path(v).exists():
            return Path(v)
    # Fall back to filesystem walk — matches cc's find_local_db
    d = Path.cwd().resolve()
    while True:
        cand = d / ".cc" / "local.db"
        if cand.is_file():
            return cand
        if d.parent == d:
            return None
        d = d.parent


def _db_cli(args: list) -> Optional[str]:
    """Invoke db.py with CC_DB pointing at the local DB. Returns stdout
    on success, None on failure (silently — persistence is best-effort)."""
    db_path = _db_path()
    if db_path is None:
        return None
    db_lib = Path(__file__).resolve().parent / "db.py"
    if not db_lib.exists():
        return None
    try:
        r = subprocess.run(
            [sys.executable, str(db_lib)] + args,
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "CC_DB": str(db_path)},
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def persist_start(spec: str) -> Optional[int]:
    """Insert chain_runs row; return run_id, or None if not persisting."""
    out = _db_cli([
        "chain-run-start",
        spec,
        os.environ.get("CC_AGENT_UUID", ""),
    ])
    if out is None:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def persist_step(run_id: int, rec: StepRecord) -> None:
    """Best-effort: persist one step. Truncate very long fields so the DB
    doesn't bloat from a single bad chain."""
    ctx = rec.context_in if len(rec.context_in) <= 8000 else rec.context_in[:8000] + "...[truncated]"
    out = rec.output if len(rec.output) <= 16000 else rec.output[:16000] + "...[truncated]"
    _db_cli([
        "chain-run-step-add",
        str(run_id), str(rec.step_idx), rec.op,
        "1" if rec.isolated else "0",
        ctx, rec.prompt, out,
        str(rec.ms_elapsed),
        "1" if rec.from_cache else "0",
        rec.cell_cid or "",
        rec.recipe_cid or "",
    ])


def persist_end(run_id: int, status: str) -> None:
    _db_cli(["chain-run-end", str(run_id), status])


def eval_node(node, context: str, op: str = "start", isolated: bool = False) -> str:
    if isinstance(node, Step):
        return call_model(node.text, context, op=op, isolated=isolated)
    if isinstance(node, BashStep):
        return call_bash(node.cmd, context, op=op, isolated=isolated)
    if isinstance(node, Group):
        # If isolated (cc-group), strip incoming context
        inner_ctx = "" if node.isolated else context
        return eval_expr(node.expr, inner_ctx, parent_isolated=node.isolated or isolated)
    raise TypeError(f"unknown AST node type: {type(node).__name__}")


def eval_expr(expr: Expr, incoming_context: str,
              parent_isolated: bool = False) -> str:
    # Group consecutive '+' terms into parallel batches. The boundary
    # operator of each batch (the op that precedes its first term, or
    # None for the very first batch) determines whether the batch sees
    # the previous output as context.
    batches: List[tuple] = []  # (boundary_op, [terms])
    current_batch: List = [expr.terms[0]]
    current_boundary: Optional[str] = None
    for op, term in zip(expr.ops, expr.terms[1:]):
        if op == '+':
            current_batch.append(term)
        else:
            batches.append((current_boundary, current_batch))
            current_batch = [term]
            current_boundary = op
    batches.append((current_boundary, current_batch))

    last_output: str = ""
    for batch_idx, (boundary, terms) in enumerate(batches):
        # Determine context for this batch
        if boundary == '|':
            ctx = last_output
        elif boundary == '-':
            ctx = ""
        else:  # boundary is None — first batch — use incoming context
            ctx = incoming_context

        # op string passed to call_model for the DB record
        op_for_record = boundary if boundary is not None else "start"

        if len(terms) == 1:
            out = eval_node(terms[0], ctx, op=op_for_record, isolated=parent_isolated)
        else:
            # Parallel — every term in this batch has op '+' (the boundary
            # op is the FIRST term's op; subsequent terms in the batch all
            # came from '+' joins).
            terms_with_op = [(t, op_for_record if i == 0 else '+')
                             for i, t in enumerate(terms)]
            with ThreadPoolExecutor(max_workers=len(terms)) as ex:
                outs = list(ex.map(
                    lambda pair: eval_node(pair[0], ctx, op=pair[1], isolated=parent_isolated),
                    terms_with_op,
                ))
            out = "\n\n---\n\n".join(outs)

        last_output = out
        # Stream the batch's joined output to stdout immediately.
        sys.stdout.write(out)
        sys.stdout.write("\n")
        if batch_idx < len(batches) - 1:
            # Separator between batches
            sys.stdout.write("\n=== --- ===\n\n")
        sys.stdout.flush()

    return last_output


# ---- introspection helpers (for --parse / --dry) ------------------------

def ast_to_dict(node):
    if isinstance(node, Step):
        return {"type": "Step", "text": node.text}
    if isinstance(node, BashStep):
        return {"type": "BashStep", "cmd": node.cmd}
    if isinstance(node, Group):
        return {"type": "Group", "isolated": node.isolated,
                "expr": ast_to_dict(node.expr)}
    if isinstance(node, Expr):
        return {
            "type": "Expr",
            "terms": [ast_to_dict(t) for t in node.terms],
            "ops": node.ops,
        }
    raise TypeError(type(node).__name__)


def render_plan(expr: Expr, depth: int = 0, label: str = "expr") -> List[str]:
    """Produce a human-readable execution plan."""
    out = []
    pad = "  " * depth
    out.append(f"{pad}{label}: {len(expr.terms)} term(s)")
    # describe batches
    batches: List[tuple] = []
    current_batch = [expr.terms[0]]
    current_boundary = None
    for op, term in zip(expr.ops, expr.terms[1:]):
        if op == '+':
            current_batch.append(term)
        else:
            batches.append((current_boundary, current_batch))
            current_batch = [term]
            current_boundary = op
    batches.append((current_boundary, current_batch))
    for i, (b, terms) in enumerate(batches):
        kind = "parallel" if len(terms) > 1 else "single"
        marker = b or "start"
        out.append(f"{pad}  batch {i} [{marker}] {kind} × {len(terms)}")
        for j, t in enumerate(terms):
            if isinstance(t, Step):
                snip = t.text[:50] + ('…' if len(t.text) > 50 else '')
                out.append(f"{pad}    term {j}: STEP {snip!r}")
            elif isinstance(t, BashStep):
                snip = t.cmd[:50] + ('…' if len(t.cmd) > 50 else '')
                trust = "" if TRUST_BASH else " [dry-run]"
                out.append(f"{pad}    term {j}: BASH {snip!r}{trust}")
            elif isinstance(t, Group):
                tag = "cc-group (isolated)" if t.isolated else "group"
                out.append(f"{pad}    term {j}: {tag}")
                out.extend(render_plan(t.expr, depth + 3, "  "))
    return out


# ---- CLI ----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(prog="chain.py", description="cc chain executor")
    ap.add_argument("spec", nargs='+', help="chain spec")
    ap.add_argument("--parse", action="store_true", help="print AST as JSON and exit")
    ap.add_argument("--dry", action="store_true", help="print execution plan and exit")
    ap.add_argument("--trust-bash", action="store_true",
                    help="actually execute bash cells (default: dry-run)")
    args = ap.parse_args()

    global TRUST_BASH
    TRUST_BASH = args.trust_bash

    spec = " ".join(args.spec)

    try:
        expr = parse(spec)
    except ChainParseError as e:
        print(f"chain parse error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.parse:
        print(json.dumps(ast_to_dict(expr), indent=2))
        return
    if args.dry:
        for line in render_plan(expr):
            print(line)
        return

    # Execute — record start, run, then flush all step records to DB.
    run_id = persist_start(spec)
    status = "ok"
    try:
        eval_expr(expr, incoming_context="")
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    except Exception as e:
        status = "failed"
        print(f"chain error: {e}", file=sys.stderr)
    finally:
        if run_id is not None:
            for rec in _records:
                persist_step(run_id, rec)
            persist_end(run_id, status)
            print(
                f"\n--- chain run #{run_id} complete: {len(_records)} step(s), "
                f"status={status} ---",
                file=sys.stderr,
            )
        else:
            print("", file=sys.stderr)
            print(
                f"--- chain complete: {len(_records)} step(s), status={status} "
                "(no persistence — CC_LOCAL_DB unset or missing) ---",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
