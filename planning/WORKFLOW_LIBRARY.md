# Workflow Library — Claude-authored global templates + local HITL execution
# IP CONFIDENTIAL

The architecture in one sentence: **Claude authors a library of robust
multi-tool workflow templates against the JSONL DAG vocabulary; the
local runtime picks a template, refines it for the user's specific
request, and executes it step-by-step with human-in-the-loop
checkpoints.**

Three layers, clean ownership:

```
┌─────────────────────────────────────────────────────────────────────┐
│  GLOBAL (~/.cc/cc.db, ~/.cc/templates/)                             │
│  Claude reads hf_task_evolution.jsonl + writes workflow_templates.  │
│  One template per capability area, e.g. "text-to-image-quality-loop"│
│  or "youtube-avatar-end-to-end". Each template includes preconditions│
│  fallbacks, recommended models, and human-checkpoint markers.       │
│  AUTHORED ONCE. Reused forever across projects.                     │
└─────────────────────┬───────────────────────────────────────────────┘
                      │  template lookup / instantiation
┌─────────────────────▼───────────────────────────────────────────────┐
│  LOCAL (<proj>/.cc/local.db)                                        │
│  workflow_jobs table — one row per user request. Each job ticks     │
│  through a chain of steps, pausing at HITL checkpoints, recording   │
│  every model output. State machine: planning → awaiting-human →     │
│  running → completed/failed/cancelled.                              │
│  PER-PROJECT. Audit trail of what was built where.                  │
└─────────────────────┬───────────────────────────────────────────────┘
                      │  (future) routing decisions
┌─────────────────────▼───────────────────────────────────────────────┐
│  TabPFN ROUTER (planned, see TABPFN_ROUTER.md)                      │
│  Once the local DB has 50+ jobs, TabPFN routes the per-step         │
│  "which opcode next? which model? which UI?" decisions in <150ms,   │
│  learning from each user's actual history.                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Layer 1 — Global authoring

**Goal:** Claude reads the taxonomy + the existing examples, and emits
~50–100 reusable workflow templates that cover the practical surface
of what MySpace++ can do.

For each primary opcode (or each interesting compound goal), Claude
answers: *"Given that I have access to this capability, what's the
robust multi-step way to use it that handles common failure modes,
provides quality checks, and surfaces decisions to the user?"*

### Template schema

A template is **not** a workflow — it's a workflow *recipe*. It carries
the chain structure plus everything a runtime needs to instantiate it:

```json
{
  "name": "text-to-image-quality-loop",
  "primary_opcode": "Text-to-Image",
  "description": "Generate an image from a prompt, score quality with a VLM, regenerate if below threshold, upscale, save.",
  "tags": ["image", "generation", "quality"],
  "steps": [
    {
      "idx": 0,
      "opcode": "Text Generation",
      "purpose": "Rewrite user prompt with style modifiers and negative-prompt for the diffusion model",
      "binds": {"TEXT": "$user_prompt"},
      "out": "rewritten_prompt",
      "model_candidates": ["claude-sonnet-4-6", "gpt-4o-mini", "qwen2.5:7b"],
      "human_checkpoint": null
    },
    {
      "idx": 1,
      "opcode": "Text-to-Image",
      "purpose": "Generate the image",
      "binds": {"TEXT": "$rewritten_prompt"},
      "out": "raw_image",
      "model_candidates": ["FLUX.1-schnell", "stabilityai/sdxl-turbo", "playgroundai/playground-v2-1024px-aesthetic"],
      "human_checkpoint": null
    },
    {
      "idx": 2,
      "opcode": "Image-Text-to-Text",
      "purpose": "Score image quality vs prompt (0-10)",
      "binds": {"IMAGE": "$raw_image", "TEXT": "Rate this image's match to: $rewritten_prompt. Reply: <score 0-10> <one line reason>"},
      "out": "quality_assessment",
      "model_candidates": ["Qwen2.5-VL-7B", "gpt-4o-mini", "claude-sonnet-4-6"],
      "human_checkpoint": null
    },
    {
      "idx": 3,
      "opcode": "__BRANCH__",
      "purpose": "If quality < 6, loop back to step 1 with adjusted prompt (max 3 retries)",
      "branch_on": "$quality_assessment",
      "branches": {
        "score<6": {"goto": 1, "max_retries": 3, "mutate": "append '(higher detail, sharper focus)' to rewritten_prompt"},
        "score>=6": {"goto": 4}
      },
      "human_checkpoint": null
    },
    {
      "idx": 4,
      "opcode": "Image-to-Image",
      "purpose": "Upscale 2x (optional, user can skip)",
      "binds": {"IMAGE": "$raw_image"},
      "out": "final_image",
      "model_candidates": ["stabilityai/stable-diffusion-x4-upscaler", "ESRGAN-x4"],
      "human_checkpoint": {
        "type": "y/n",
        "prompt": "Upscale 2x? (costs ~30s, ~$0.001 if cloud)",
        "default": "y"
      }
    }
  ],
  "preconditions": [
    {"check": "available_modality", "value": "TEXT"},
    {"check": "user_prompt_min_length", "value": 5}
  ],
  "fallbacks": {
    "Text-to-Image": ["Image-Text-to-Image"],
    "Image-Text-to-Text": ["Image-to-Text + Text Classification"]
  },
  "outputs": [
    {"name": "final_image", "modality": "IMAGE"},
    {"name": "quality_score", "modality": "SCALAR", "from_step": 2}
  ],
  "authored_by": "claude",
  "author_prompt_hash": "sha256:abc...",
  "use_count": 0
}
```

Notice what's NEW vs the simple `workflow_def`:
- **`purpose`** per step — Claude annotates *why* this step matters
- **`model_candidates`** — ordered preference list per opcode
- **`human_checkpoint`** — explicit confirmation points
- **`__BRANCH__`** opcode for conditional logic (with `branch_on` + `branches`)
- **`preconditions`** — runtime checks before kickoff
- **`fallbacks`** — what to swap if a model is unavailable

### The authoring command

```bash
cc -authorize-templates                       # generate templates for every opcode
cc -authorize-templates --opcode Text-to-Image     # one opcode
cc -authorize-templates --goal "youtube-avatar"    # one freeform goal
```

What it does (in Python, calling `cc claude` under the hood):

1. Loads `hf_task_evolution.jsonl`.
2. For the target (opcode or freeform goal), builds a Claude prompt with:
   - The full taxonomy as reference (`inputs`/`outputs`/`era`/`exemplars`)
   - The relevant path-builder results (top-10 chains involving the target)
   - The existing template library (so Claude doesn't duplicate)
   - A schema spec for the output JSON
3. Calls `cc claude -p` with that prompt.
4. Validates the returned JSON against the schema.
5. Validates each step's `opcode` exists in the taxonomy.
6. Validates the chain edges via `task_dag.paths()`.
7. Inserts the template into `workflow_templates` (global DB).
8. Logs the authoring prompt + cost to `chat-add` for audit.

**Cost discipline:** authoring is the ONE place we don't worry about
Claude cost. Each template costs ~$0.02 to author and is reused
thousands of times. Authored once at install + once per new opcode.

### Seeding the library

At first install, run `cc -authorize-templates --seed` to populate the
library with templates for the 22 demo pipelines (cheap, ~$0.50 total).
That gives every fresh project a useful starting library. Per-opcode
authoring is opt-in after that.

---

## Layer 2 — Local execution (HITL loop)

**Goal:** a per-project state machine that takes a user request,
selects a template, refines it for this specific request, and ticks
through execution with human checkpoints.

### Job state machine

```
┌─────────────┐    template selected     ┌──────────────┐
│  planning   │───────────────────────►  │   running    │
└─────────────┘                          └──────┬───────┘
       │                                        │
       │ HITL needed                  step complete, more steps?
       ▼                                        │
┌──────────────────┐    approved              yes
│ awaiting-human   │──────────────────────────┐│
└──────────────────┘                          ││
       │                                      ▼▼
       │ rejected                       ┌──────────────┐
       └────────────► replan / cancel   │  completed   │
                                        └──────────────┘
```

### Schema additions

```sql
-- Global (~/.cc/cc.db): the template library
CREATE TABLE IF NOT EXISTS workflow_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  primary_opcode TEXT,
  description TEXT NOT NULL,
  tags TEXT,                            -- comma-separated
  template_json TEXT NOT NULL,          -- full template (steps + branches + ...)
  preconditions_json TEXT,
  fallbacks_json TEXT,
  authored_by TEXT NOT NULL,            -- 'claude' | 'user' | 'seed'
  author_prompt_hash TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  use_count INTEGER DEFAULT 0,
  last_used_at TEXT
);

-- Local (<proj>/.cc/local.db): per-project jobs
CREATE TABLE IF NOT EXISTS workflow_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  template_name TEXT,                   -- NULL = ad-hoc (no template)
  user_request TEXT NOT NULL,
  current_step INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'planning',
  context_json TEXT,                    -- accumulated outputs / chosen models / branches taken
  started_at TEXT DEFAULT (datetime('now')),
  ended_at TEXT,
  agent_uuid TEXT
);

CREATE TABLE IF NOT EXISTS workflow_job_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER REFERENCES workflow_jobs(id),
  step_idx INTEGER,
  opcode TEXT NOT NULL,
  purpose TEXT,                         -- copied from template for audit
  chosen_model TEXT,
  inputs_json TEXT,
  output TEXT,
  human_checkpoint_type TEXT,           -- NULL if none
  human_decision TEXT,                  -- 'approved' | 'rejected' | 'overridden' | NULL
  human_notes TEXT,
  started_at TEXT DEFAULT (datetime('now')),
  finished_at TEXT,
  ms_elapsed INTEGER
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON workflow_jobs(status);
CREATE INDEX IF NOT EXISTS idx_steps_job ON workflow_job_steps(job_id, step_idx);
```

### CLI surface

```bash
# Browse the library
cc -templates                          # list all global templates
cc -template-show <name>               # full JSON, steps, model candidates
cc -template-search <query>            # semantic search (uses Feature Extraction)

# Start a job
cc -job "<freeform request>"           # creates planning job, drafts chain
                                       # → returns job id, asks human to confirm template
cc -job --template <name> "<request>"  # skip planning, use this template

# Drive a job (auto-mode or interactive)
cc -job-step <id>                      # advance one step (blocks if HITL needed)
cc -job-auto <id>                      # auto-approve until first HITL
cc -job-approve <step_id> [notes]      # human approves a HITL checkpoint
cc -job-reject <step_id> [reason]      # human rejects; system replans
cc -job-override <step_id> <model>     # human picks a different model for this step
cc -job-show <id>                      # full state dump
cc -job-cancel <id>

# Browse
cc -jobs                               # list recent jobs
cc -job-last                           # show most recent
cc -job-runs <template_name>           # all jobs that used this template
```

### What happens during `cc -job "build me a youtube-avatar"`

1. **Planning phase** (cc claude call):
   - System loads global templates matching `youtube-avatar` or
     similar keywords + the relevant opcode chain from path-builder.
   - Claude (or TabPFN later) picks the best matching template, or
     composes a new chain from existing templates.
   - System shows the proposed chain to the user; user confirms or edits.
2. **Job created** with status `planning` → `running`.
3. **Step loop** (sync, in foreground by default):
   - For each step in the template:
     - Resolve the concrete model from `model_candidates` (current heuristic;
       TabPFN takes over once trained).
     - If `human_checkpoint` is set, write status `awaiting-human`,
       block, surface the checkpoint prompt, wait for `cc -job-approve` /
       `cc -job-reject`.
     - Otherwise, dispatch the model call (via `cc tiny` / `cc claude`
       / direct HF Inference API / etc.).
     - Record output to `workflow_job_steps`.
     - If `__BRANCH__`, evaluate the branch condition, jump.
4. **Completion**: status `completed`, final outputs surfaced (paths
   to files, downloadable artifacts).

### HITL UX (v1 — terminal only)

```
$ cc -job "make a 30-second talking avatar from this YouTube URL"
[planning] selecting template…
  → matched template 'youtube-avatar-end-to-end' (used 0 times)
  → 6 steps, est ~3 minutes, 1 human checkpoint
  → proposed chain:
    [0] yt-dlp-grab           (no model)
    [1] Video-Text-to-Text    (Whisper-large-v3)
    [2] Text Generation       (Claude-sonnet-4-6)  ← rewrite script
    [3] Text-to-Speech        (XTTS-v2)            ← clone voice
    [4] Audio-Image-to-Video  (MuseTalk)           ← lipsync
    [5] [HUMAN] approve final output before save

  Proceed? [Y/n/edit] y
[running] step 0: yt-dlp-grab… done (2.3s)
[running] step 1: Whisper transcription… done (8.1s)
[running] step 2: Claude script rewrite… done (4.2s)
[running] step 3: XTTS synthesis… done (15.7s)
[running] step 4: MuseTalk lipsync… done (47.3s)
[awaiting-human] step 5: preview /tmp/avatar.mp4

  approve? [Y/n/redo last step]
```

If `n` → step rejected, replanning offered. If `redo` → step 4 (or
selected) re-run with adjusted params.

### HITL UX (v2 — gradio web)

Same state machine, different surface. The web UI polls
`workflow_jobs` for `awaiting-human` rows in the current project and
renders an approval card. Phase 3 work.

---

## How this connects to existing primitives

| Existing | Connection |
|---|---|
| `hf_task_evolution.jsonl` | The opcode vocabulary Claude authors against and the chain validator enforces |
| `path_builder.py` | Used DURING authoring (Claude is shown top-N chains for context) and during ad-hoc job composition |
| `cc workflow define` / `run` | A workflow is the legacy ad-hoc form; a template is the new structured form. `workflow_def` will be deprecated in favor of `workflow_templates` over time, OR we keep `workflow_def` for terse user-authored cases and `workflow_templates` for the rich Claude-authored ones. |
| `cc -chain` | A chain is the simplest case — one-shot multi-step with `\|`/`+`/`-`. A template is a chain + branches + HITL + model candidates. |
| `cc claude` | Powers the authoring phase. |
| `cc tiny` | Powers cheap per-step routing decisions while the template is running. |
| `chain_runs` table | Each run still records to `chain_runs` for the cache-detection determinism layer. Job-level metadata is in `workflow_jobs`. |

---

## Decisions Tom needs to make (4)

These map back to your earlier questions, now answered:

| # | Question | Answer |
|---|---|---|
| 1 | Global vs local example bank | **Both** — templates global, jobs local. The TabPFN example bank later also splits this way. |
| 2 | Ship seed templates? | **Yes** — author the 22 demo pipelines as templates at install, ship in core. ~50 KB. |
| 3 | TabPFN default vs opt-in | **Opt-in extra** — k-NN fallback ships in core. (Unchanged from prior doc.) |
| 4 | Record HITL rejections as TabPFN negative examples? | **Yes** — the loop that learns from human-in-the-loop decisions is the entire point of the architecture. |

---

## Build order

Same thin-slice philosophy as before — each phase ships something
end-to-end runnable.

| Phase | Builds | Why first |
|---|---|---|
| **W1** | Schema + `cc -templates`/`-template-show` | Surface the table; even empty it proves the wiring |
| **W2** | `cc -authorize-templates --opcode <X>` against Claude | One-template-at-a-time gives fast iteration on the authoring prompt |
| **W3** | Seed: author + commit templates for the 22 demo pipelines | Concrete library to test against |
| **W4** | Job state machine: `cc -job`, `-job-step`, `-job-show` (no HITL yet) | Auto-run a template end-to-end |
| **W5** | HITL: `human_checkpoint` handling, `-job-approve` / `-job-reject` | The headline feature |
| **W6** | `__BRANCH__` opcode evaluation + retry logic | Quality loops work |
| **W7** | Integration with TabPFN router for per-step model selection | Replaces the heuristic `chosen_model` picker |

W1 + W2 + W4 are the critical path to "works end-to-end with one
template, no HITL, no branches". ~4 hours. Everything else is
incremental.

---

## Open question Tom probably has

**Q: How does this interact with `cc -chain`?**

`-chain` stays — it's the ad-hoc terse form for one-shot
prototyping. A template is the productionized form. There's a clean
migration path:

```bash
# Prototype a chain interactively
$ cc -chain '{{"foo"} | cc {{"bar"} + {"baz"}}}'
[output...]

# When it's good, promote to a template
$ cc -chain-promote --name my-fast-pipeline
written: ~/.cc/templates/my-fast-pipeline.json

# Now it's reusable, gets a use_count, can be edited by Claude later
$ cc -job --template my-fast-pipeline "actual user request"
```

The promote step is a 50-line bash that wraps the chain's
`chain_runs` row as a minimal template (no branches, no HITL).
Trivial to add.
