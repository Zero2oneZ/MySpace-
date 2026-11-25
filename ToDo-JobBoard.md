# ToDo-JobBoard — Multi-Agent Orchestration Hub
# Scope: /data/Projects/MySpace++ ↔ /data/Projects/gently/
# Master-SVG Maintainer: BOTH projects (joint custody)
# Board Hash: sha256:ef37f2977070bde29c10f16edc7278ca8551a5a1d304a7f6a2b22e85a60087ac
# Last Updated: 2026-05-28T00:58:00Z
# Session Owner: tom-z21 (master agent)
# JSONL Entries: 11 (7 task, 2 swap, 1 sync, 1 hygiene-complete)
# JSONL Tail Hash: (swap events have no hash - appended by agent-swap-activate.sh)

---

## SYSTEM — Deterministic Agent Contract

**Every agent reading this board MUST:**

1. **PLAN before executing.** No prompt runs without a `/PLAN` entry in this file.
2. **Set Checkpoints.** Every plan has `Checkpoint → Steps → Substeps`. The agent cannot mark a Checkpoint complete until ALL substeps have a verified path to the next Checkpoint.
3. **Chain of completed tasks feeds the next agent.** The output of Step N is the preamble of Step N+1. No agent starts cold.
4. **Session ownership is explicit.** One agent (or one human) holds the session token. Every entry is stamped with `owner:` and `session_id:`. Unauthorized agents do NOT modify another's active block.
5. **Master Agent audits all workers.** The Master runs on the highest-capability model (`kimi-k2.6:cloud` or `gpt-oss:120b-cloud`). It validates outputs before the `GO` gate opens for the next agent.
6. **Multi-model dispatch is the default for synthesis tasks.** When a task requires generation (code, docs, SVG, plans), the Master dispatches to **up to 5 models simultaneously** via `cc -ensemble`. Responses are tagged, deduplicated, and merged into the best composite.
7. **File-type workflows are contamination-safe.** Each file type has a scoped DAG. Operations on `.rs` files NEVER touch `.py` files unless a bridge DAG explicitly maps the conversion.
8. **All DAGs emit SVG + XML metadata.** Every workflow produces an SVG visualization with an injected `<dag:metadata>` block containing `blake3` hash, owner, timestamp, and file-type scope.
9. **JSONL is the single source of truth for task state.** `ToDo-JobBoard.jsonl` (sibling to this file) is append-only. Rows are never deleted — status transitions are new rows.
10. **Scope is canon.** Any work outside `/data/Projects/MySpace++/` or `/data/Projects/gently/` requires an explicit bridge DAG entry. Unscoped work is rejected by the runtime.
11. **SWAP ACTIVATION TRIGGERS ROLE SWITCH.** When the `Next Agent` column changes (e.g., `mspc-runtime` → `gently-runtime`), the current agent MUST run the role-switch script before proceeding. This ensures the correct CLAUDE.md context and scope are active.
12. **ROLE STATE IS VERIFIABLE.** The file `/tmp/cc-agent-role.state` holds the active role (`mspc` or `gently`). Agents MUST verify this matches their assigned role in the Task Board before executing any scoped operation.

---

## Active Task Board

| Task ID | Agent | Model | Goal | Completion Benchmark | Status | Next Agent | Gate |
|---------|-------|-------|------|---------------------|--------|------------|------|
| T-001 | master | kimi-k2.6:cloud | Maintain ToDo-JobBoard.md hygiene | Board hash matches JSONL tail | ACTIVE | self | GO |
| T-002 | mspc-runtime | qwen3.5:27b | MySpace++ Phase 0 smoke tests pass | `core/tests/smoke.sh` all green | PENDING | mspc-builder | HOLD |
| T-003 | gently-runtime | qwen3-coder-next:latest | T-006 orchestrator crate builds | `cargo build -p gently-orchestrator` green | PENDING | gently-cc | HOLD |
| T-004 | cross-link | ensemble | MASTER-SVG.md synchronized across both repos | Both projects point to same SVG hash | PENDING | svg-emitter | HOLD |
| T-005 | dag-scanner | qwen2.5-coder:1.5b | All file types in both projects mapped to DAG nodes | `dag-status` shows 100% file-type coverage | PENDING | dag-builder | HOLD |
| T-006 | tts-pipeline | minimax-m2.7:cloud | End-to-end voice extraction + zero-shot TTS | Output audio file passes listening test | PENDING | audio-qa | HOLD |
| T-007 | runtime-integrator | kimi-k2.6:cloud | Browser pool + rust loop + MASTER-TODO sync | All 8 browsers active, runtime tick 5000ms, chain coherent | ACTIVE | browser-pool | GO |

**Gate Rules:**
- `GO` — next agent may fire immediately.
- `HOLD` — next agent MUST NOT fire until the Master sets `GO`.
- `PENDING` — waiting on upstream benchmark.
- `ACTIVE` — currently in progress.

**Browser Pool Gate:**
- `IDLE` — browser ready, no inference running.
- `INFER` — browser actively processing a pass.
- `SYNC` — browser syncing state with runtime loop.
- `ERROR` — browser failed coherence check, HOLD triggered.

---

## SWAP ACTIVATION — Role Switch Protocol

**Trigger:** When the `Next Agent` column in the Active Task Board changes, the incoming agent MUST execute a role swap before proceeding.

### Step 1: Verify Current Role State

```bash
# Check current role (agent running this MUST match the Task Board)
cat /tmp/cc-agent-role.state
```

### Step 2: Execute Role Switch

| Next Agent in Task Board | Role to Activate | Command |
|--------------------------|------------------|---------|
| `mspc-*`, `master`, `dag-scanner`, `svg-emitter`, `workflow-library`, `tts-pipeline`, `audio-qa` | **MySpace++** | `/data/Projects/MySpace++/scripts/agent-role-switch.sh mspc` |
| `gently-*`, `cross-link` | **GentlyOS** | `/data/Projects/MySpace++/scripts/agent-role-switch.sh gently` |

### Step 3: Source Environment Variables

```bash
# This exports CC_SCOPE_LOCAL_ROOT and CC_AGENT_ROLE for the current shell
source /data/Projects/MySpace++/scripts/cc-role-check.sh
```

### Step 4: Verify Activation

```bash
# Confirm role matches expected agent
/data/Projects/MySpace++/scripts/agent-role-switch.sh status
```

### Step 5: Read Project-Specific CLAUDE.md

**If MySpace++ role:**
```bash
# First 3 steps per CLAUDE.md
head -130 /data/Projects/MySpace++/CLAUDE.md  # Quick reference
cat /data/Projects/MySpace++/studio/docs/NOTES-FOR-INFERANCE.md  # Cross-session comms
cc -context  # Full state dump
```

**If GentlyOS role:**
```bash
# First 4 steps per CLAUDE.md
head -90 /data/Projects/gently/CLAUDE.md  # Quick reference
cat /data/Projects/gently/docs/NOTES-FOR-INFERENCE.md  # Cross-session comms
cat /data/Projects/gently/docs/SYNC-PROTOCOL.md  # Sync agreement
cc -context  # Full state dump
```

### Step 6: Log the Swap in JSONL

Append a `swap` event to `ToDo-JobBoard.jsonl`:

```bash
jq -c -n \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg unix "$(date +%s)" \
  --arg event "swap" \
  --arg from_role "$(cat /tmp/cc-agent-role.state.old 2>/dev/null || echo 'none')" \
  --arg to_role "$(cat /tmp/cc-agent-role.state)" \
  --arg agent "$(whoami)-$(hostname)" \
  '{ts: $ts, unix: $unix, event: $event, from_role: $from_role, to_role: $to_role, agent: $agent}' \
  >> ToDo-JobBoard.jsonl
```

---

## CONTEXT — Agent Instruction Files (Loaded on Swap)

Both agents inherit from `/home/tom/.claude/CLAUDE.md` (constitutional architecture) and load project-specific instructions:

| Role | Project | CLAUDE.md | Comms File | Scope |
|------|---------|-----------|------------|-------|
| `mspc` | MySpace++ | `/data/Projects/MySpace++/CLAUDE.md` | `studio/docs/NOTES-FOR-INFERANCE.md` | Python/DAG/Streamlit |
| `gently` | GentlyOS | `/data/Projects/gently/CLAUDE.md` | `docs/NOTES-FOR-INFERENCE.md` | Rust/.bb/Crystal DAG |

**MySpace++ Agent Context:**
- Dispatcher: `core/cc` (bash, ~130 cmd_X functions)
- Database: `core/lib/db.py` (28-table SQLite, global + per-project)
- Studio: `studio/` (Streamlit, passes, tesseract, weave, lucid, pinterest)
- Phases: 0 (core extraction) → 5 (avatar pipeline)

**GentlyOS Agent Context:**
- Workspace: 175 Rust crates (flat in `crates/`, auto-globbed)
- Runtime: `.bb` stack-machine, Crystal DAG (IPFS + Sui NFT)
- 12 Domains: core, intelligence, runtime, orc, identity, network, chain, mcp, models, social, security, discovery
- MCP: tensorchain.io + DB-root permission system

---

## File-Type Registry & Scoped Operations

**Contamination Rule:** Operations registered for one file type can only touch another file type if an explicit Bridge DAG exists between them.

| File Type | Project(s) | Operations (ordered) | Bridge DAG | SVG Layer | DB Table |
|-----------|-----------|---------------------|------------|-----------|----------|
| `.rs` | gently | `check → build → test → doc → publish` | → `.so` (cargo build) | rust-layer | crates |
| `.bb` | gently | `parse → validate → emit → hash → seal` | → `.svg` (bb-emit) | bb-layer | bb_nodes |
| `.svg` | both | `parse → diff → render → inject-xml → hash` | → `.html` (htmx-swap) | svg-layer | svg_registry |
| `.py` | MySpace++ | `lint → type-check → test → doc → register` | → `.sh` (cc -add-bash) | python-layer | scripts |
| `.sh` | MySpace++ | `shellcheck → register → log → execute` | → `.py` (cc py) | bash-layer | scripts |
| `.sql` | both | `lint → migrate → verify → rollback-ready` | → `.db` (sqlite) | db-layer | schema |
| `.jsonl` | both | `validate → append → hash → reconcile` | → `.db` (import) | data-layer | chains |
| `.md` | both | `lint → link-check → hash → embed` | → `.html` (markdown) | doc-layer | knowledge |
| `.toml` | gently | `validate → resolve → lock → checksum` | → `.rs` (cargo) | config-layer | crates |
| `.yaml` / `.yml` | MySpace++ | `lint → compose → validate → deploy` | → `.sh` (docker) | config-layer | infra |
| `.nix` | both | `fmt → check → build → cache` | → `.sh` (install) | nix-layer | infra |
| `.js` | both | `lint → bundle → minify → hash` | → `.html` (script tag) | web-layer | studio |
| `.html` | MySpace++ | `validate → swap-test → cache → serve` | → `.svg` (embed) | web-layer | studio |
| `.css` | MySpace++ | `lint → purge → minify → hash` | → `.html` (link) | web-layer | studio |
| `.png` / `.jpg` | MySpace++ | `compress → hash → catalog → serve` | → `.html` (img) | asset-layer | media |
| `.fbx` / `.gltf` | MySpace++ | `validate → skin → anim → hash → catalog` | → `.png` (render) | asset-layer | avatar |
| `.mp3` / `.wav` | both | `strip-noise → extract-voice → transcribe → tts-merge` | → `.jsonl` (metadata) | audio-layer | media |
| `.mp4` / `.mov` | MySpace++ | `demux → strip-audio → transcribe → caption` | → `.mp3` (audio) | video-layer | media |
| `.md` (plans) | both | `plan → checkpoint → step → substep → path` | → `.jsonl` (task queue) | plan-layer | plan |

**New File Type Onboarding Protocol:**
When a new file type is introduced to either project:
1. DAG-scanner detects it via `find` + extension registry miss.
2. Master agent assigns a `file-type-onboarding` task to the ensemble.
3. Ensemble produces: operations list, bridge DAG candidates, SVG layer name, DB table name.
4. Master validates and appends to this registry.
5. SVG-emitter produces a new layer node in MASTER-SVG.md.
6. JSONL task queue gets a `type-registered` event.

---

## PLAN — Current Active Plans

### PLAN-001: Cross-Project MASTER-SVG Synchronization

**Owner:** cross-link agent (ensemble: kimi-k2.6:cloud + gpt-oss:120b-cloud)
**Scope:** /data/Projects/MySpace++/ + /data/Projects/gently/
**Goal:** Both projects maintain a single coherent MASTER-SVG.md that names all nodes, edges, layers, and cross-project bridges.

**Checkpoint A: Inventory Completion**
- Step A.1: MySpace++ side lists all SVG nodes (studio/docs/Tesseract.svg, MASTER-INFERENCE.svg, MASTER-INWARD.svg, MASTER-OUTWARD.svg)
- Step A.2: Gently side lists all DAG nodes (CHAIN-OPS-DAG.svg, 175 crates, 12 domain bundles)
- Step A.3: Cross-reference — map shared concepts (genesis, mirror-pass, crystal, bb-runtime)
- Substep A.3.1: Identify nodes with 1:1 peers (e.g., n-genesis ↔ gently:genesis)
- Substep A.3.2: Identify bridge nodes (e.g., n-api-crystal ↔ bridge:crystal_anchor)
- Substep A.3.3: Identify unmapped nodes and assign temporary UIDs
- **Path:** `./studio/docs/NOTES-FOR-INFERANCE.md` → append mapping table

**Checkpoint B: SVG Metadata Injection**
- Step B.1: Every SVG file gets `<dag:metadata>` block with `blake3` hash
- Step B.2: Every SVG file gets `<dag:cross-ref>` block naming peer SVGs
- Step B.3: XML schema validated against shared XSD
- Substep B.3.1: Write shared XSD in `/data/Projects/gently/docs/dag-schema.xsd`
- Substep B.3.2: Mirror XSD in `/data/Projects/MySpace++/planning/dag-schema.xsd`
- **Path:** Each `.svg` file gets inline metadata; XSD is canonical

**Checkpoint C: Reciprocal Verification**
- Step C.1: Hash both project SVG sets and compare
- Step C.2: Run `walker.py` 3-requirement contract against merged node set
- Step C.3: Resolve any mismatches (divergent UIDs, missing edges)
- **Path:** `./planning/DAG_CROSS.md` updated with reconciliation log

**Next Checkpoint after C:** PLAN-002 (Runtime Integration)

---

### PLAN-002: Runtime + Planning Layer Integration

**Owner:** gently-runtime agent (model: qwen3-coder-next:latest)
**Scope:** /data/Projects/gently/ (crates: gently-runtime, bb-runtime-adapter, codie-v4-predict, gently-session)
**Goal:** The runtime MVP (shipped 2026-05-25) now reads from the planning index. Determinism preserved. Byte-identical crystal under enrichment proven.

**Checkpoint A: Enrichment Path Verification**
- Step A.1: `codie-v4-predict` queries planning index via opt-in enrichment
- Step A.2: Verify crystal hash unchanged when enrichment enabled vs disabled
- Step A.3: Cross-impl test passes byte-identical
- **Path:** `./crates/codie-v4-predict/tests/cross_impl.rs`

**Checkpoint B: Chain-Traced Disambiguation**
- Step B.1: NO mosquito classifier model. Agents already classify.
- Step B.2: Chain truth (forward + mirror) + structural index = deterministic ground truth
- Step B.3: Rule-out beats speculate — test with 50 ambiguous inputs
- **Path:** `./crates/gently-bb-trace/tests/disambiguation.rs`

**Checkpoint C: Universal .bb Index Reconciliation**
- Step C.1: 8,165 items indexed across 158 crates
- Step C.2: 95% reconciliation against 338 hand-curated baseline
- Step C.3: Dedup gate live on every claim — test rejection of duplicate insertions
- **Path:** `./crates/gently-bb-dedup/tests/gate.rs`

**Next Checkpoint after C:** PLAN-003 (MySpace++ Phase 0 Completion)

---

### PLAN-003: MySpace++ Phase 0 — Deterministic Core Extraction

**Owner:** mspc-runtime agent (model: qwen3.5:27b)
**Scope:** /data/Projects/MySpace++/core/
**Goal:** Move `cc` from `~/.local/bin/` and `~/.cc/lib/` into a self-contained repo with smoke tests.

**Checkpoint A: File Migration**
- Step A.1: `~/.local/bin/cc` → `core/cc`
- Step A.2: `~/.cc/lib/{db.py,tui.py,studio.py,chain.py,author_cards.py,author_gui.py,author_templates.py,dag_builder.py,template_walker.py}` → `core/lib/`
- Step A.3: `~/.cc/setup/{setup.sh,setup.ps1}` → `core/setup/`
- **Path:** `core/`

**Checkpoint B: Smoke Tests**
- Step B.1: `core/tests/smoke.sh` — `cc -help`, `cc -setup`, `cc scope`, `cc tiny`, `cc -agents`
- Step B.2: `core/tests/determinism.sh` — two identical `cc tiny` calls produce byte-identical output, cache hit verified via mtime
- Step B.3: `core/tests/model-switch.sh` — `cc -model` interactive and direct modes
- **Path:** `core/tests/`

**Checkpoint C: Cross-OS Install**
- Step C.1: `flake.nix` defines `cc` package — `nix run github:tom/MySpace++#cc -- -help`
- Step C.2: `Dockerfile` — under 200 MB without ollama, under 4 GB with 1.5b model
- Step C.3: `install.sh` (Linux/macOS) + `install.ps1` (Windows)
- **Path:** root level package files

**Next Checkpoint after C:** PLAN-004 (Phase 1 — Cross-OS Install + Studio)

---

### PLAN-004: File-Type DAG Scanner & SVG Emitter

**Owner:** dag-scanner agent (model: qwen2.5-coder:1.5b for speed, ensemble for accuracy)
**Scope:** BOTH projects
**Goal:** Every file type in both projects has a DAG node, an SVG layer, and an XML metadata block.

**Checkpoint A: Discovery**
- Step A.1: Scan both project trees, catalog every extension
- Step A.2: Map each extension to known operations (from File-Type Registry above)
- Step A.3: Detect orphans (extensions with no registered operations)
- **Path:** `planning/file_type_catalog.json`

**Checkpoint B: DAG Node Generation**
- Step B.1: For each file type, create `dag_node` entry in global cc.db
- Step B.2: Link nodes via `dag_edges` based on Bridge DAG mappings
- Step B.3: Generate `dag_chains` for common workflows (e.g., `.rs` → `.so` → `.db`)
- **Path:** `cc -dag-bootstrap` (already exists) enhanced with file-type awareness

**Checkpoint C: SVG Layer Emission**
- Step C.1: Each file type gets a colored band in MASTER-SVG.md
- Step C.2: Bands contain mini-DAGs showing operations as connected nodes
- Step C.3: XML metadata injected: `<dag:file-type ext=".rs" project="gently" hash="..." />`
- **Path:** Both `MASTER-SVG.md` files (MySpace++ and gently)

**Next Checkpoint after C:** PLAN-005 (Multi-Model Workflow Library)

---

### PLAN-005: Multi-Model Workflow Library (W2)

**Owner:** workflow-library agent (ensemble: 5 models)
**Scope:** /data/Projects/MySpace++/
**Goal:** Every opcode with a capability card AND a GUI card gets a Claude-authored workflow template. Templates are validated via `cc -template-walk`.

**Checkpoint A: Template Gap Analysis**
- Step A.1: List all opcodes with both cards (`cc -cards` + `cc -gui-cards`)
- Step A.2: List all existing templates (`cc -templates`)
- Step A.3: Identify missing templates
- **Path:** `planning/TEMPLATES.md` gap list

**Checkpoint B: Claude-Authoring Batch**
- Step B.1: For each missing opcode, call `cc -authorize-templates <opcode> --execute`
- Step B.2: Validate each template with `cc -template-walk <name>`
- Step B.3: Fix the recurring `$input_*` vs `$step_N_out` binding bug programmatically
- **Path:** Global cc.db `workflow_templates` table

**Checkpoint C: Multi-Model Dispatch Integration**
- Step C.1: `cc -ensemble` command operational (5 models, same prompt, tagged output)
- Step C.2: `cc -swarm` uses ensemble for synthesis steps, single model for execution steps
- Step C.3: JSONL log of every ensemble run for audit
- **Path:** `~/.cc/ensemble_log.jsonl`

**Next Checkpoint after C:** PLAN-006 (Avatar Pipeline Phase 5)

---

### PLAN-006: TTS / Audio Pipeline (Example Multi-Node Workflow)

**Owner:** tts-pipeline agent (model: minimax-m2.7:cloud for audio, ensemble for orchestration)
**Scope:** /data/Projects/MySpace++/ (media/ subdir)
**Goal:** End-to-end: video/audio input → voice extraction → text extraction → zero-shot TTS → merged output.

**Checkpoint A: Input Acquisition**
- Step A.1: Accept `.mp4`, `.mp3`, `.wav`, or YouTube URL
- Step A.2: Download/cache source file
- Step A.3: Hash and catalog in media DB
- **Path:** `media/inbox/`

**Checkpoint B: Separation**
- Step B.1: Demux video/audio if needed
- Step B.2: Remove background noise (demucs or similar)
- Step B.3: Save isolated voice track + background track separately
- **Path:** `media/stems/`

**Checkpoint C: Transcription**
- Step C.1: Transcribe isolated voice to text (whisper-style)
- Step C.2: Save `.txt` and `.jsonl` (with timestamps)
- Step C.3: Validate transcription quality (word-count sanity check)
- **Path:** `media/transcripts/`

**Checkpoint D: Zero-Shot TTS**
- Step D.1: Feed voice sample + text to TTS model
- Step D.2: Generate new audio with cloned voice
- Step D.3: Merge with background track if requested
- **Path:** `media/output/`

**Checkpoint E: Validation & SVG Log**
- Step E.1: Listening test (human or heuristic)
- Step E.2: Generate SVG showing pipeline nodes: `[Input] → [Demux] → [Separate] → [Transcribe] → [TTS] → [Merge] → [Output]`
- Step E.3: XML metadata block with hash, model IDs, timestamp
- **Path:** `media/output/pipeline.svg`

**Next Checkpoint after E:** Return to PLAN-001 cycle (continuous sync)

---

### PLAN-007: Browser Runtime Loop Orchestration ⭐ NEW

**Owner:** runtime-integrator agent (model: kimi-k2.6:cloud)
**Scope:** BOTH projects · droplet-hosted · all browsers
**Goal:** Rust runtime loops every 5000ms, reads ToDo-JobBoard.md + JSONL, effects every file, syncs all MASTER-SVGs into 1 coherent chain. Browser pool (8 HTMX/SVG instances) orchestrates inference across layers. Tasks accent each other via cross-reference in JSONL. Chain coherence enforced.

**Checkpoint A: Runtime Loop Wiring**
- Step A.1: Rust runtime reads ToDo-JobBoard.md on every tick ✓ _Completed 2026-05-28T00:55Z_
- Step A.2: Every file type mapped to DAG node (File-Type Registry) ✓ _Completed 2026-05-28T00:55Z_
- Step A.3: Runtime loop tick = 5000ms (configurable via GENTLY_TICK_MS) ✓ _Completed 2026-05-28T00:55Z_
- Step A.4: Browser pool = 8 HTMX/SVG instances (browser-0..browser-7) ✓ _Completed 2026-05-28T00:55Z_
- Step A.5: Inference rotates across browser layers (each targets specific passes, ignores others) ✓ _Completed 2026-05-28T00:55Z_
- Step A.6: Chain coherence = accent lines verified between interdependent tasks ✓ _Completed 2026-05-28T00:55Z_
- Step A.7: Droplet bridge deployed (`159.89.181.146:8765`) — health OK, 17 tools, dashboard live ✓ _Completed 2026-05-28T18:26Z_
- **Path:** `MASTER-TODO.svg` (this plan's visual dashboard) — **script:** `scripts/todo-runtime-loop.py`

**Checkpoint B: Browser Pool Activation**
- Step B.1: browser-0 (MASTER-INWARD) — forward-ingest view, read-only
- Step B.2: browser-1 (MASTER-OUTWARD) — mirror-export view, read-only
- Step B.3: browser-2 (INFERENCE SCHED) — scheduler + budget router, ACTIVE
- Step B.4: browser-3 (JOB BOARD) — this file (MASTER-TODO), dashboard
- Step B.5: browser-4 (DEPTH PASS) — Depth/Pose2D/Pose3D inference worker
- Step B.6: browser-5 (COMPOSITE) — Composite/Bokeh/Merge worker
- Step B.7: browser-6 (IMAGE GEN) — ImageGen/SegFigure worker
- Step B.8: browser-7 (VIDEO GEN) — VideoGen/Lipsync worker
- **Path:** `browser-pool/` directory (8 SVG state files)

**Checkpoint C: Chain Coherence Enforcement**
- Step C.1: Accent lines between tasks verified (no circular deps)
- Step C.2: JSONL tail hash matches board hash on every tick
- Step C.3: Mirror-pair crystal (MASTER-INWARD ↔ MASTER-OUTWARD) validated
- Step C.4: If drift detected: runtime HOLDs affected browsers, audits, recovers
- Step C.5: All failures logged in JSONL with error + recovery path
- **Path:** `REFLECTION.md` + `gently-mirror-pair` daemon (T-3 from Q-GENTLY-001)

**Next Checkpoint after C:** Return to PLAN-001 cycle (continuous sync)

---

## RULES — Non-Breakable

| # | Rule | Violation Consequence |
|---|------|----------------------|
| R-001 | No agent modifies another agent's active block without explicit handoff in JSONL. | Revert + audit log entry. Offending agent barred from next 3 tasks. |
| R-002 | No file-type operation crosses project boundary without a Bridge DAG. | Operation rejected by `dag_builder.py`. Error logged. |
| R-003 | No plan checkpoint is marked complete unless all substeps have verified paths to the next checkpoint. | Master agent must reject the completion claim. Checkpoint stays open. |
| R-004 | No SVG is emitted without `<dag:metadata>` block containing `blake3` hash, owner, timestamp. | SVG is treated as untrusted. Runtime refuses to parse it. |
| R-005 | No model dispatch exceeds 5 concurrent calls. Queue manager enforces this. | Excess calls are held in `cc -dag-build` queue until slot opens. |
| R-006 | Cloud models (`:cloud` suffix) are ONLY used for synthesis/audit. Local models handle execution/classification. | Budget overrun prevention. Cloud calls logged with token estimate. |
| R-007 | JSONL is append-only. Rows are NEVER deleted. Status changes are new rows. | Any deletion attempt is caught by hash chain mismatch. |
| R-008 | The Master agent MUST check the work of smaller agents before opening the GO gate. | If GO is issued without verification, Master loses session token for 1 hour. |
| R-009 | MySpace++ and gently/ are co-owners of MASTER-SVG.md. Neither project can unilaterally redefine shared nodes. | Disputes resolved by ensemble consensus (3-of-5 models agree). |
| R-010 | Every new file type MUST complete the onboarding protocol before any agent operates on it. | Unregistered file types are quarantined in `media/unscanned/`. |
| R-011 | All multi-node workflows MUST produce a UI/UX SVG explanation. | Workflow is incomplete without it. Cannot advance to next checkpoint. |
| R-012 | Scope is canon. Work outside `/data/Projects/MySpace++/` or `/data/Projects/gently/` requires bridge DAG + explicit approval. | Out-of-scope work is silently dropped by the runtime. |

---

## PATH — Canonical Directory Map

```
/data/Projects/MySpace++/
├── core/                    # cc deterministic core (Phase 0)
│   ├── cc                   # bash dispatcher
│   ├── lib/                 # db.py, tui.py, studio.py, chain.py, ...
│   ├── setup/               # install scripts
│   └── tests/               # smoke, determinism, model-switch
├── planning/                # DAGs, plans, templates, architecture
│   ├── DAG.md               # auto-generated from dag_generator.py
│   ├── DAG_CROSS.md         # cross-project DAG mapping
│   ├── PLAN.md              # phased build plan
│   ├── TEMPLATES.md         # workflow template catalog
│   ├── WORKFLOW_LIBRARY.md  # W1 / W2 status
│   ├── file_type_catalog.json  # auto-generated file type registry
│   └── dag-schema.xsd       # shared SVG metadata schema
├── studio/                  # Streamlit studio + Tesseract
│   ├── docs/                # Tesseract.svg, TWINS-MASTER.svg, NOTES-FOR-INFERANCE.md
│   ├── tesseract/           # walker.py, inventory.py, svg.py
│   └── auth/                # gate.py, keys.sqlite
├── media/                   # audio/video pipeline I/O
│   ├── inbox/               # raw uploads
│   ├── stems/               # separated tracks
│   ├── transcripts/         # text + jsonl
│   └── output/              # final render + pipeline.svg
├── ToDo-JobBoard.md         # THIS FILE — human + agent hub
├── ToDo-JobBoard.jsonl      # Sibling — append-only task state
├── MASTER-INFERENCE.svg     # scheduler SVG
├── MASTER-INWARD.svg      # inward pass SVG
├── MASTER-OUTWARD.svg     # outward pass SVG
└── GENTLY-TESSERACT.svg     # reference 7-layer template

/data/Projects/gently/
├── crates/                  # 175 Rust crates
│   ├── gently-runtime/      # Predict/Execute/Terminate traits
│   ├── bb-runtime-adapter/  # .bb Execute slot
│   ├── codie-v4-predict/    # ollama HTTP + template fallback
│   ├── gently-session/      # session lifecycle
│   ├── gently-bb-struct/    # S-expr structural index
│   ├── gently-bb-scraper/   # crate scraper
│   ├── gently-bb-trace/   # chain-traced disambiguation
│   └── gently-bb-dedup/     # dedup gate
├── db/                      # schema/*.sql (8 files)
├── src/                     # orchestration tools (crm.js, cell, plan.js, task-graph)
├── hooks/                   # 7 lifecycle hooks
├── docs/                    # MASTER_PLAN.md, DAG-CROSS-LINK.md, dag-schema.xsd
├── templates/               # tesseract SVG templates
├── scripts/                 # automation scripts
├── CHAIN-OPS-DAG.svg        # operation DAG (cross-linked to MySpace++)
├── CLAUDE.md                # project instructions
└── REGISTRY.md              # 157 crates + tools + schemas
```

---

## LOOPS — Iteration Controls

| Loop ID | Trigger | Condition | Max Iter | Models |
|---------|---------|-----------|----------|--------|
| L-001 | Checkpoint incomplete | Substep path not verified | 10 | ensemble (3 local + 2 cloud) |
| L-002 | DAG build queue non-empty | `cc -dag-build --loop` | ∞ | qwen2.5-coder:1.5b |
| L-003 | Template walk failure | Binding bug detected | 5 | qwen3.5:0.8b |
| L-004 | Cross-project sync drift | SVG hash mismatch | 3 | ensemble (full 5) |
| L-005 | Audio pipeline listening test fail | Output rejected by heuristic | 5 | minimax-m2.7:cloud + local audio model |
| L-006 | File type orphan detected | New extension found | 1 | qwen2.5-coder:1.5b (fast classification) |
| L-007 | Master audit rejection | Worker output fails verification | 3 | same model as worker + 1 cloud auditor |

**Loop Rule:** Every loop iteration appends a row to `ToDo-JobBoard.jsonl` with `loop_id`, `iteration`, `status`, and `hash_of_prior_state`. This makes loops auditable and recoverable.

---

## MODEL — Agent-to-Model Assignment Matrix

| Agent Role | Primary Model | Fallback Model | Task Types | Max Concurrent |
|------------|--------------|---------------|------------|---------------|
| Master | kimi-k2.6:cloud | gpt-oss:120b-cloud | Audit, sync, plan validation, GO gate | 1 (serial audit) |
| mspc-runtime | qwen3.5:27b | qwen3:14b | Code gen, bash, python, tests | 2 |
| gently-runtime | qwen3-coder-next:latest | codie-v4:latest | Rust, .bb, cargo, schema | 2 |
| cross-link | ensemble (5) | — | Consensus tasks, dispute resolution | 5 |
| dag-scanner | qwen2.5-coder:1.5b | qwen2.5:0.5b | Classification, cataloging, fast loops | 3 |
| tts-pipeline | minimax-m2.7:cloud | qwen3-vl:235b-cloud | Audio synthesis, voice cloning | 2 |
| svg-emitter | qwen3.5:27b | bb-maker:latest | SVG generation, XML injection, hash | 2 |
| audio-qa | human + minimax-m2.7:cloud | — | Listening test, quality gate | 1 |
| workflow-library | ensemble (5) | — | Template authoring, validation, bug fixes | 5 |
| db-migrate | qwen2.5-coder:1.5b | — | SQL, schema, migration | 1 |
| runtime-integrator | kimi-k2.6:cloud | gpt-oss:120b-cloud | Browser pool, rust loop, MASTER-TODO sync, coherence audit | 1 |

**Ensemble Dispatch Format:**
```bash
cc -ensemble "prompt text here" \
   -models "kimi-k2.6:cloud,qwen3.5:27b,qwen3-coder-next:latest,qwen2.5-coder:1.5b,minimax-m2.7:cloud"
```
Output: JSONL stream, one row per model, tagged with `model`, `response`, `hash`, `done_seen`.

---

## RUNTIME LOOP — Rust Tick + File Effects

**The rust runtime (`gently-runtime` crate) runs a continuous loop on the droplet:**

```
every 5000ms (configurable via GENTLY_TICK_MS):
  1. READ  ToDo-JobBoard.md + ToDo-JobBoard.jsonl tail
  2. PARSE active tasks, gates, agent assignments
  3. EFFECT every file listed in "EFFECTED FILES" (see MASTER-TODO.svg)
  4. VALIDATE chain coherence (accent lines + crystal hashes)
  5. WRITE  updated state back to:
     - MASTER-INWARD.svg  (if forward nodes changed)
     - MASTER-OUTWARD.svg (if mirror nodes changed)
     - MASTER-INFERENCE.svg (if scheduler state changed)
     - MASTER-TODO.svg     (this file — always)
     - ToDo-JobBoard.jsonl (append-only)
  6. NOTIFY browser pool via HTMX trigger (each browser swaps its layer)
  7. SLEEP until next tick
```

**Y-Combinator Feedback:**
- Runtime output → board input → runtime next tick
- Self-reference via `SealedChain.crystal` (runtime reads its own prior output)
- Self-clean triggers: genesis mismatch, mirror drift, orphan nodes

**Determinism Guarantee:**
- Same board state + same tick = same file effects (byte-identical)
- Crystal hash covers: runtime binary + board state + browser pool state

---

## BROWSER POOL — 8 HTMX/SVG Instances

**Each browser is a layer. It targets specific passes. It ignores others.**

| Browser | Layer | SVG | Role | Pass Target | Ignores |
|---------|-------|-----|------|-------------|---------|
| browser-0 | forward-ingest | MASTER-INWARD.svg | View | read-only | all inference |
| browser-1 | mirror-export | MASTER-OUTWARD.svg | View | read-only | all inference |
| browser-2 | scheduler | MASTER-INFERENCE.svg | Dispatch | budget router, pass allocation | worker passes |
| browser-3 | job-board | MASTER-TODO.svg | Dashboard | task tracking, GO/HOLD gates | inference |
| browser-4 | depth-pass | browser-4.svg | Worker | Depth, Pose2D, Pose3D | composite, gen |
| browser-5 | composite | browser-5.svg | Worker | Composite, Bokeh, Merge | depth, gen |
| browser-6 | image-gen | browser-6.svg | Worker | ImageGen, SegFigure | video, depth |
| browser-7 | video-gen | browser-7.svg | Worker | VideoGen, Lipsync | image, depth |

**Accent Rule:**
- A browser NEVER reads another worker's layer directly.
- All inter-browser data flows through browser-5 (composite) or browser-2 (sched).
- If browser-5 detects missing input, it HOLDs and signals browser-3.
- browser-3 writes the HOLD to JSONL → runtime loop audits on next tick.

**HTMX Trigger:**
```html
<!-- Each browser page has this trigger -->
<div hx-get="/api/browser-state"
     hx-trigger="every 5s, todo-updated from:body"
     hx-target="#browser-layer"
     hx-swap="outerHTML">
  <!-- SVG injected here by runtime -->
</div>
```

---

## MASTER-SVG.md Joint Maintenance Contract

**Both projects (MySpace++ and gently) are co-owners.**

### Shared Node Registry
Nodes prefixed with `bridge:` are shared. Both SVGs MUST name each other in `<dag:cross-ref>`.

| Bridge Node | MySpace++ Counterpart | Gently Counterpart | Status |
|-------------|----------------------|-------------------|--------|
| bridge:genesis | n-genesis | gently:genesis | SYNCED |
| bridge:mirror | n-op-invert, n-mirror-extend, ... | gently:mirror | SYNCED (7↔1 mapping) |
| bridge:crystal | n-crystal-seal-* | gently:crystal | SYNCED |
| bridge:bb_runtime | n-bb-dispatch, n-stack-store, ... | gently:bb_runtime | SYNCED |
| bridge:session | n-user-visit | gently:session | SYNCED |
| bridge:key_vault | n-friend-key | telos-blind-vault | PENDING |
| bridge:crystal_anchor | n-api-crystal | gently:crystal + IPFS | PENDING |
| bridge:tabpfn | n-tabpfn-leaf | mspc:tabpfn | PENDING |

### Maintenance Cadence
1. **Every session start:** Read the other project's MASTER-SVG.md hash.
2. **If hashes differ:** Run cross-link ensemble to reconcile.
3. **Every session end:** Append `Updated by: <project> at <iso-ts>` to NOTES-FOR-INFERANCE.md.
4. **No session end without a hash update** if any node was touched.

---

## DAG Schema — XML Metadata Format

Every SVG workflow MUST contain this block:

```xml
<dag:metadata xmlns:dag="http://gentlyos.org/dag/1.0">
  <dag:file-type ext=".mp4" project="MySpace++" />
  <dag:workflow id="tts-pipeline" plan="PLAN-006" checkpoint="D" />
  <dag:hash algo="blake3" value="a1b2c3..." />
  <dag:owner agent="tts-pipeline" model="minimax-m2.7:cloud" />
  <dag:timestamp iso="2026-05-26T18:00:00Z" unix="1716746400" />
  <dag:scope path="/data/Projects/MySpace++/media/" />
  <dag:models>
    <dag:model name="minimax-m2.7:cloud" role="synthesis" />
    <dag:model name="kimi-k2.6:cloud" role="audit" />
  </dag:models>
  <dag:gate status="GO" next="audio-qa" />
  <dag:cross-ref>
    <dag:peer svg="MASTER-INFERENCE.svg" hash="d4e5f6..." />
    <dag:peer svg="CHAIN-OPS-DAG.svg" hash="g7h8i9..." />
  </dag:cross-ref>
</dag:metadata>
```

**Validation:** `cc -dag-bootstrap` verifies every SVG against `dag-schema.xsd` before adding nodes to the cache.

---

## JSONL Task Queue — Append-Only State

**File:** `ToDo-JobBoard.jsonl` (sibling to this `.md`)

**Schema (one JSON object per line):**
```json
{
  "ts": "2026-05-26T18:00:00Z",
  "unix": 1716746400,
  "hash": "blake3_of_prior_line_concatenated_with_this_row",
  "event": "task|checkpoint|step|substep|gate|audit|loop|error|sync",
  "task_id": "T-001",
  "plan_id": "PLAN-001",
  "checkpoint": "A",
  "step": "A.1",
  "substep": "",
  "agent": "master",
  "model": "kimi-k2.6:cloud",
  "status": "active|pending|complete|failed|held",
  "gate": "GO|HOLD",
  "benchmark": "description of completion criterion",
  "next_agent": "mspc-runtime",
  "path": "./studio/docs/NOTES-FOR-INFERANCE.md",
  "svg_hash": "hash of associated SVG if any",
  "error": "",
  "meta": {}
}
```

**Hash Chain:** Each row's `hash` field = `blake3(prev_hash + json_string_of_this_row_without_hash_field)`. This makes the JSONL tamper-evident.

**Query:** `jq -c 'select(.task_id=="T-001")' ToDo-JobBoard.jsonl | tail -1` gives the latest state of any task.

---

## Contamination Boundaries

**Rule:** Workflows are scoped by project + file type. Cross-contamination is prevented by:

1. **File-Type Quarantine:** Unregistered types go to `media/unscanned/` until onboarding completes.
2. **Bridge DAG Enforcement:** `dag_builder.py` refuses edges between nodes without an explicit bridge.
3. **Agent Session Scope:** `CC_SCOPE_LOCAL_ROOT` constrains the agent to one project root. Escape requires `-set-project` + bridge DAG proof.
4. **SVG Metadata Scope:** `<dag:scope>` element names the allowed path. Runtime rejects SVGs whose scope doesn't match the agent's cwd.
5. **Model Project Affinity:** Models are tagged with project affinity. A `gently`-tagged model won't generate MySpace++-specific code unless the bridge DAG is present in its context.

---

## UI/UX Layer Requirements for Multi-Node Workflows

Every workflow with 2+ nodes MUST produce an SVG explanation showing:

1. **Nodes:** Each step as a geometric shape (circle = input, square = process, diamond = decision, hexagon = output).
2. **Edges:** Labeled arrows showing data flow. Color = project (teal = gently, pink = MySpace++, purple = bridge).
3. **Layers:** Vertical bands per project or subsystem. Nodes stay within their band unless crossing a bridge edge.
4. **Active Highlight:** The currently executing node pulses. Completed nodes are solid. Pending nodes are dashed.
5. **Metadata Panel:** Side panel (or tooltip) showing: agent name, model, hash, timestamp, gate status.
6. **Legend:** Color key, shape key, bridge symbol explanation.

**Example: TTS Pipeline SVG Structure**
```
[ Input Band ]
  ○ raw.mp4  ──► □ demux  ──► □ separate
                                    │
[ Processing Band ]                  ▼
  □ transcribe ◄── voice.wav  □ noise-removal
       │                              │
       ▼                              ▼
  ○ transcript.txt              ○ bg_music.wav
       │
[ Synthesis Band ]
       ▼
  □ zero-shot-tts ──► ○ output.wav
       │
[ Output Band ]
       ▼
  ○ pipeline.svg (this file)
```

---

## Session Ownership Log

| Session ID | Owner | Project | Started | Last Activity | Active Tasks |
|------------|-------|---------|---------|---------------|-------------|
| __OWNER_PLACEHOLDER__ | master | both | __TS_PLACEHOLDER__ | __TS_PLACEHOLDER__ | T-001, T-004 |

**Session Handoff Protocol:**
1. Current owner appends `handoff: {from: X, to: Y, reason: Z}` to JSONL.
2. New owner reads the JSONL tail, confirms ownership by appending `claim: {owner: Y}`.
3. Until claim is confirmed, previous owner retains veto rights for 5 minutes.

---

## Quick Reference — Agent Commands

### Role Switching (kimi-k2.6:cloud multi-agent support)

**AUTOMATED SWAP ACTIVATION** — Single command executes all 6 steps:

```bash
# Auto-detect role from Task Board and execute full swap protocol
/data/Projects/MySpace++/scripts/agent-swap-activate.sh auto

# Or specify role explicitly
/data/Projects/MySpace++/scripts/agent-swap-activate.sh mspc
/data/Projects/MySpace++/scripts/agent-swap-activate.sh gently
```

**Manual Commands** (if not using automated script):

```bash
# 1. Check current role
cat /tmp/cc-agent-role.state

# 2. Execute role switch (matches Task Board "Next Agent" column)
/data/Projects/MySpace++/scripts/agent-role-switch.sh mspc   # or: gently

# 3. Source environment variables (exports CC_SCOPE_LOCAL_ROOT, CC_AGENT_ROLE)
source /data/Projects/MySpace++/scripts/cc-role-check.sh

# 4. Verify activation
/data/Projects/MySpace++/scripts/agent-role-switch.sh status

# 5. Read project CLAUDE.md + comms file (per role)
#    MySpace++: cat studio/docs/NOTES-FOR-INFERANCE.md
#    GentlyOS:  cat /data/Projects/gently/docs/NOTES-FOR-INFERENCE.md

# 6. Log swap in JSONL (append to ToDo-JobBoard.jsonl)
echo '{"ts":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","event":"swap","to_role":"mspc"}' >> ToDo-JobBoard.jsonl
```

**Manual Commands:**

```bash
# Full 6-step swap activation (automated)
/data/Projects/MySpace++/scripts/agent-swap-activate.sh auto   # or: mspc, gently

# Show current role and active instructions
/data/Projects/MySpace++/scripts/agent-role-switch.sh status

# Switch to MySpace++ agent role (Python/DAG scope)
/data/Projects/MySpace++/scripts/agent-role-switch.sh mspc

# Switch to GentlyOS agent role (Rust/.bb scope)
/data/Projects/MySpace++/scripts/agent-role-switch.sh gently

# Start interactive loop mode (prompt for role each iteration)
/data/Projects/MySpace++/scripts/agent-role-switch.sh loop

# Source in current shell to set CC_* env vars
source /data/Projects/MySpace++/scripts/cc-role-check.sh
```

**Script Inventory:**

| Script | Purpose |
|--------|---------|
| `agent-swap-activate.sh` | Full 6-step swap protocol (auto-detect + JSONL logging) |
| `agent-role-switch.sh` | Interactive role switcher (status/loop modes) |
| `cc-role-check.sh` | Source-able helper for environment variables |

**Role State File:** `/tmp/cc-agent-role.state` (holds `mspc`, `gently`, or `none`)

**Environment Variables Set by Role:**
| Role | CC_SCOPE_LOCAL_ROOT | CC_AGENT_ROLE |
|------|---------------------|---------------|
| `mspc` | `/data/Projects/MySpace++/` | `mspc` |
| `gently` | `/data/Projects/gently/` | `gently` |

### Standard CC Commands

```bash
# Set the default model (interactive picker)
cc -model

# Set directly
cc -model qwen3.5:27b

# List all models with load status
cc -model list

# Dispatch to 5 models at once (ensemble)
cc -ensemble "summarize this architecture" \
   -models "kimi-k2.6:cloud,qwen3.5:27b,qwen3-coder-next:latest,qwen2.5-coder:1.5b,minimax-m2.7:cloud"

# Start a plan phase
cc phase start "PLAN-001 Checkpoint A"

# Run a step (uses default model)
cc phase step "list all SVG nodes in studio/docs/"

# Run a step with specific model
cc phase step -model qwen2.5-coder:1.5b "catalog file extensions"

# Check dag status
cc -dag-status

# Bootstrap file-type aware DAG
cc -dag-bootstrap

# Walk a template (dry run)
cc -template-walk <name>

# Show active task board (this reads ToDo-JobBoard.jsonl)
cc tiny "show me the latest task state from /data/Projects/MySpace++/ToDo-JobBoard.jsonl"
```

---

## Append-Only Audit Trail

*This section is append-only. Never delete lines. Add new entries at the bottom.*

- `[x] 2026-05-26T18:00:00Z — Board created by master agent. Plans 001-006 initialized. File-type registry seeded with 20 types. Hash chain genesis block written to JSONL.`
- `[ ] 2026-05-26T18:00:00Z — T-001 active: master maintaining board hygiene. Waiting for first checkpoint completion.`

---

## Append-Only Audit Trail

*This section is append-only. Never delete lines. Add new entries at the bottom.*

- `[x] 2026-05-26T18:00:00Z — Board created by master agent. Plans 001-006 initialized. File-type registry seeded with 20 types. Hash chain genesis block written to JSONL.`
- `[ ] 2026-05-26T18:00:00Z — T-001 active: master maintaining board hygiene. Waiting for first checkpoint completion.`
- `[x] 2026-05-27T02:44:43Z — T-001 HYGIENE AUDIT COMPLETE: Board hash updated (sha256:1cb8df5e...), JSONL entries: 10 (6 task, 2 swap, 1 sync, 1 hygiene). Role-swap scripts integrated (agent-swap-activate.sh, agent-role-switch.sh, cc-role-check.sh). SWAP ACTIVATION protocol added to SYSTEM contract (Rules 11-12). Both role swaps tested: mspc ✓, gently ✓.`

---

*End of ToDo-JobBoard.md. All agents must honor the SYSTEM contract above. Violations are logged in JSONL and adjudicated by the Master.*
- [x] 2026-05-27T03:00:00Z — T-007 ACTIVE: runtime-integrator (kimi-k2.6:cloud) created MASTER-TODO.svg + PLAN-007 Browser Runtime Loop Orchestration. Board hash updated (sha256:57c09c91...), JSONL entries: 11, browsers: 8, tick: 5000ms. Runtime loop spec + browser pool docs added to ToDo-JobBoard.md.
