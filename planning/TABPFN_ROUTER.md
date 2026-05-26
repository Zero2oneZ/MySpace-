# TabPFN Router — three predictors over the opcode graph
# IP CONFIDENTIAL

The user's vision: TabPFN is the brain that decides, at any point in a
workflow build, **what to do next**, **what UI to render**, and
**which concrete model to dispatch**. It runs deterministically, in-
context, with no per-project training.

Three predictors. One substrate (sqlite + a few hundred lines of Python).
All three trained from the same example-collection mechanism (cc records
every chain run, every workflow edit, every user override; those rows
become future training data automatically).

---

## P1 — Next-opcode router (TODO / planning brain)

**Question it answers:** given the workflow built so far, what task
opcode should come next?

**Features (input vector):**

| feature | type | encoding | example |
|---|---|---|---|
| current_modality_in | categorical | one-hot over 11 modalities | `IMAGE` |
| target_modality | categorical | one-hot | `VIDEO` |
| steps_so_far | int | 0–5 | 2 |
| last_opcode | categorical | one-hot over 53 opcodes | `Text-to-Speech` |
| last_layer | int | 1–6 | 2 |
| modalities_visited | multi-hot | which modality types have appeared | `{TEXT, AUDIO}` |
| intent_keywords | multi-hot | bag of (stemmed) intent words from user prompt | `{translate, podcast}` |
| user_project_kind | categorical | from local meta: `chat`, `media`, `trading`, `business` | `media` |
| era_distribution | bucketed | mean era of chain so far | 4.2 |

**Label:** next opcode (one of 53 classes from `hf_task_evolution.jsonl`),
or `__STOP__` if the chain should terminate here.

**Training data sources:**
- Every successful `chain_runs` row (already in DB) becomes N-1 examples:
  `(state at step i, label = opcode at step i+1)`.
- The 22 demo pipelines in `PIPELINES.md` seed the cold-start dataset.
- User overrides during REPL (`swap` / `insert` / `remove`) generate
  negative examples (the rejected opcode was wrong for THIS context).
- The 53 opcode rows themselves seed a "what opcodes EXIST" prior.

**Integration point:** wraps the existing path_builder ranker. Two
modes selectable via flag:
- `--rank heuristic` (current scorer) — explainable, no ML deps
- `--rank tabpfn` — learns from history, beats heuristic once
  you have ~50+ recorded chains

The two modes return the same shape (`list[(score, [opcode...])]`),
so swap is free.

---

## P2 — GUI-element predictor

**Question it answers:** given an opcode (or partial workflow), which
UI widgets does the user need to render?

**Features:**

| feature | type | example |
|---|---|---|
| opcode | categorical | `Image-Text-to-Video` |
| input_slots | multi-hot | which modalities the opcode consumes — `IMAGE`, `TEXT` |
| output_slot | categorical | `VIDEO` |
| upstream_provides | multi-hot | which slots are auto-filled by previous step output |
| user_intent_category | categorical | `quick-demo`, `production`, `inspection` |
| device_class | categorical | `desktop`, `mobile`, `embed` |

**Label:** set of GUI widgets needed (multi-label classification or
sequence prediction):
- `text_input` (single-line / multi-line)
- `file_upload` (image / audio / video / doc — typed)
- `audio_recorder`, `video_recorder` (live capture)
- `slider` (duration, seed, temperature)
- `dropdown` (model variant, language)
- `image_preview`, `audio_player`, `video_player` (output)
- `progress_bar`, `step_indicator`
- `download_button`, `share_button`
- `confirmation_dialog` (for destructive ops)

**Training data sources:**
- A seed mapping: `opcode → typical widgets` (hand-curated for the 53
  opcodes, ~1 hour of work).
- User UI edits in the Phase-3 frontends (every time a user adds /
  removes / reorders a widget, record it as `(features, label)`).
- HF Spaces examples: scrape the gradio interface specs from a few
  hundred public Spaces, label each by detected opcode → widget map.

**Integration point:** the Phase-3 Gradio frontend calls
`cc tabpfn ui <opcode>` to know what widgets to spawn. The output is
a JSON spec that Gradio (or any UI layer) consumes. Same predictor
serves Streamlit, terminal TUI, future VSCode plugin.

---

## P3 — Concrete-model resolver (what / where / why)

**Question it answers:** given an opcode + context constraints, which
ACTUAL model do we dispatch — and why?

**Features:**

| feature | type | example |
|---|---|---|
| opcode | categorical | `Automatic Speech Recognition` |
| input_audio_lang | categorical | `en`, `es`, `multi`, `unknown` |
| max_latency_ms | int | 500 |
| max_cost_usd | float | 0.01 |
| gpu_available | bool | true |
| gpu_vram_gb | float | 24 |
| network_available | bool | true |
| privacy_required | bool | false |
| preferred_provider | categorical | `local`, `ollama`, `hf`, `openai`, `anthropic` |
| past_user_choices | multi-hot | which models this user previously picked for this opcode |

**Label:** concrete model identifier (e.g., `openai/whisper-large-v3`,
`distil-whisper/distil-small.en`, `gpt-4o-transcribe`).

**Plus an EXPLANATION head** — TabPFN's output is a probability
distribution over candidates. The "why" is just `top-1 prediction
+ contributing features ranked by influence`. Cheap to derive.

**Training data sources:**
- A seed `tool_resolutions.jsonl` mapping each opcode to N candidate
  models with their cost/latency/quality profiles (~3 hours of work).
- Every successful `runs` row records which model was actually called
  for which opcode under which conditions. Becomes training data.
- User explicit overrides (`cc tabpfn resolve --use <model>`) become
  high-weight positive examples.

**Integration point:** wraps the dispatch layer. `cc workflow run`
currently calls a tool's executor verbatim. Wrap it: when the workflow
step is an opcode (not a concrete tool), the resolver picks the
concrete model first, then runs.

---

## Schema additions

```sql
-- The training-example accumulator. Each row is one
-- (features → label) example for one of the three predictors.
CREATE TABLE IF NOT EXISTS tabpfn_examples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  predictor TEXT NOT NULL,              -- 'router' | 'ui' | 'resolver'
  features_json TEXT NOT NULL,          -- the feature vector as JSON
  label TEXT NOT NULL,                  -- the target class as string
  weight REAL DEFAULT 1.0,              -- user overrides get weight=5
  source TEXT,                          -- 'seed' | 'chain_run' | 'user_override' | 'demo'
  created_at TEXT DEFAULT (datetime('now')),
  project TEXT                          -- scoped per project_name
);

CREATE INDEX IF NOT EXISTS idx_examples_predictor
  ON tabpfn_examples(predictor, project);

-- A cache of recent predictions, useful for explainability + debugging.
CREATE TABLE IF NOT EXISTS tabpfn_predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  predictor TEXT NOT NULL,
  features_json TEXT NOT NULL,
  features_hash TEXT NOT NULL,          -- sha256 for cache lookup
  prediction_json TEXT NOT NULL,        -- {top_k: [(label, prob)...], rationale: ...}
  ms_elapsed INTEGER,
  cached INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_predictions_hash
  ON tabpfn_predictions(features_hash);
```

---

## Architecture (no daemon, single Python module)

```
core/lib/router.py     — orchestrator. Loads TabPFN once per process.
                          Exposes predict_route(), predict_ui(),
                          predict_resolver().
core/lib/seed_data.py  — generators that produce the cold-start
                          examples for each predictor from the
                          taxonomy JSONL + canonical pipelines.
core/lib/explain.py    — "why this model" — feature-importance and
                          contributing-example surfacing.

cc -route '<state>'           — one-shot CLI call
cc -ui <opcode>               — predict UI widgets
cc -resolve <opcode>          — predict concrete model
cc -route-train               — refresh predictions cache + dump stats
cc -route-show <prediction>   — show a previous prediction + rationale
```

---

## TabPFN dep handling

TabPFN ships as a pip package (`tabpfn`) plus PyTorch (~2 GB).
Heavy for the otherwise-lightweight cc substrate. Two-tier strategy:

**Optional dep.** `core/lib/router.py` tries `import tabpfn`; on
failure falls back to a built-in classifier. The fallback options
(easiest first):

1. **k-NN over the example bank** — no deps beyond stdlib + numpy.
   Surprisingly competitive on small datasets; deterministic; fast.
2. **scikit-learn DecisionTree / RandomForest** — single dep that
   most python envs already have. Better than k-NN; less than TabPFN.
3. **TabPFN** — best quality, heaviest dep, our default if installed.

The router exposes the SAME interface regardless of backend. User
installs `tabpfn` when they want the best predictions; everyone else
gets a working router from a 5 KB python file.

The Nix flake gets a `myspace-pp-tabpfn` package overlay (with the
PyTorch + tabpfn deps); the Docker image gets a `myspace-pp:tabpfn`
tag (~3 GB vs ~200 MB base). Users opt in.

---

## Why this is genuinely better than "just use an LLM"

| concern | LLM router | TabPFN router |
|---|---|---|
| Latency per call | 200–1500 ms | 50–150 ms |
| Cost per call | $0.0001–0.01 | $0 (local) |
| Determinism | temp=0+seed but still drifts across model versions | byte-identical given same examples |
| Trains from user history | needs fine-tuning ($, time) | free, by adding rows |
| Explainability | hand-wave | feature importance, contributing examples |
| Size on disk | API-hosted (free) or ~5–20 GB local | 30 MB weights + PyTorch |
| Sub-100ms? | no | yes |

The LLM is still better when the user's request is a NOVEL composition
the example bank has never seen. So we keep both: TabPFN routes by
default, escalates to Claude/Codex when its top-1 probability is below
a threshold (e.g., 0.3) or when the user explicitly asks for creative
synthesis.

---

## Build order (proposed thin-slice first)

1. **Schema** — add `tabpfn_examples` + `tabpfn_predictions` to db.py
   (10 min).
2. **Seed generator** — `seed_data.py` produces ~500 cold-start
   examples for the router predictor from the 22 demo pipelines +
   the 53-opcode taxonomy (1 hour).
3. **Router with k-NN fallback** — `router.py` with the k-NN backend
   only, no TabPFN dep. Proves the interface (1 hour).
4. **CLI wiring** — `cc -route '<state>'` returns top-3 next opcodes.
   Bridges the router into the existing `path_builder` REPL via a
   new `route` command (30 min).
5. **TabPFN backend** — `import tabpfn`; if present, swap it in.
   Re-run the demo pipelines through the TabPFN-routed path. Compare
   vs heuristic vs k-NN (1 hour, given the pip install actually works).
6. **P2 (UI predictor) seed + thin slice** (2 hours).
7. **P3 (resolver) seed + thin slice** (3 hours — needs the tool
   resolution map first).

Total to a working router with both backends: ~6 hours. P2 and P3
extend incrementally; the router is the linchpin.

---

## Open questions for Tom

1. **Privacy/scope** — should the example bank be GLOBAL (cross-
   project, every chain in `cc.db`) or LOCAL (per-project, in
   `<proj>/.cc/local.db`)? Global gives better predictions; local
   preserves project-scope discipline. Mixed (default global with
   per-project override) is probably right.
2. **Cold-start prior** — do we ship the 22-demo seed examples as
   part of the substrate? They give every fresh install instant useful
   predictions. Cost: ~10 KB. Recommend yes.
3. **TabPFN as default vs opt-in** — given the 2 GB PyTorch dep, my
   default would be: k-NN baseline ships in core; tabpfn extra is a
   separate package / docker tag. Users who want the TabPFN brain pull
   that variant.
4. **Override workflow** — when the user disagrees with the router's
   top pick (in the REPL with `swap` or `insert`), do we record that
   as a negative example? Strong yes — that's how the router learns
   per-user preferences without explicit training.
