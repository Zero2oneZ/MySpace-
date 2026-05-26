# HF Task Taxonomy → Talking Avatar — Evolution Map

> Companion to `hf_task_evolution.jsonl`. The JSONL has one line per task
> class (52 total, from the Hugging Face task picker). The lines are
> ordered by **era of emergence** — when the capability first became
> practically usable at scale, not when the math was invented.
>
> The point of this map: the avatar use case ("describe a video bot
> that talks and walks in realtime") is not one model — it's a stack
> of capabilities, each enabled by the one below it. The JSONL lets
> us see WHICH capabilities a request needs, IN WHAT ORDER, and which
> are mature enough to actually wire today.

---

## The 7 eras

| Era | Years | What it unlocked |
|---|---|---|
| **1. Classical signal + early deep CV** | pre-2012 → 2016 | image classification, audio classification, depth, keypoints, ASR, TTS — the recognition primitives |
| **2. Transformer NLP** | 2017 → 2020 | text generation, translation, summarization, QA, embeddings — language as a first-class computable thing |
| **3. Multimodal foundations** | 2020 → 2022 | CLIP, diffusion, BLIP — text and image start sharing a representation space |
| **4. Generative video + 3D** | 2022 → 2024 | text-to-video, image-to-video, 3D Gaussian splats, ControlNet — pixels become animatable from descriptions |
| **5. Multimodal LLMs** | 2023 → 2026 | GPT-4V, Gemini, Qwen-VL, GPT-4o — a single model reads/writes across modalities |
| **6. Real-time embodied** | 2024 → 2026 | Wav2Lip → SadTalker → MuseTalk → streaming TTS + streaming ASR + low-latency lipsync; the round-trip drops under 500ms |
| **7. Any-to-Any unified** | 2024 → present | Chameleon, Janus, Show-o, GPT-4o multimodal output — one model in, anything out. The endgame for the avatar pipeline. |

---

## The canonical text → walking-talking-realtime-avatar pipeline

Each arrow is a task class from the HF taxonomy.

```
USER INPUT
    │
    ├── (voice)  Voice Activity Detection  →  Automatic Speech Recognition  →  text
    └── (typed)  text directly
                                                    │
                                                    ▼
                                          [ Text Generation ]                   ← LLM brain
                                                    │
                              ┌─────────────────────┼────────────────────────────────┐
                              ▼                     ▼                                ▼
                       [ Translation ]     [ response text ]              [ control tokens: emotion,
                       (i18n branch)                                        pose, gesture intent ]
                              │                     │                                │
                              └─────────────────────┤                                │
                                                    ▼                                │
                                          [ Text-to-Speech ]                         │
                                          (streaming, voice-cloned)                  │
                                                    │                                │
                              ┌─────────────────────┼────────────────────────────────┘
                              ▼                     ▼
                       [ audio stream ]      [ avatar pose plan ]
                              │                     │
                              │              ┌──────┴──────┐
                              │              ▼             ▼
                              │     [ Image-to-Video ]  [ Text-to-Video ]
                              │      (face/expression)   (body/walk gait)
                              │              │             │
                              │              └──────┬──────┘
                              │                     │
                              └─────────►  [ Video-to-Video ]  ← audio-conditioned lipsync
                                                    │           (Wav2Lip / MuseTalk lineage)
                                                    ▼
                                           [ Mask Generation ]  ← matting / background separation
                                                    │
                                                    ▼
                                          [ Image-to-Image ]  ← composite layers
                                                    │
                                                    ▼
                                            STREAMED OUTPUT
                                          (frames + audio,
                                           <500 ms round-trip)
```

Hard-realtime path (live conversation):

```
mic → VAD (~5 ms) → streaming ASR (~80 ms) → LLM (~200 ms) →
streaming TTS (~150 ms) → lipsync video (~100 ms) → display
                                      Σ ≈ 535 ms turn-around
```

Each of those numbers is from a 2026-era single-GPU implementation. Sub-500 ms is
just barely possible today; sub-200 ms is research.

---

## How to read the JSONL

Each line carries **two orthogonal views** of the same task:

- **Opcode view** (`inputs[]`, `outputs[]`, `layer`) — the typed interface.
  This is what lets a DAG self-assemble via `EDGE(A→B) iff outputs(A) ∩ inputs(B) ≠ ∅`.
  Layer numbering follows the standard ML-taxonomy convention (1 = single-modality,
  2 = cross-modal transducer, 3 = compound multimodal, 4 = zero-shot, 5 = universal
  bridge / Any-to-Any, 6 = agentic).
- **Evolution view** (`era`, `year`, `depends_on`, `enables`) — historical lineage.
  Tells the decomposer what's mature, what depends on what, and what to expect for
  cost/reliability.

Full schema:
```json
{
  "era": 1-7,                  // EVOLUTION view
  "year": <int>,
  "task": "<HF task name>",
  "category": "<HF macro category>",
  "layer": 1-6,                // OPCODE view
  "inputs":  ["<modality>"],
  "outputs": ["<modality>"],
  "exemplars": ["<model names>"],
  "depends_on": ["<prior tasks>"],
  "enables":    ["<later tasks>"],
  "pipeline_step": <int|null>,
  "role_in_avatar": "<one-liner or 'tangential'>",
  "notes": "<short reasoning>"
}
```

**Modality vocabulary** (primitive types that connect tasks):
- Modal: `TEXT`, `IMAGE`, `AUDIO`, `VIDEO`, `3D`, `TABULAR`, `GRAPH`, `DOC`
- Indexing: `EMBEDDING`
- Classification: `LABEL`, `LABEL_SEQ`, `LABELS` (the candidate set for zero-shot)
- Vision intermediates: `BOXES`, `MASK`, `KEYPOINTS`, `DEPTH_MAP`
- Other: `SCALAR`, `TIMESERIES`, `STATE`, `ACTION`

---

## Mechanical edge derivation

The DAG isn't hand-curated — it falls out of the typed I/O. Run:

```bash
python3 planning/task_dag.py stats                     # taxonomy summary
python3 planning/task_dag.py paths DOC AUDIO --no-any  # PDF -> podcast pipelines
python3 planning/task_dag.py paths AUDIO VIDEO         # voice -> talking head
python3 planning/task_dag.py consumers EMBEDDING       # who eats embeddings
python3 planning/task_dag.py producers VIDEO           # who emits video
```

The current taxonomy yields 527 raw edges (450 excluding the Any-to-Any wildcard).
The `paths` BFS finds every valid composition — for `DOC→AUDIO` it returns 2,858
distinct pipelines within depth 5, of which the top match is the obvious
`Document Question Answering → Text-to-Speech`. The Phase-5 decomposer's job is to
RANK these (using the `era`, `role_in_avatar`, and step counts) and pick the right one
for the user's request.

`pipeline_step` is non-null only for the tasks actually in the avatar pipeline.
The others (Tabular, Time Series, Graph ML, Document QA, etc.) are tangential
to the avatar use case but matter for OTHER MySpace++ use cases (trading bots,
business automation, etc.).

---

## Why this matters for MySpace++

1. **Decomposer prompt context.** The Phase-5 decomposer needs a vocabulary
   of capabilities. This JSONL IS that vocabulary, with dependency info baked in.
2. **Maturity gating.** Era ≤ 3 = reliable, deterministic, runs on CPU. Era 4–5 =
   GPU required, slow. Era 6–7 = bleeding edge, may not have an open weight. The
   decomposer can prefer earlier-era capabilities when the user request allows.
3. **Tool catalog seeding.** Each task class maps to ≥1 concrete tool we register
   in `cc tool define`. The JSONL tells us the priority order to build the
   catalog.
4. **The Any-to-Any endgame.** Era 7 collapses many pipeline steps. The decomposer
   should know that GPT-4o / Gemini-Live can replace ASR+LLM+TTS in one call,
   trading determinism + cost for latency + simplicity. That's a knob, not a fact.

---

## Open follow-ups (not for this commit)

- Map each JSONL entry to a concrete tool we'd register (`yt-dlp`, `whisper.cpp`,
  `xtts`, `wav2lip`, `SAM`, etc.).
- Add a `maturity` field: `production | preview | research` to gate the decomposer.
- Add a `cost_per_call` rough estimate (free local / cents / dollars) for the
  escalation logic.
- For Any-to-Any models: enumerate which sub-tasks they subsume so the decomposer
  can collapse pipelines automatically.
- **Pipeline ranking** — `task_dag.py paths` currently returns BFS results unranked.
  The 2,858 pipelines for DOC→AUDIO need to be scored. Heuristic: penalize Layer-1
  tasks that don't change modality (e.g., Fill-Mask in the middle of a chain is
  almost never what the user wants), reward shorter chains, reward chains made of
  newer-era (Layer 3/5) compound tasks that collapse multiple steps.
- **Multi-input pipeline planning** — current BFS treats an edge as "A satisfies
  one of B's inputs". A real planner tracks which of B's inputs are still unmet
  and finds a sub-chain to satisfy each. Topological planner, not BFS.

## Note on the gently parallel

The gently project has its own opcode taxonomy at
`/data/Projects/gently/data/task_taxonomy.jsonl` tied to the gently runtime
(operable_units index, Kimi tensors, crystal hashes, gently-dedup). MySpace++
has THIS parallel taxonomy — same opcode-graph design pattern, separate file,
zero cross-import. The two evolve independently so MySpace++ can ship
externally without exposing gently IP, and gently can evolve its opcodes
for the runtime axiom without coordinating with MySpace++.
