"""loop — the autoregressive outer transformer for cc.

cc composes a prompt from retrieved cells (attention), dispatches it to the
cloud FFN, awaits the response, stores it as a cell, re-attends, and
re-dispatches — until the task is answered or a fixpoint / step cap is hit.

The model is nothing but the non-linear activation in the middle (the FFN).
Everything around it — retrieval, composition, caching, the autoregressive
loop — is deterministic and per-intent (the "weights" live in
attention_programs). Composition + retrieval cost ZERO cloud calls; the FFN
fires only on a genuine recipe cache miss.

Response protocol (the model speaks this):
  ANSWER: <text>   → task is done; <text> is the final answer; STOP.
  BASH: <cmd>      → run the bash command (recipe-cached), feed stdout back.
  <anything else>  → a reasoning step; store and continue.

Usage:
  loop.py run [--intent default] [--max-steps N] [--trust-bash] "<task>"
  loop.py show <run_id>
  loop.py list [n]

Model selection (in priority order):
  CC_LOOP_MODEL  → CC_TINY_MODEL  → "qwen2.5:3b"
  (glm-5.2:cloud / CC_MODEL is honored via CC_LOOP_MODEL once it is actually
   served at CC_OLLAMA_URL; the loop mechanics are model-agnostic.)
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_store  # type: ignore

DB_PATH = Path(os.environ.get("CC_GLOBAL_DB", str(Path.home() / ".cc" / "cc.db")))
OLLAMA_URL = os.environ.get("CC_OLLAMA_URL", "http://localhost:11434")
MODEL = (os.environ.get("CC_LOOP_MODEL")
         or os.environ.get("CC_TINY_MODEL")
         or "qwen2.5:3b")
TIMEOUT = int(os.environ.get("CC_LOOP_TIMEOUT",
                            os.environ.get("CC_MODEL_TIMEOUT", "120")))
KEEP_ALIVE = os.environ.get("CC_KEEP_ALIVE", "30s")

# ---- the default attention program (seeded on first use) -----------------
DEFAULT_PROGRAM = {
    "retrieve": {"top_k": 5},
    "template": "default",
    "stop": {"max_steps": 5, "answer_prefix": "ANSWER:", "fixpoint": True},
}

DEFAULT_TEMPLATE = """You are an autonomous agent solving a task one step at a time.

TASK:
{task}

RELEVANT PRIOR WORK (retrieved from the cell store):
{retrieved}

PRIOR STEP RESPONSE:
{last_response}

You may use bash to inspect the working directory ({cwd}). Respond with EXACTLY ONE of:
  BASH: <command>            — run a bash command; its stdout becomes the next context
  ANSWER: <final answer>     — the task is fully solved; stop here
If you need information (git log, file listing, etc.), emit a BASH: step first."""


# ---- attention program store (direct sqlite on the global db) -----------
def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def program_get(intent: str) -> dict:
    """Return the program spec, seeding DEFAULT if absent."""
    with _conn() as c:
        r = c.execute("SELECT spec_json FROM attention_programs WHERE intent=?",
                      (intent,)).fetchone()
    if r:
        try:
            return json.loads(r["spec_json"])
        except Exception:
            pass
    if intent == "default":
        program_upsert("default", DEFAULT_PROGRAM)
        return DEFAULT_PROGRAM
    # fall back to default rather than failing
    return DEFAULT_PROGRAM


def program_upsert(intent: str, spec: dict) -> None:
    with _conn() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS attention_programs("
            "intent TEXT PRIMARY KEY, spec_json TEXT NOT NULL, "
            "created_at TEXT DEFAULT (datetime('now')))")
        c.execute("INSERT OR REPLACE INTO attention_programs(intent, spec_json) VALUES(?,?)",
                  (intent, json.dumps(spec)))
        c.commit()


# ---- dispatch (the FFN) --------------------------------------------------
def ollama_generate(model: str, prompt: str) -> str:
    """Deterministic ollama /api/generate (temp=0, seed=42), DONE stripped."""
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0, "seed": 42}, "keep_alive": KEEP_ALIVE,
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        j = json.loads(r.read().decode("utf-8"))
    text = j.get("response", "") or ""
    # strip a trailing DONE token (mirrors cc.sh model_call contract)
    if text.rstrip().endswith("DONE"):
        text = text.rstrip()[:-4].rstrip()
    return text


def dispatch_model(prompt: str, intent: str, meta: dict) -> tuple:
    """Compose→cache→(miss)→ollama. Returns (output_cid, output, from_cache)."""
    rc = cell_store.recipe_hash(prompt, "loop-model", "model", MODEL)

    def _exec() -> str:
        return ollama_generate(MODEL, prompt)

    return cell_store.cached_execute(
        rc, "model", "loop-model", _exec,
        intent=intent, model=MODEL,
        project=meta["project"], scope_cwd=meta["scope_cwd"],
        agent_uuid=meta["agent_uuid"])


def run_bash(cmd: str, context: str, intent: str, meta: dict) -> tuple:
    """Run a bash command, recipe-cached. Returns (output_cid, output, from_cache)."""
    rc = cell_store.recipe_hash(context, "loop-bash", "bash", cmd)

    def _exec() -> str:
        r = subprocess.run(["bash", "-c", cmd], input=context,
                           capture_output=True, text=True,
                           timeout=int(os.environ.get("CC_CHAIN_STEP_TIMEOUT", "180")))
        return r.stdout.rstrip()

    return cell_store.cached_execute(
        rc, "bash", "loop-bash", _exec,
        intent=intent, model="bash",
        project=meta["project"], scope_cwd=meta["scope_cwd"],
        agent_uuid=meta["agent_uuid"])


# ---- composition (zero cloud calls) --------------------------------------
def compose_prompt(spec: dict, task: str, retrieved: list,
                   last_response: str, step: int) -> str:
    top_k = spec.get("retrieve", {}).get("top_k", 5)
    if retrieved:
        ctx = "\n---\n".join(
            f"[{i}] ({r['kind']}, sim={r['score']}) {r['snippet']}"
            for i, r in enumerate(retrieved[:top_k]))
    else:
        ctx = "(none yet — this is the first step)"
    tmpl = DEFAULT_TEMPLATE if spec.get("template", "default") == "default" else DEFAULT_TEMPLATE
    return tmpl.format(
        task=task, retrieved=ctx,
        last_response=last_response or "(none yet)",
        cwd=os.getcwd(), step=step)


def parse_response(text: str, stop: dict) -> tuple:
    """Return (kind, payload). kind in {answer, bash, reason}."""
    t = text.strip()
    ap = stop.get("answer_prefix", "ANSWER:")
    if t.startswith(ap):
        return "answer", t[len(ap):].strip()
    if t.startswith("BASH:"):
        return "bash", t[len("BASH:"):].strip()
    # also accept a trailing ANSWER: anywhere
    if ap in t:
        return "answer", t.split(ap, 1)[1].strip()
    return "reason", t


# ---- the loop ------------------------------------------------------------
def run(task: str, intent: str = "default", max_steps: int = 0,
        trust_bash: bool = False, top_k: int = 0) -> dict:
    spec = program_get(intent)
    if not max_steps:
        max_steps = spec.get("stop", {}).get("max_steps", 5)
    if not top_k:
        top_k = spec.get("retrieve", {}).get("top_k", 5)
    stop = spec.get("stop", {})
    meta = {
        "intent": intent,
        "project": os.environ.get("CC_SCOPE_LOCAL_PROJECT")
                   or os.environ.get("CC_SCOPE_GLOBAL_PROJECT", ""),
        "scope_cwd": os.environ.get("CC_SCOPE_CWD", os.getcwd()),
        "agent_uuid": os.environ.get("CC_AGENT_UUID", ""),
    }

    # Seed: the task itself is a prompt cell (RAG-retrievable from now on).
    seed_cid = cell_store.add_cell("prompt", task, intent=intent, source="loop",
                                   project=meta["project"], scope_cwd=meta["scope_cwd"],
                                   agent_uuid=meta["agent_uuid"])
    steps = [{"step": 0, "kind": "seed", "cell_cid": seed_cid, "content": task}]
    last_response = ""
    prev_response_cid = None
    final_answer = None
    print(f"[loop] intent={intent} model={MODEL} max_steps={max_steps} top_k={top_k}",
          file=sys.stderr)

    for step in range(1, max_steps + 1):
        # ── attend: retrieve relevant cells (maximized scope, zero cloud) ──
        query_text = last_response or task
        retrieved = cell_store.query(query_text, top_k=top_k)
        # ── compose (zero cloud) ──
        prompt = compose_prompt(spec, task, retrieved, last_response, step)
        # ── dispatch → await → store (recipe-cached) ──
        out_cid, output, from_cache = dispatch_model(prompt, intent, meta)
        steps.append({"step": step, "kind": "model", "cell_cid": out_cid,
                      "from_cache": from_cache, "output": output[:200],
                      "recipe_cached": from_cache})
        cache_tag = " [cache]" if from_cache else ""
        print(f"[loop] step {step} model{cache_tag}: {output[:120]!r}", file=sys.stderr)

        # ── stop: fixpoint (same model response cell as last step) ──
        # Catches both reason-loops AND bash-loops: if the model emits the
        # same thing twice (identical composed prompt → identical output),
        # the content-addressed cid repeats → we're stuck → stop. The best
        # answer is the last OBSERVATION (last_response), not the repeated
        # model command.
        if stop.get("fixpoint", True) and prev_response_cid == out_cid:
            print(f"[loop] fixpoint reached at step {step}", file=sys.stderr)
            final_answer = last_response or output
            break
        prev_response_cid = out_cid

        kind, payload = parse_response(output, stop)
        if kind == "answer":
            final_answer = payload
            steps[-1]["parsed"] = "answer"
            break
        if kind == "bash":
            if not trust_bash:
                print(f"[loop] step {step} BASH (dry-run, --trust-bash to run): {payload!r}",
                      file=sys.stderr)
                last_response = f"[dry-run not executed] {payload}"
                steps.append({"step": step, "kind": "bash-dryrun", "cmd": payload})
            else:
                b_cid, b_out, b_cache = run_bash(payload, last_response, intent, meta)
                last_response = b_out
                steps.append({"step": step, "kind": "bash", "cell_cid": b_cid,
                              "from_cache": b_cache, "output": b_out[:200]})
                cell_store.edge_add(out_cid, b_cid, "produced")
                print(f"[loop] step {step} bash{' [cache]' if b_cache else ''}: {b_out[:120]!r}",
                      file=sys.stderr)
            continue
        # reason step — feed it forward
        last_response = output
    else:
        print(f"[loop] max_steps ({max_steps}) reached", file=sys.stderr)
        final_answer = final_answer or last_response or output

    # Persist the loop as a chain_run (a loop IS a chain) so cc -chain-show works.
    run_id = _persist_loop(task, intent, steps, final_answer)
    result = {"run_id": run_id, "intent": intent, "model": MODEL,
              "steps": steps, "final_answer": final_answer}
    print(json.dumps(result, indent=2))
    return result


def _persist_loop(task: str, intent: str, steps: list, answer) -> int:
    """Best-effort: write the loop as a chain_run + chain_run_steps (local db)."""
    db_path = os.environ.get("CC_LOCAL_DB") or os.environ.get("CC_SCOPE_LOCAL_DB")
    if not db_path or not Path(db_path).exists():
        return 0
    try:
        import subprocess
        db_lib = Path(__file__).resolve().parent / "db.py"
        env = {**os.environ, "CC_DB": db_path}
        r = subprocess.run([sys.executable, str(db_lib), "chain-run-start",
                            f"[loop:{intent}] {task}",
                            os.environ.get("CC_AGENT_UUID", "")],
                           capture_output=True, text=True, timeout=10, env=env)
        run_id = int(r.stdout.strip()) if r.stdout.strip() else 0
        for i, s in enumerate(steps):
            subprocess.run([sys.executable, str(db_lib), "chain-run-step-add",
                            str(run_id), str(i), s.get("kind", "loop"), "0",
                            "", s.get("output", s.get("cmd", ""))[:16000],
                            s.get("output", "")[:16000], "0",
                            "1" if s.get("from_cache") else "0",
                            s.get("cell_cid", ""), ""],
                           capture_output=True, text=True, timeout=10, env=env)
        subprocess.run([sys.executable, str(db_lib), "chain-run-end",
                        str(run_id), "ok"], capture_output=True, text=True,
                       timeout=10, env=env)
        return run_id
    except Exception:
        return 0


# ---- CLI -----------------------------------------------------------------
def _cli():
    import argparse
    ap = argparse.ArgumentParser(prog="loop.py", description="cc autoregressive loop")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("task", nargs="+")
    r.add_argument("--intent", default="default")
    r.add_argument("--max-steps", type=int, default=0)
    r.add_argument("--trust-bash", action="store_true")
    r.add_argument("--top-k", type=int, default=0)
    s = sub.add_parser("show"); s.add_argument("run_id", type=int)
    l = sub.add_parser("list"); l.add_argument("n", type=int, default=20, nargs="?")
    args = ap.parse_args()

    if args.cmd == "run":
        run(" ".join(args.task), intent=args.intent, max_steps=args.max_steps,
            trust_bash=args.trust_bash, top_k=args.top_k)
    elif args.cmd == "show":
        # delegate to cc -chain-show via db.py
        db_path = os.environ.get("CC_LOCAL_DB") or os.environ.get("CC_SCOPE_LOCAL_DB")
        db_lib = Path(__file__).resolve().parent / "db.py"
        env = {**os.environ, "CC_DB": db_path} if db_path else os.environ
        subprocess.run([sys.executable, str(db_lib), "chain-run-show", str(args.run_id)], env=env)
    elif args.cmd == "list":
        db_path = os.environ.get("CC_LOCAL_DB") or os.environ.get("CC_SCOPE_LOCAL_DB")
        db_lib = Path(__file__).resolve().parent / "db.py"
        env = {**os.environ, "CC_DB": db_path} if db_path else os.environ
        subprocess.run([sys.executable, str(db_lib), "chain-run-list", str(args.n)], env=env)


if __name__ == "__main__":
    _cli()