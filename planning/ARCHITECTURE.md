# MySpace++ — Architecture
# IP CONFIDENTIAL

Three layers. Strict separation. The lower layers must never depend on
the upper layers.

```
┌────────────────────────────────────────────────────────────────┐
│  FRONTENDS                                                     │
│  streamlit · gradio · TUI · future: VSCode ext, web dashboard  │
└──────────────────────────┬─────────────────────────────────────┘
                           │ reads/writes sqlite, calls `cc <verb>`
┌──────────────────────────▼─────────────────────────────────────┐
│  ADAPTERS                                                      │
│  ollama (reference) · claude-code · codex · hf-spaces          │
└──────────────────────────┬─────────────────────────────────────┘
                           │ all expose `model_call(model, prompt) -> (text, rc)`
┌──────────────────────────▼─────────────────────────────────────┐
│  SUBSTRATE                                                     │
│  bash `cc` · db.py · sqlite (cc.db + per-project local.db)     │
│  agent lifecycle · DONE protocol · sha256 cache · two-DB scope │
└────────────────────────────────────────────────────────────────┘
```

The **substrate** is the only mandatory layer. A user with just `cc` + bash
+ python3 + sqlite has a working system. Everything else is opt-in.

---

## The determinism contract

The substrate guarantees three things. If any port breaks these, it's a bug,
not a feature trade-off.

### 1. Same input → same output, byte for byte

```bash
$ cc tiny "what is 2 + 2"
4
$ cc tiny "what is 2 + 2"
4          # second call served from cache, not re-inferred
```

How:
- `model_call` always passes `temperature=0, seed=42` to ollama (unless
  `CC_DETERMINISTIC=0` is set, an explicit opt-out).
- Cache key is `sha256(model + json_options + full_prompt)`.
- Cache file lives in `$CC_CACHE` (default `~/.cc/cache/`).
- On cache hit, the file is returned verbatim — no re-tokenization, no
  re-decoding.

What this enables:
- Reproducible test runs.
- Cheap re-execution of long swarms during dev.
- A user can diff cache files between two cc versions to spot drift.

### 2. Every model call signals completion or failure

The substrate appends a literal `When finished, end your response with
the literal token: DONE` directive to every prompt. The response handler:

- `rc=0`: response contains DONE → completion confirmed, DONE stripped.
- `rc=1`: transport error (curl timeout, ollama crash, empty response).
- `rc=2`: response present but no DONE → partial. Stored with a
  `.partial` sibling marker. Callers can retry, escalate, or accept.

This means a swarm can distinguish "model finished" from "model got cut
off mid-thought" without parsing JSON or reading server logs.

### 3. Scope is mechanical, not aspirational

Two databases:
- `$CC_HOME/cc.db` — **global**. Projects, todos, queue, directory log,
  registered scripts, agent/tool/workflow/swarm definitions.
- `<project>/.cc/local.db` — **local**. Per-project meta, entrypoints,
  runs, agent lifecycle, phases, chats.

Scope resolution: walk up from `$PWD` until a directory contains
`.cc/local.db`. That directory is `CC_LOCAL_ROOT`. Everything `cc` does
is scoped to that root unless the user explicitly opts out.

Why this matters for portability:
- The scope mechanism is **pure filesystem walk**. No daemon, no env
  variable, no PID file. Works identically on every OS.
- The local DB is portable: copy `.cc/` to a new machine and the
  project's full history goes with it.
- A container mount can map a project directory and `cc` inside the
  container sees the same scope as `cc` outside.

---

## The DONE protocol (detailed)

Why: small models routinely truncate at the context boundary or emit
EOS mid-thought. We need a signal that doesn't require server-side
introspection.

Flow:
1. Substrate appends `When finished, end your response with the literal
   token: DONE` to the user's prompt.
2. Model generates response.
3. Substrate runs a Python regex `(^|\s)DONE\s*$` to check.
4. Strip the DONE token from the response before returning.
5. Set `has_done=1` if matched, `0` otherwise.
6. Return rc=0 if matched, rc=2 if not.

Adapters MUST follow this protocol. The claude-code adapter wraps
`claude -p` with the same directive. The codex adapter does the same.
The HF-spaces adapter does the same. **All adapters return the same
(text, rc) tuple shape.**

A consequence: prompts that are themselves about the word "DONE" need
escaping. That's an acceptable trade-off for the cross-adapter
uniformity it buys.

---

## Agent lifecycle

Every `cc` invocation:
1. Generates a fresh UUID (from `/proc/sys/kernel/random/uuid` if
   available, then `uuidgen`, then python `uuid.uuid4()`, then a
   pid+epoch+RANDOM fallback).
2. Calls `agent-claim` on the local DB — INSERTs a row with
   `(uuid, pid, cwd, action, started_at)`.
3. Registers an EXIT/INT/TERM trap that calls `agent-release`, which
   UPDATEs the row with `finished_at=now()`.
4. On `exec` (e.g., `cc tui`, `cc studio`), releases the agent
   **before** the exec so the shell handoff doesn't skip the trap.

Why: with 5-10 concurrent terminals, the user needs to see which `cc`
processes are doing what. `cc -agents` reads this table. Zombie rows
indicate trap skips or `kill -9`. The lifecycle is a debug signal as
much as a coordination mechanism.

---

## Adapter contract

Every adapter exports a single function:

```python
def model_call(
    model: str,
    prompt: str,
    *,
    options: dict | None = None,
    cache_dir: Path,
    timeout: int = 120,
) -> tuple[str, int]:
    """
    Return (response_text, rc) where rc in {0, 1, 2}:
      0 = completed (DONE seen, stripped)
      1 = transport failure
      2 = partial (no DONE)
    Must cache by sha256(model + json(options) + prompt) under cache_dir.
    Must append the DONE directive to the prompt before sending.
    Must respect timeout — never block longer than this.
    """
```

That's it. Any model backend that fits this signature plugs in:
- ollama (HTTP `/api/generate`)
- claude-code (`claude -p --append-system-prompt ...`)
- codex (`openai.chat.completions.create`)
- hf-spaces (`huggingface_hub.InferenceClient.text_generation`)
- (future) llama.cpp, vllm, modal, replicate, anything else

---

## Escalation chain

Configured per-project in `local.db` meta:

```
meta-set escalation_chain "ollama:qwen2.5-coder:1.5b > ollama:qwen2.5-coder:7b > claude:opus"
```

Step-level logic in `cc swarm run`:
1. Try the first adapter in the chain.
2. If rc=2 (partial) → retry same adapter once. If still rc=2 → escalate.
3. If rc=1 (transport) → escalate immediately.
4. Escalation = call next adapter in chain with same prompt.
5. Log each escalation as a `runs` row with `escalated_from` column
   (schema addition needed in phase 4).
6. If chain exhausted, the swarm step records `status=failed` and the
   loop terminates unless `loop_until` is satisfied.

This gives users a single knob to dial cost vs reliability without
rewriting any agent definitions.

---

## Frontend contract

Every frontend MUST:
- Read/write only through `cc <verb>` or directly through `db.py`'s
  documented functions. No raw sqlite access to undocumented tables.
- Respect the agent lifecycle: claim an agent on connect, release on
  disconnect.
- Render the same view of the same data — a swarm started in gradio
  must appear identically in tui.
- Refuse to perform destructive operations without an explicit
  confirmation. (The substrate already enforces this for `cc -setup`
  re-runs after the phase-0 hardening pass.)

---

## What the substrate deliberately does NOT do

- **No daemon.** `cc` is a one-shot command. State is in sqlite.
  Concurrent invocations coordinate via WAL mode and the agents table.
- **No network bind.** The substrate never opens a listening socket.
  Frontends do that; the substrate only reads/writes files.
- **No background workers.** A swarm runs in the foreground of the
  invoking process. If you want it backgrounded, run it under
  `setsid`/`nohup`/`screen` — the agent row will reflect that.
- **No package management.** The substrate assumes its deps are
  already on PATH. The install layer's job is to put them there.

This minimalism is what makes the substrate portable. Adding a daemon
would mean per-OS service files. Adding network binds would mean
firewall logic. Adding background workers would mean signal handling
across platforms. None of that scales to four OSes.

---

## How this connects to existing IP

This repo is **standalone** and external-facing. It does not depend on
gently, GentlyOS, .bb, or any internal crate. It can be released as
source-available without exposing the platform.

Optional bridges (future, not phase 1-5):
- `adapters/bb_export.py` — convert a cc workflow JSON to a `.bb`
  program for ingestion into the gently runtime.
- `adapters/gently_runtime.py` — call `gently-runtime` as one of the
  model_call backends, treating each tic-tac as a deterministic step.
- `adapters/codie_v4.py` — use codie-v4-predict to compress prompts
  before they hit the cache, cutting cache size and improving hit rate.

These bridges live in `adapters/` and are opt-in. The core repo ships
without them and works without them.
