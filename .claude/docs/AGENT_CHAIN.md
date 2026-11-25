# AGENT_CHAIN — Deterministic Agent Routing System

> Resides in `.claude/` (project-local). Orchestrates all agent work across MySpace++.
> Principle: **Right-sized compute for every task.** No task gets a model 10x larger than needed.
> Principle: **Sessions never confuse each other.** Every agent has a deterministic chain position.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        ToDo-JobBoard.md                          │
│              (canonical task list — human + machine)               │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
         ┌──────────────┐      ┌──────────────┐
         │ chain_runner │      │ model_router │
         │  (tick loop) │      │ (complexity  │
         └──────┬───────┘      │  scoring)    │
                │              └──────────────┘
                ▼
         ┌──────────────┐
         │ Agent Level  │      Level 1 = tiny (0.5B)      — hash, list, validate
         │   Decision   │      Level 2 = small (1.5B)     — edit, parse, dispatch
         │              │      Level 3 = medium (7B)      — plan, route, design
         │  Route to:   │      Level 4 = large (32B)      — architect, sync, bridge
         │  ollama /    │      Level 5 = opus (Claude)    — strategy, security, human
         │  anthropic / │
         │  mcp_bridge  │
         └──────┬───────┘
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌───────┐  ┌───────┐  ┌──────────┐
│ollama │  │Claude │  │MCP Bridge│
│(local)│  │(api)  │  │(tools)   │
└───┬───┘  └───┬───┘  └────┬─────┘
    │          │           │
    └──────────┴───────────┘
                │
                ▼
        ┌──────────────┐
        │ chain_events │  ← append-only JSONL
        │  .jsonl      │     (every dispatch, every result)
        └──────────────┘
```

---

## How Routing Works

### 1. Task enters the board

A task is a row in `ToDo-JobBoard.md`:

```
| T-009 | level-3 | qwen2.5:7b | Design social clan API | RFC doc exists | PENDING | | HOLD |
```

### 2. chain_runner reads the board every tick

```bash
python3 .claude/chain/chain_runner.py --once
```

Only `PENDING` + `GO` tasks are routed.

### 3. model_router computes complexity

Four factors (0-100 total):
- **token_volume** (0-30) — how much text is involved
- **cross_file** (0-25) — how many files/systems are touched
- **reasoning** (0-25) — architectural vs mechanical
- **external** (0-20) — how many external APIs/platforms

Example:
```bash
python3 .claude/chain/model_router.py --task "Count lines in file.py"
# → Level 1 (tiny, qwen2.5:0.5b)

python3 .claude/chain/model_router.py --task "Refactor auth system with Discord integration and security audit"
# → Level 5 (opus, claude-opus-4-7) — escalated for security
```

### 4. Agent level decides endpoint

| Level | Model | Endpoint | Can Spawn? | Human? |
|-------|-------|----------|------------|--------|
| 1 | qwen2.5:0.5b | ollama | No | No |
| 2 | qwen2.5-coder:1.5b | ollama | Yes (L1) | No |
| 3 | qwen2.5:7b | ollama | Yes (L2) | No |
| 4 | qwen2.5:32b | ollama | Yes (L3) | No |
| 5 | claude-opus-4-7 | anthropic | Yes (L4) | **Yes** |

### 5. Dispatch

- **Level 1-4**: Can be auto-dispatched to ollama (if running) or fall back to anthropic
- **Level 5**: Never auto-dispatched. Flags `intervention: {reason, recommended_action}` and waits for a Claude session

---

## Agent Hierarchy & Handoff

### Lower → Higher (escalation)

When a lower-level agent:
1. Exceeds its token budget
2. Encounters a capability it doesn't have
3. Sees error rate > 30%

It **does not fail silently**. It appends an escalation event:

```json
{"event": "escalate", "from_level": 2, "to_level": 3, "task_id": "T-002",
 "reason": "capability_not_found: bb_program_author", "ts": "2026-05-28T16:00:00Z"}
```

### Higher → Lower (spawning)

When a higher-level agent decomposes a task, it spawns sub-tasks:

```bash
python3 .claude/chain/chain_runner.py --spawn "Generate SVG badge for tool status" \
  --parent T-005 --level 2
```

This appends a new row to ToDo-JobBoard.md and JSONL. The sub-task is a first-class citizen.

### Direct Handoff Protocol

1. Parent writes `subtask_spawn` event to JSONL
2. Child reads the event, executes, writes `subtask_complete` event
3. Parent reads `subtask_complete`, integrates the result
4. No shared memory — only the JSONL append-only log

---

## Token Budgets & Context Management

### Per-level hard caps

| Level | max_tokens | context_window |
|-------|-----------|----------------|
| 1 | 2,048 | 4,096 |
| 2 | 4,096 | 8,192 |
| 3 | 8,192 | 32,768 |
| 4 | 16,384 | 128,000 |
| 5 | 32,768 | 200,000 |

### Context measurement

The chain runner estimates tokens before routing:

```python
from model_router import estimate_tokens
tokens = estimate_tokens(long_prompt, content_type="code")
```

If `tokens > level.max_tokens`, escalate one level automatically.

### Session isolation

- Every task has a unique `task_id`
- Every sub-task has a unique `subtask_id` with parent reference
- Agents never share context windows — they share only the JSONL log
- A session reads the log from `unix=0` to now, but only acts on tasks assigned to its level

---

## Claude Intervention Points

Level 5 (opus) is **special**. It represents the human-level Claude sessions that the user interacts with directly.

### When Claude is summoned

A task is flagged for Claude when any of these are true:

| Trigger | Why |
|---------|-----|
| `requires_human_flag_set` | Task explicitly says "needs human" |
| `security_sensitive` | Contains "security", "auth", "token", "key" |
| `new_domain_unknown` | No existing capability covers this |
| Complexity > 75 | Strategic / architectural decisions |
| Error rate > 30% | Lower agents are failing repeatedly |

### What Claude sees

When a session starts, the chain runner produces:

```bash
# Summary of flagged tasks
python3 .claude/chain/chain_runner.py
```

Output:
```
Board: 7 tasks | 5 pending | 0 GO-ready
GO-ready tasks:
  T-009: Design social clan API... → L5 [HUMAN]
  T-010: Security review of payment router... → L5 [HUMAN]
```

Claude handles these. All other tasks are routed to ollama automatically.

---

## Integration with MCP Bridge

The chain runner can dispatch to the MCP bridge (Level 3+ tasks):

```python
# Inside chain_runner.py simulate_dispatch()
if endpoint == "mcp_bridge":
    # POST to http://127.0.0.1:8765/mcp/call
    # Tool names are namespaced: discord:send_message, hf:text_generation, etc.
```

This means:
- Level 3 agents can call HuggingFace, Livepeer, TrollzDotFun tools
- Level 2 agents can call Discord webhooks, social uploads
- Level 1 agents query browser states, validate JSON

---

## Feedback Loop (IDEA-006)

The chain is not static. It learns:

1. Every dispatch writes `chain_events.jsonl`
2. A periodic analyzer reads the last N events, computes success rates per level
3. If Level 2 has 40% failure on `code_review` tasks, the threshold for `code_review` is raised
4. The `registry.json` is updated with new complexity mappings

This is meta — the chain_runner becomes self-tuning.

---

## Files

| File | Purpose |
|------|---------|
| `.claude/agents/registry.json` | Agent definitions, levels, capabilities, endpoints |
| `.claude/chain/model_router.py` | Complexity scoring + model selection |
| `.claude/chain/chain_runner.py` | Tick loop: read board → route → dispatch → log |
| `.claude/chain/chain_events.jsonl` | Append-only dispatch + result log |
| `.claude/ideas/IDEAS.md` | Human-readable idea inventory |
| `.claude/ideas/ideas.jsonl` | Machine-readable idea state |
| `.claude/docs/AGENT_CHAIN.md` | This document |

---

## CLI Reference

```bash
# Route a single task
python3 .claude/chain/model_router.py --task "Design API" --json

# Run one chain tick (dry-run)
python3 .claude/chain/chain_runner.py --once

# Run daemon (every CHAIN_TICK_MS)
python3 .claude/chain/chain_runner.py --daemon --execute

# Spawn a sub-task
python3 .claude/chain/chain_runner.py --spawn "Generate badge SVG" --parent T-005 --level 2

# Check board status
python3 .claude/chain/chain_runner.py

# Route specific task
python3 .claude/chain/chain_runner.py --task-id T-002
```

---

*AGENT_CHAIN v0.1.0 | Deterministic routing for MySpace++ | 2026-05-28*
