# MySpace++ Design Principles — Compiled Canon

> **This document is the single compiled source of truth for every design principle, rule, mandate, philosophy, and architectural decision found across all documentation in the MySpace++ project.**
>
> **Sources**: `CLAUDE.md` · `README.md` · `CONSOLIDATION.md` · `REFLECTION.md` · `ToDo-JobBoard.md` · `VM-CONSOLIDATION.md` · `DAG.md` · `DAG-GUI.md` · `DAG-FLOW.md` · `PASSES_DAG.md` · `LAYOUT.md` · `LUCID_INTEGRATION.md` · `DEFOLD-INTEGRATION.md` · `NOTES-FOR-INFERANCE.md` · `TWINS-MASTER.md` · `TESSERACT.md` · `WEAVE.md` · `RUST-CHAIN.md` · `ARCHITECTURE.md` · `PLAN.md` · `WORKFLOW_LIBRARY.md` · `TEMPLATES.md` · `PIPELINES.md` · `PATH_BUILDER.md` · `DAG_CROSS.md` · `TABPFN_ROUTER.md` · `AVATAR_ASSETS.md` · `NOTES-ON-3d-INFERANCE.md` · `PORTABILITY.md` · `LICENSE.draft.md` · `OPEN_QUESTIONS.md`
>
> **How to update**: Add new principles here and append the source file. Never remove. Principles accumulate.

---

## Table of Contents

1. [Core Philosophy](#1-core-philosophy)
2. [Architecture & System Design](#2-architecture--system-design)
3. [Determinism & Content-Addressing](#3-determinism--content-addressing)
4. [Governance & Orchestration](#4-governance--orchestration)
5. [Data & Persistence](#5-data--persistence)
6. [Security & Auth](#6-security--auth)
7. [Cross-Half Coordination (MSPC ↔ GENTLY)](#7-cross-half-coordination-mspc--gently)
8. [Filesystem & Naming](#8-filesystem--naming)
9. [Inference & Model Dispatch](#9-inference--model-dispatch)
10. [Frontend & UX](#10-frontend--ux)
11. [Visualization & DAG](#11-visualization--dag)
12. [Compute & Infrastructure](#12-compute--infrastructure)
13. [Build & Deployment](#13-build--deployment)
14. [Multi-Tenancy & SaaS](#14-multi-tenancy--saas)
15. [Prohibitions](#15-prohibitions)

---

## 1. Core Philosophy

### The Thesis
- **Deterministic-first terminal substrate.** The system is a terminal substrate for orchestrating local and frontier AI models. Determinism is the default; frontier models are the escalation path, not the entry point. *(README.md)*
- **Deterministic small-model dispatch is enough for most agent tasks.** Frontier models (Claude, Codex) belong on the escalation path, not the default path. *(README.md · ARCHITECTURE.md)*
- **"Use what is built to build more."** Permanent operating mandate. Before writing ANY code, check in order: 1. REGISTRY.md, 2. src/*.js, 3. db/schema/*.sql, 4. hooks/, 5. BB.md. *(CLAUDE.md — GentlyOS Prime Directive)*
- **"The whole point of this repo is to prove that what's already built is sufficient."** Every new file should make existing core reachable from somewhere new, not duplicate existing functionality. *(PLAN.md)*
- **"One substrate, many UIs."** `cc tui`, `cc studio`, future `cc chat` all share sqlite tables and agent lifecycle. *(README.md)*
- **"The substrate is the only mandatory layer."** A user with just `cc` + bash + python3 + sqlite has a working system. Everything else is opt-in. *(ARCHITECTURE.md)*
- **"No daemon. `cc` is a one-shot command. State is in sqlite."** *(ARCHITECTURE.md)*
- **"Super-LLM by Default" thesis:** raw data → Tesseract DAG → pass outputs → SVG layers + vector DB → gemini-nano in browser → Rust engine → correlation_id = `blake3(mspc_hash || gently_hash)` → Crystal DAG. This combination creates organized super intelligence for free. *(README.md)*
- **Organized speech:** Every pass output is addressable via `data-walk-id`, `data-walk-neighbors`, `data-walk-subjects`. Not unstructured text; a knowledge graph with explicit relationships. *(README.md)*
- **Part-sentence driven:** `hash_loop_decompile()` creates discrete "thought steps" independently addressable. You get a chain of hash-reflection points, not a blob of text. *(README.md)*
- **Free of charge:** The intelligence emerges from mirror synchrony between the already-running Rust runtime and Python side, not from training a new model. *(README.md)*
- **Self-referential:** Every output is itself a content-addressable key into the same store. *(RUST-CHAIN.md)*
- **Self-cleaning:** Tampering is detected by replaying the chain. *(RUST-CHAIN.md)*
- **"The external models are optional perception adapters, not the spine."** Same chain; external models act as PERCEPTION BRIDGES. *(NOTES-ON-3d-INFERANCE.md)*

### Value System
- **Sovereignty:** Every byte is on the droplet, no third-party JS, no external auth. *(CONSOLIDATION.md)*
- **Privacy:** No analytics beacon, no email collection, no consent gates. *(CONSOLIDATION.md)*
- **Cost target:** $5/mo droplet vs $9.95/user/mo Lucid Pro per user. *(CONSOLIDATION.md)*
- **"Unfuckability":** Lucid's document model, formula engine, reference keys, and locks are exactly the robustness levers wanted. *(LUCID_INTEGRATION.md)*
- **Drift between doc and code is the most expensive drift.** Fix the code first if needed, then rebuild the doc. *(TWINS-MASTER.md)*

---

## 2. Architecture & System Design

### Layered Architecture
- **Three-layer architecture with strict dependency direction:** Frontends → Adapters → Substrate. Lower layers never depend on upper layers. *(ARCHITECTURE.md)*
- **Two-halves architecture:** MySpace++ (Python/bash/Streamlit user-facing) and GentlyOS (Rust/`.bb`/crystal deterministic runtime). *(CLAUDE.md)*
- **Dual-Loop Architecture:** MSPC Loop (Python/HTMX: input → BLAKE3 hash → invert_hash iterations → visible UI/asset) and GENTLY Loop (Rust/.bb/crystal: opcode → OpKind → .bb program hash → mirror-pass → crystal hash → mirror of MSPC loop). *(README.md)*
- **The browser becomes the runtime extension:** Every visit = chain step; cookies = cache key; SVG response is the full UI; HTMX swaps fragments. No SPA, no separate pages, no ads, no logins. *(CONSOLIDATION.md)*

### Components
- **Tesseract meta-DAG:** 8 source DAGs, 253 nodes, 729 edges. The master SVG is the source of truth; this file is a reading guide. *(TESSERACT.md)*
- **Two SVGs, one chain:** `Tesseract.svg` (inventory — WHAT exists) and `MASTER-INFERENCE.svg` (scheduler — HOW it runs). They are NOT redundant; they have orthogonal responsibilities. The new SVG points into the existing one; never duplicates data. *(CONSOLIDATION.md · REFLECTION.md)*
- **Reflection contract:** Two SVGs, one chain. Every node on one side has exactly one mirror node on the other side, bound by a shared ID. *(REFLECTION.md)*
- **Mirror-pass anti-particle:** Every op has its inverse at the mirror position in the chain. `crystal = blake3(chain ⊕ anti_chain)`. Tampering requires erasing both. *(RUST-CHAIN.md · REFLECTION.md)*
- **SVG is the document. SQLite is the truth. The relay is the courier. The browser is the worker. The PLANS decide.** *(WEAVE.md)*
- **No single piece is special — any of them can be replaced without breaking the rest.** *(WEAVE.md)*

### Modularity
- **WEAVE doesn't replace anything.** It layers on top of passes/pieces_index/timing. *(WEAVE.md)*
- **The worker page is content-only** (no eval, no Function constructor, no untrusted imports). *(WEAVE.md)*
- **"No asset generation step."** Body + face come from the bundle; frontier models only touch text/audio/face-pixel transformations. *(AVATAR_ASSETS.md)*

---

## 3. Determinism & Content-Addressing

### Determinism Contract
- **Every model call goes through `temp=0, seed=42`** and a `sha256(model + prompt + opts)` cache. Same input produces same output byte-for-byte. *(README.md · ARCHITECTURE.md)*
- **Determinism contract:** same `.bb` + same `seed.json` = same crystal hash, byte for byte, every time. *(RUST-CHAIN.md)*
- **Determinism guarantee:** same board state + same tick = same file effects (byte-identical). Crystal hash covers runtime binary + board state + browser pool state. *(ToDo-JobBoard.md)*
- **Determinism:** rust chain crystal hashes mean re-runs are byte-identical. *(CONSOLIDATION.md)*
- **Genesis-anchored:** The runtime emits its own hash as `chain[0]`. Self-recognizes; can detect impersonation. *(RUST-CHAIN.md)*

### Content-Addressing
- **Crystal hash = XOR-chain of all `.bb` step hashes.** *(RUST-CHAIN.md)*
- **Crystal hash in `<metadata>` is the deterministic identity of the WHOLE pair;** mismatched bytes mean someone touched one without the other. *(REFLECTION.md)*
- **Crystal/piece interface:** When MySpace++ runs an opcode whose execution should produce a chain extension, the piece's `content_hash` should equal the crystal's blake3 hash. *(RUST-CHAIN.md · NOTES-FOR-INFERANCE.md)*
- **Correlation ID:** `sha256(mspc_hash || gently_hash)` appears in BOTH halves' cadence logs. *(README.md)*
- **Correlation:** `hash_loop_decompile` finds where MSPC's hash becomes GENTLY's hash through iterative inversion. This is the "reflection point." *(README.md)*
- **The correlation point is found by both halves running `hash_loop_decompile(initial_hash, iterations)` and seeing the same alternating pattern.** *(NOTES-FOR-INFERANCE.md)*
- **Updates are null-addressed no-op extensions — never mutations of past entries.** *(RUST-CHAIN.md)*
- **Pin to IPFS → mint as Sui NFT → the `.bb` IS the on-chain artifact.** *(RUST-CHAIN.md)*
- **Self-reference:** A crystal hash can appear AS A value inside another `.bb` program. Programs can verify each other. *(RUST-CHAIN.md)*
- **Self-cleaning:** Replay any `.bb` with its seed; if resulting crystal hash matches claimed one, program is genuine; if not, state is corrupt or program was modified. *(RUST-CHAIN.md)*
- **Cookie `mspc_visitor_crystal` holds the visitor's chain hash (cache key).** Returning visitor = cache hit, instant render. Cold visit = chain extends, browser cooks new juice. *(CONSOLIDATION.md)*
- **Cookie crystal collision prevented by using BLAKE3 over `(visitor_ip, ua_class, path, chain_hash)`.** *(CONSOLIDATION.md)*
- **MultiModalHex:** Same 32 bytes, multiple lenses: RGB color (bytes 0..3), Distance in meters (bytes 3..7), Audio frequency in Hz (bytes 7..11), Audio amplitude (bytes 11..15), Text label (bytes 16..32), Short hex (bytes 0..8). *(NOTES-ON-3d-INFERANCE.md)*

---

## 4. Governance & Orchestration

### Agent Lifecycle
- **Agent lifecycle tracking:** Every invocation gets a UUID, claims an agent row at start, releases on exit. *(README.md · ARCHITECTURE.md)*
- **Three concepts distinguished:** `agent_defs` (persistent definition by name), `agents` (active slot per invocation by UUID), `runs` (persistent history tagged by agent_uuid). *(TWINS-MASTER.md)*
- **A single `agent_def` can be invoked by many concurrent `agents` rows** — each with a unique UUID — and each invocation produces its own history rows. *(TWINS-MASTER.md)*
- **Agents table uses claim/release semantics:** INSERT at start, DELETE at exit via EXIT trap. Stale slots auto-pruned by TTL. *(TWINS-MASTER.md)*
- **If `cc` is killed with `-9`, the agents row is left as an orphan;** `cc -agents` shows it as stale by checking if PID is alive. *(TWINS-MASTER.md)*
- **Session ownership is explicit:** One agent (or human) holds the session token. Unauthorized agents do NOT modify another's active block. *(ToDo-JobBoard.md)*
- **The Master runs on the highest-capability model and validates outputs before the `GO` gate opens for the next agent.** *(ToDo-JobBoard.md)*
- **Session Handoff Protocol:** Current owner appends `handoff`, new owner appends `claim`, previous owner retains veto rights for 5 minutes until claim is confirmed. *(ToDo-JobBoard.md)*

### Deterministic Agent Contract
- **Every agent reading the board MUST PLAN before executing,** set Checkpoints, chain completed tasks to feed the next agent, make session ownership explicit, have the Master audit workers, use multi-model dispatch as default for synthesis, keep file-type workflows contamination-safe, emit SVG+XML metadata for every DAG, treat JSONL as single source of truth, treat scope as canon, trigger SWAP ACTIVATION on role change, and keep role state verifiable. *(ToDo-JobBoard.md)*
- **No prompt runs without a `/PLAN` entry in the board.** *(ToDo-JobBoard.md)*
- **Every plan has `Checkpoint -> Steps -> Substeps`.** A Checkpoint cannot be marked complete until ALL substeps have a verified path to the next Checkpoint. *(ToDo-JobBoard.md)*
- **The output of Step N is the preamble of Step N+1.** No agent starts cold. *(ToDo-JobBoard.md)*
- **SWAP ACTIVATION triggers role switch:** When the `Next Agent` column changes, the current agent MUST run the role-switch script before proceeding. *(ToDo-JobBoard.md)*
- **Role state is verifiable via `/tmp/cc-agent-role.state`;** agents MUST verify this matches their assigned role before executing scoped operations. *(ToDo-JobBoard.md)*
- **Loop Rule:** Every loop iteration appends a row to `ToDo-JobBoard.jsonl` with `loop_id`, `iteration`, `status`, and `hash_of_prior_state`. Loops are auditable and recoverable. *(ToDo-JobBoard.md)*

### Gate Rules
- **`GO`** = next agent may fire immediately; **`HOLD`** = next agent MUST NOT fire until Master sets `GO`; **`PENDING`** = waiting on upstream; **`ACTIVE`** = in progress. *(ToDo-JobBoard.md)*
- **Browser Pool Gate states:** `IDLE` (ready), `INFER` (active), `SYNC` (syncing), `ERROR` (coherence check failed, HOLD triggered). *(ToDo-JobBoard.md)*

### Governance Rules (R-001 to R-012)
- **R-001:** No agent modifies another agent's active block without explicit handoff in JSONL. Violation = revert + audit log + offending agent barred from next 3 tasks. *(ToDo-JobBoard.md)*
- **R-002:** No file-type operation crosses project boundary without a Bridge DAG. Operation rejected by `dag_builder.py`. *(ToDo-JobBoard.md)*
- **R-003:** No plan checkpoint is marked complete unless all substeps have verified paths to the next checkpoint. *(ToDo-JobBoard.md)*
- **R-004:** No SVG is emitted without `<dag:metadata>` block containing `blake3` hash, owner, timestamp. Untrusted SVGs are refused by the runtime. *(ToDo-JobBoard.md)*
- **R-005:** No model dispatch exceeds 5 concurrent calls. Queue manager enforces this; excess calls held in `cc -dag-build` queue until slot opens. *(ToDo-JobBoard.md)*
- **R-006:** Cloud models (`:cloud` suffix) are ONLY used for synthesis/audit. Local models handle execution/classification. Cloud calls logged with token estimate. *(ToDo-JobBoard.md)*
- **R-007:** JSONL is append-only. Rows are NEVER deleted. Status changes are new rows. Any deletion attempt is caught by hash chain mismatch. *(ToDo-JobBoard.md)*
- **R-008:** The Master agent MUST check the work of smaller agents before opening the `GO` gate. If `GO` issued without verification, Master loses session token for 1 hour. *(ToDo-JobBoard.md)*
- **R-009:** MySpace++ and `gently/` are co-owners of `MASTER-SVG.md`. Neither project can unilaterally redefine shared nodes. Disputes resolved by ensemble consensus (3-of-5 models agree). *(ToDo-JobBoard.md)*
- **R-010:** Every new file type MUST complete the onboarding protocol before any agent operates on it. Unregistered file types are quarantined in `media/unscanned/`. *(ToDo-JobBoard.md)*
- **R-011:** All multi-node workflows MUST produce a UI/UX SVG explanation. Workflow is incomplete without it and cannot advance to next checkpoint. *(ToDo-JobBoard.md)*
- **R-012:** Scope is canon. Work outside the two project roots requires bridge DAG + explicit approval. Out-of-scope work is silently dropped by the runtime. *(ToDo-JobBoard.md)*

### Contamination Boundaries
- **Five contamination boundaries:** (1) File-Type Quarantine, (2) Bridge DAG Enforcement, (3) Agent Session Scope via `CC_SCOPE_LOCAL_ROOT`, (4) SVG Metadata Scope matching agent cwd, (5) Model Project Affinity. *(ToDo-JobBoard.md)*
- **File-type workflows are contamination-safe:** Operations on `.rs` files NEVER touch `.py` files unless a bridge DAG explicitly maps the conversion. *(ToDo-JobBoard.md)*
- **New File Type Onboarding Protocol:** DAG-scanner detects → Master assigns → Ensemble produces operations/bridge/layer/table → Master validates → append registry → SVG-emitter produces node → JSONL gets `type-registered` event. *(ToDo-JobBoard.md)*
- **Contamination Rule:** Operations registered for one file type can only touch another file type if an explicit Bridge DAG exists between them. *(ToDo-JobBoard.md)*

---

## 5. Data & Persistence

### Two-DB Scope Model
- **Global `~/.cc/cc.db`** (one per user, 28 tables, cross-project, cross-device) + **Local `<project>/.cc/local.db`** (one per project, chain runs + session state). Walk-up resolution from `cwd` finds the right scope automatically. *(README.md · ARCHITECTURE.md · TWINS-MASTER.md)*
- **Global is the user's memory; local is the project's memory.** They share schema patterns but never the same row. *(TWINS-MASTER.md)*
- **Discovery order for local DB:** 1) `$CC_LOCAL_DB` env override, 2) `$CC_SCOPE_LOCAL_DB`, 3) walk-up from cwd, 4) None → "(unscoped)". *(TWINS-MASTER.md)*
- **WAL mode + `busy_timeout=30000ms`:** Writers don't block readers; conflicting writers retry. *(TWINS-MASTER.md)*
- **`PRAGMA foreign_keys = ON`:** Stale `agent_uuid` refs fail loudly, not silently. *(TWINS-MASTER.md)*
- **Every row in every table can answer "which agent_uuid wrote this and when?"** *(TWINS-MASTER.md)*
- **Tom is the only writer of `cc.db`.** Droplet hosts services but holds no truth. *(TWINS-MASTER.md)*
- **Friends never touch `cc.db`;** their access stops at SSH tunnel + auth gate + salted token + Lucid embed. *(TWINS-MASTER.md)*

### Append-Only & Immutable
- **JSONL is append-only.** Rows are NEVER deleted. Status changes are new rows. *(ToDo-JobBoard.md)*
- **JSONL hash chain:** Each row's `hash` field = `blake3(prev_hash + json_string_of_this_row_without_hash_field)`. This makes JSONL tamper-evident. *(ToDo-JobBoard.md)*
- **Append-Only Audit Trail:** Never delete lines; add new entries at the bottom. *(ToDo-JobBoard.md)*
- **NOTES-FOR-INFERANCE.md is append-only at the section level.** Do not delete things. *(CLAUDE.md)*
- **Cadence log entries must be append-only with most recent at top.** *(NOTES-FOR-INFERANCE.md)*
- **`current_task` is a singleton row, upserted only — atomic by definition.** *(TWINS-MASTER.md)*

### Schema & Taxonomy
- **Opcode taxonomy at `planning/hf_task_evolution.jsonl`** is shared canonical data; if either side adds a new opcode it goes there. Dedup gate enforces uniqueness. *(CLAUDE.md · RUST-CHAIN.md · NOTES-FOR-INFERANCE.md)*
- **Both sides read the same canonical `hf_task_evolution.jsonl`;** add new opcodes only by appending. *(RUST-CHAIN.md)*
- **Schema sharing recommendation:** Cross-link via meta keys (fully separate DBs, explicit bridge). *(OPEN_QUESTIONS.md)*

### VM Filetree
- **VM Filetree:** `~/.vmfs/` is the single root for all virtual filesystems. No subdirectories, no nesting. *(VM-FILETREE.md)*
- **No VMs inside VMs.** All VMs live at the same level under `~/.vmfs/`. *(VM-FILETREE.md)*
- **All VMs contain only symlinks to `_local_assets/`.** *(VM-FILETREE.md)*
- **VMs import each other via `imports/` symlinks,** creating a navigable graph. *(VM-FILETREE.md)*
- **Graph walking ensures:** all VMs discoverable from any starting point, import cycles detectable, no VMs hidden inside other VMs. *(VM-FILETREE.md)*
- **Cross-VM references use `imports/` directory with symlinks to other VMs by `vm_<id>` name.** *(VM-CONSOLIDATION.md)*
- **Only one real file root:** `~/.vmfs/_local_assets/` — everything else is symlinks. *(VM-CONSOLIDATION.md)*
- **VMs never nest.** All VMs at `~/.vmfs/` root level; imports via `imports/`. *(VM-CONSOLIDATION.md)*
- **Content-addressed:** Canonical names include git tree + timestamp. *(VM-CONSOLIDATION.md)*
- **Deterministic ID:** `vm_id = sha256(cwd | agent_uuid)` — same scope → same VM. *(VM-CONSOLIDATION.md)*
- **Canonical naming:** `symbol{array}.project.folder.file.git.branch.txt` *(VM-CONSOLIDATION.md · DEFOLD-INTEGRATION.md)*
- **cc derives VM ID from scope using `sha256(CC_SCOPE_CWD|CC_AGENT_UUID)`.** *(VM-FILETREE.md)*

---

## 6. Security & Auth

### Authentication
- **Friend-scoped access model:** SSH port-forward on the network layer plus per-user IP-binding gate on the app layer. *(README.md)*
- **Default whitelist uses the same password (`"passwd"`) for all named friends;** the strong authentication factor is SSH key plus sticky IP binding, not the password. *(README.md)*
- **Salted-token registry at `studio/auth/keys.sqlite` (mode 600)** is per-host; friends' tokens are valid on the issuing host only. *(CLAUDE.md)*
- **Phishing surface = nil** (magic-link salted keys). *(CONSOLIDATION.md)*
- **The `chromium-authority` cookie is the shared session token** that authenticates both loops. *(README.md · NOTES-FOR-INFERANCE.md)*
- **Claude guest-pass proxy at `MySpace++/studio/proxy/claude_proxy.py` (port 8520)** is the ONLY route to Anthropic from either half. *(NOTES-FOR-INFERANCE.md)*

### Privacy
- **Visitor probe never stores raw IP — only `ip_as_class` (CIDR /24 hash).** *(CONSOLIDATION.md)*
- **Open-window commit:** While an agent is running, the session is an "open window" — SVG-active, no hashing. When unplugged: deltas clipped, forward+mirror loop runs, ONE chain extension committed. Streaming privacy + k-anonymity per session. *(RUST-CHAIN.md)*

### Headline Guarantees (TWINS-MASTER.md)
- No two sessions can corrupt each other's work.
- No two devices can claim to be the source of truth.
- No two friends can use the same IP-bound token from different networks.
- No two terminals can pin `current_task` to conflicting values without the later one winning atomically.
- If any guarantee breaks, it's a bug in the substrate, not a feature.

---

## 7. Cross-Half Coordination (MSPC ↔ GENTLY)

### Communication Protocol
- **The ONLY path for coordinating between the two halves is `studio/docs/NOTES-FOR-INFERANCE.md`.** No other messaging channel may be used. *(CLAUDE.md · README.md)*
- **Open every session by reading `NOTES-FOR-INFERANCE.md`;** finish by updating it. Mark completed items `[x]` and append `Updated by: <half> at <iso-ts>`. *(CLAUDE.md)*
- **Questions for the other side must use unique IDs** (`Q-MSPC-001`, `Q-GENTLY-001`). *(CLAUDE.md)*
- **Communication protocol for updating NOTES-FOR-INFERANCE.md:** (1) READ the whole file, (2) CLAIM the lock in §10 (30 min TTL), (3) EDIT inside YOUR scope, (4) STAMP in §11 (cadence log), (5) RELEASE the lock. *(README.md)*
- **If you see a stale lock (>30 min old) you may break it — but log it in §11.** *(NOTES-FOR-INFERANCE.md)*
- **One session edits at a time.** Use the `# LOCK` line in §10 to claim. Lock TTL = 30 min. *(NOTES-FOR-INFERANCE.md)*
- **The file is append-mostly.** You may rewrite within a section you own, but never delete another half's content. *(NOTES-FOR-INFERANCE.md)*

### Shared Infrastructure
- **`.env` is mirrored** between `/data/Projects/MySpace++/.env` and `/data/Projects/gently/.env`. Never committed. *(CLAUDE.md · NOTES-FOR-INFERANCE.md)*
- **Salted-token registry at `MySpace++/studio/auth/keys.sqlite`** is the shared issuer for any token presented by a friend or by gently calling out. *(NOTES-FOR-INFERANCE.md)*
- **WEAVE topology (`MySpace++/studio/cache/dag/weave.sqlite`)** is the joint device registry. Gently registers Rust workers as `kind='bot'`; MySpace++ registers browser-tab workers as `kind='browser-tab'`. *(NOTES-FOR-INFERANCE.md)*
- **When MSPC submits a cross-half `.bb`,** it MUST include the `asset_sha` as a `StackVal::Hash` on the program's starting stack. *(NOTES-FOR-INFERANCE.md)*
- **Joint `correlation_id = sha256(cc_uuid || gn_uuid)`** (or blake3) with `correlation_id TEXT` column in both agents tables. *(NOTES-FOR-INFERANCE.md)*
- **PRIME DIRECTIVE compliance is bidirectional** — "use what is built" includes MSPC's working Python infra. Don't reimplement working code in Rust just for uniformity. *(NOTES-FOR-INFERANCE.md)*

### Data Conventions
- **Crystal hash computed by gently is the canonical content address** for any chain extension. MySpace++ may mirror it into `pieces_index` but never originates a new crystal hash. *(NOTES-FOR-INFERANCE.md)*
- **Content-addressing convention:** When an opcode runs and produces a binary artifact, gently emits the crystal hash; MySpace++'s `pieces_index.asset_sha` equals that hash's first 16 hex chars. *(NOTES-FOR-INFERANCE.md)*
- **Agent UUIDs are per-half.** MySpace++ uses kernel-uuid → `CC_AGENT_UUID`. Gently uses its own scheme. Cross-half work gets a JOINT id. *(NOTES-FOR-INFERANCE.md)*
- **Shared topology view:** One shared WEAVE SQLite where gently writes `kind='bot'` and MySpace++ writes `kind='browser-tab'`. *(RUST-CHAIN.md)*
- **The two predictor systems** (MySpace++ TABPFN_ROUTER and gently `codie-v4-predict`) should share training data via a JSONL export format both sides can read. *(RUST-CHAIN.md)*

### Bridge Interfaces
- **11 Phase B Bridges** connecting MSPC and GENTLY (e.g., Opcode→OpKind translation table, `pieces_index.asset_sha` <-> crystal hash, WEAVE topology joint schema). *(README.md)*
- **Cross-boundary interfaces** (19 total) tracked in COMPLEX-DAG.svg with direction and status labels. *(NOTES-FOR-INFERANCE.md)*
- **MySpace++ exposes its routing decisions as an MCP tool;** gently exposes `telos-ml-tools` reachable from cc dispatch. *(RUST-CHAIN.md)*

---

## 8. Filesystem & Naming

### Unified Asset Root
- **`studio/assets/` is THE ONE REAL FILE ROOT.** Everything else is symlinks. *(studio/assets/README.md)*
- **The filename is the variable; the holder is constant.** *(studio/assets/README.md)*
- **DIRECTORY = CONSTANT HOLDER (never changes). FILENAME = VARIABLE (encodes all state).** *(studio/assets/README.md)*
- **State transitions by moving files:** `pending → running → completed (or failed)`. No UPDATE statements. No state mutations. Just `mv` and `cp`. *(studio/assets/README.md)*

### Canonical Naming
- **Canonical naming convention:** `{symbol}{array}.{domain}.{category}.{name}.{state}.{version}.{ext}` *(studio/assets/README.md)*
- **Examples:** `vm_mspc_001.compute.gpu_profiles.rtx3090ti.24gb.v0.json` *(studio/assets/README.md)*
- **Querying without a database:** `find _compute/jobs/ -name "*.pending.json"` — the filename IS the database. *(studio/assets/README.md)*

### Godot / Engine Projects
- **Godot project structure:** `studio/godot/project/` with `project.godot`, `src/`, `cpp/`, `scenes/`, `assets/` → `../../assets/projects/default`. *(studio/assets/README.md)*
- **Defold walkthrough:** `studio/defold/walkthrough/` with `game.project`, `scripts/`, `assets/` → `../../assets/projects/default`. *(studio/assets/README.md)*

### VM Card & Metadata
- **VM card format:** `VM_ID`, `CASE`, `ROLE`, `CRYSTAL`, `SCOPE`, `CREATED_AT`, `CHAIN_RUN_ID`, `AGENT_UUID`. *(VM-CONSOLIDATION.md)*
- **Asset files in `files/` use canonical metadata card + convenience symlink `current` + back-link to real file.** *(VM-FILETREE.md)*

---

## 9. Inference & Model Dispatch

### Deterministic Dispatch
- **DONE-sentinel completion protocol:** Every model call gets an "end with DONE" directive appended. Responses returned as `(text, rc)` where `rc=0` = completed, `rc=1` = transport failure, `rc=2` = partial (truncation detected). *(README.md · ARCHITECTURE.md)*
- **Adapter contract:** `model_call(model, prompt, options, cache_dir, timeout) -> tuple[str, int]`. *(ARCHITECTURE.md)*
- **Escalation chain:** rc=2 retry once then escalate; rc=1 escalate immediately; configured per-project. *(ARCHITECTURE.md)*

### Multi-Model Dispatch
- **Multi-model dispatch is the default for synthesis tasks:** The Master dispatches to up to 5 models simultaneously via `cc -ensemble`. Responses are tagged, deduplicated, and merged into the best composite. *(ToDo-JobBoard.md)*
- **R-005:** No model dispatch exceeds 5 concurrent calls. Queue manager enforces this. *(ToDo-JobBoard.md)*
- **R-006:** Cloud models (`:cloud` suffix) are ONLY used for synthesis/audit. Local models handle execution/classification. Cloud calls logged with token estimate. *(ToDo-JobBoard.md)*
- **The LLM is still better when the user's request is a NOVEL composition;** keep both: TabPFN routes by default, escalates to Claude/Codex when top-1 probability below threshold. *(TABPFN_ROUTER.md)*
- **User overrides during REPL (`swap` / `insert` / `remove`) generate negative examples.** *(TABPFN_ROUTER.md)*

### Routing & Prediction
- **7-step inference loop:** CHECK → PLAN → ROUTE → RUN → RECORD → WALK → SYNC. *(NOTES-FOR-INFERANCE.md · WEAVE.md)*
- **Four questions every inference call must answer:** Q1 (already done?), Q2 (which passes apply?), Q3 (what subsystem owns this pass?), Q4 (import time or lazily?). *(NOTES-FOR-INFERANCE.md)*
- **Three predictors:** P1 Next-opcode router, P2 GUI-element predictor, P3 Concrete-model resolver. *(TABPFN_ROUTER.md)*
- **TabPFN comparison vs LLM router:** 50-150ms vs 200-1500ms, $0 vs $0.0001-0.01, byte-identical determinism, free training by adding rows. *(TABPFN_ROUTER.md)*
- **Visitor probe + budget routing:** Same chain serves anonymous / user / admin differently, automatically. `gently-probe::classify` → `ActivationHex` (12-bit mask); `gently-inference-budget::route` → `QualityTarget` (Draft/Standard/Cinematic/Realtime). *(CONSOLIDATION.md)*
- **Mitigation: Layer rotation starvation addressed by `gently-inference-budget` tracking per-subsystem call count with round-robin + budget weights.** *(CONSOLIDATION.md)*

### Passes & Pipelines
- **20 registered passes and 27 recognized file extensions.** *(PASSES_DAG.md)*
- **Per-filetype plan split into Import-time (heavy stuff that runs once) and Lazy (on render).** *(PASSES_DAG.md)*
- **Cost classes:** LIGHT, MEDIUM, HEAVY. *(PASSES_DAG.md)*
- **Stage classes:** import, lazy. *(PASSES_DAG.md)*
- **6-step inference loop refinement:** CHECK → PLAN → ROUTE → RUN → RECORD → WALK → SYNC (Step 3 ROUTE is new). *(WEAVE.md)*
- **Intent words use 6-char prefix matcher** (e.g., `translate` matches `translation` via "transl"). *(PIPELINES.md)*
- **"A clean fix: add `Audio-Image-to-Video` as a Layer-3 compound opcode"** covering the Wav2Lip/MuseTalk/SadTalker / Image-Text+Audio-to-Video model family. *(PIPELINES.md)*

### Classification
- **NO mosquito classifier model.** Agents already classify. Chain truth (forward + mirror) + structural index = deterministic ground truth. Rule-out beats speculate. *(ToDo-JobBoard.md)*
- **Chain-traced disambiguation:** Test with 50 ambiguous inputs; reject speculation in favor of structural rule-out. *(ToDo-JobBoard.md)*
- **Dedup gate must be live on every claim** — reject duplicate insertions. *(ToDo-JobBoard.md)*

---

## 10. Frontend & UX

### Stack
- **Flat HTML + HTMX only.** No JS framework. No build step. Mobile-first always. *(CLAUDE.md · CONSOLIDATION.md)*
- **Suggested stack:** Shell=Electron or Tauri (Tauri preferred); Frontend=React+react-flow+zustand+Tailwind; Backend=Python FastAPI subprocess workers; IPC=Unix socket JSON-RPC. *(DAG-GUI.md)*
- **webgpu_worker.html is 8 KB of vanilla JS with no build step.** *(WEAVE.md)*

### GUI Principles
- **Global UX principle — "Modality drives layout."** *(DAG.md)*
- **Global UX principle — "One Run button, one progress indicator."** *(DAG.md)*
- **Global UX principle — "HITL is a checkpoint, not a permanent prompt."** *(DAG.md)*
- **Global UX principle — "Outputs are first-class artifacts."** *(DAG.md)*
- **Global UX principle — "Failure modes drive error UX."** *(DAG.md)*
- **Global UX principle — "Param widgets vs modality widgets are different layers."** *(DAG.md)*
- **Global UX principle — "Chain steps look the same as single steps."** *(DAG.md)*
- **The studio is friend-installable end-to-end:** clone, run `./install.sh`, open the printed URL. *(README.md)*

### SVG / HTMX Rendering
- **M4 — Stacked SVG renderer:** One HTML page, all surfaces inside. No client-side routing; URL bar drives `hx-push-url`. *(CONSOLIDATION.md)*
- **Server filters out `<g>` groups the visitor's scope cannot reach BEFORE response.** *(CONSOLIDATION.md)*
- **SVG inline + browser cache + cookie-keyed responses = sub-second first paint.** *(CONSOLIDATION.md)*
- **Lazy-loading `<g>` fragments via `hx-get`;** only above-fold groups inline. *(CONSOLIDATION.md)*
- **Performance:** SVG inline + browser cache + cookie-keyed responses = sub-second first paint. *(CONSOLIDATION.md)*

### Browser Pool
- **Browser Pool: 8 HTMX/SVG instances.** Each browser is a layer targeting specific passes and ignoring others. *(ToDo-JobBoard.md)*
- **Accent Rule:** A browser NEVER reads another worker's layer directly. All inter-browser data flows through browser-5 (composite) or browser-2 (sched). *(ToDo-JobBoard.md)*
- **If browser-5 (composite) detects missing input,** it HOLDs and signals browser-3 (job board), which writes the HOLD to JSONL, and the runtime loop audits on next tick. *(ToDo-JobBoard.md)*

---

## 11. Visualization & DAG

### Tesseract & SVG
- **Tesseract layers:** 0 Instructions, 1 Systems, 2 DAG of DAGs, 3 Nodes, 4 Project types, 5 Plan. *(TESSERACT.md)*
- **SVG contains a machine-readable manifest in `<metadata>`** — every node's `id`, `kind`, `source_dag`, `walk-state`, `walk-by`, `walk-at`, `walk-neighbors`, `walk-subjects`. *(TESSERACT.md · LUCID_INTEGRATION.md)*
- **Agent walker contract:** To advance through one node, an agent must satisfy three requirements — identify the node, identify every adjacent node, map the subject matter. Only when all three walker fields are populated may the walker set `walk-state="processed"`. *(TESSERACT.md · NOTES-FOR-INFERANCE.md · LUCID_INTEGRATION.md)*
- **Status colors:** green = implemented, yellow = partial, orange = stub, gray = placeholder. *(TESSERACT.md · NOTES-FOR-INFERANCE.md · TWINS-MASTER.md)*
- **Visual `<circle>` elements get their `fill` attribute synced** so a browser shows progress visually. *(TESSERACT.md)*
- **Walk state is NOT preserved across rebuilds.** To preserve, capture processed-set before rebuild, then re-identify after. *(TESSERACT.md)*
- **`cc -tesseract-build` is idempotent.** *(TESSERACT.md)*
- **R-004:** No SVG is emitted without `<dag:metadata>` block containing `blake3` hash, owner, timestamp. *(ToDo-JobBoard.md)*
- **R-011:** All multi-node workflows MUST produce a UI/UX SVG explanation. *(ToDo-JobBoard.md)*
- **UI/UX Layer Requirements:** Nodes as geometric shapes (circle=input, square=process, diamond=decision, hexagon=output), labeled edges, vertical bands per project, active highlight (pulse=solid=dashed), metadata panel, legend. *(ToDo-JobBoard.md)*
- **DAG Schema validation:** `cc -dag-bootstrap` verifies every SVG against `dag-schema.xsd` before adding nodes to the cache. *(ToDo-JobBoard.md)*

### Lucid Integration
- **Lucid is a near-perfect external surface for the Tesseract.** Its document model, formula engine, custom shapes, data connectors, and Cards integration line up 1-to-1 with existing abstractions. *(LUCID_INTEGRATION.md)*
- **Standard Import converter shipped under `studio/lucid/standard_import.py`.** Runs offline, no Lucid account required to test. *(LUCID_INTEGRATION.md)*
- **Reference keys are the unfuckability primitive.** Each chain step gets a primary key = the chain hash. Lucid maps shape → record by reference key. Even if a user moves, resizes, copies, or pastes the shape, the record link survives. *(LUCID_INTEGRATION.md)*
- **Relational formulas are DAG traversal primitives:** `CONNECTED(THIS)`, `PAGENAME()`, `UPSTREAM(THIS)`, `DOWNSTREAM(THIS)`, `ANCESTORS`, `DESCENDANTS`, `CHILDREN`, `PARENT`, `SIBLINGS`, `CONTAINED`, `CONTAINER`. They evaluate live as the doc changes. *(LUCID_INTEGRATION.md)*
- **Walker contract fields:** `data-walk-id`, `data-walk-neighbors`, `data-walk-subjects`, `data-walk-state`. Three of four required fields populate automatically from Lucid formulas. The walker only has to verify the user/agent set the state. *(LUCID_INTEGRATION.md)*
- **Four-layer integration plan:** Layer 1 Schema mirror (Standard Import), Layer 2 Data connector (hashed-chain bridge), Layer 3 Custom shape library, Layer 4 Editor extension (in-Lucid panel). *(LUCID_INTEGRATION.md)*

---

## 12. Compute & Infrastructure

### WEAVE Cross-Device Compute
- **Friends open a URL. Their browser tab probes WebGPU. They become a worker on Tom's compute network.** No installs, no SSH keys, no Lucid account, no Docker. *(WEAVE.md)*
- **Device kinds:** `owner` (Tom's primary), `droplet` (always-on relay), `browser-tab` (Chromium 113+), `friend` (wardrobe app), `bot` (headless agent). *(WEAVE.md)*
- **`browser-tab` is the magic kind.** Anyone can become one by clicking a link. *(WEAVE.md)*
- **Three concrete tables:** `devices`, `webgpu_adapters`, `plans`, `plan_evaluations`. *(WEAVE.md)*
- **PLANS are JSON dicts with condition + action + priority,** evaluated against live topology + pass spec. *(WEAVE.md)*
- **First fired plan wins.** *(WEAVE.md)*
- **Seed plans use priority ASCending** (lower number = higher priority). *(WEAVE.md)*
- **WebSocket relay runs on port 8540** (configurable). *(WEAVE.md)*
- **Three new TWINS-MASTER.svg layers** render WEAVE state: L8 weave-topology, L9 weave-plans, L10 weave-queue. *(WEAVE.md)*
- **Capability-aware routing planned:** plans say `{require_feature: "shader-f16"}` and router only picks devices that have it. *(WEAVE.md)*
- **Cost-aware routing planned:** use `passes/timing.sqlite` medians to predict job duration and schedule accordingly. *(WEAVE.md)*

### Execution Topology
- **Execution sites:** `localhost:8081` (HTMX/MSPC), `localhost:7445` (MCP/GENTLY), Chrom browser tab (both/WebGPU), z21 GPU 1 (both/CUDA), droplet (GENTLY/Rust remote). *(README.md · NOTES-FOR-INFERANCE.md)*
- **GPU profile:** z21 has dual RTX 3090 Ti (24 GB each). GPU 1 preferred for inference: `export CUDA_VISIBLE_DEVICES=1`. *(CLAUDE.md)*
- **Port map:** 443 Caddy TLS (droplet), 3100 watchdog-mcp (droplet), 7392 gently-scope-explorer (local), 7681 claude-terminal PTY (local), 7778 companion-server (local), 7779 ClaudeCompanion Electron (local), 7780 embed-server (local), 8080 trollz-api Axum (droplet), 8090 zero2onez cross-post (local), 8091 zero2onez MCP host (local). *(CLAUDE.md)*
- **WireGuard:** z21 ↔ DO droplet `159.89.181.146`. *(CLAUDE.md)*

### Rust Runtime
- **Runtime Loop (`gently-runtime`):** Every 5000ms (configurable via `GENTLY_TICK_MS`), read board, parse tasks, effect every file listed, validate chain coherence, write state back to SVGs and JSONL, notify browser pool via HTMX trigger, sleep. *(ToDo-JobBoard.md)*
- **Y-Combinator Feedback:** Runtime output → board input → runtime next tick. Self-reference via `SealedChain.crystal`. Self-clean triggers: genesis mismatch, mirror drift, orphan nodes. *(ToDo-JobBoard.md)*
- **The 10-step `.bb` agent turn round-trip:** Agent wants model X → `OpKind::AgentPrompt` → `.bb` step → `bb-loop` records step → `crystal_n` XOR → MCP receives `.bb` → `codie-v4-predict` looks up model → model invoked → `OpKind::VerifyHash` → append → `crystal_{n+1}`. *(RUST-CHAIN.md)*
- **Open-window commit:** While an agent is running, the session is an "open window" — SVG-active, no hashing. When unplugged: deltas clipped, forward+mirror loop runs, ONE chain extension committed. *(RUST-CHAIN.md)*

### 3D / Spatial Inference (Run #20)
- **Run #20 Spatial-Hardened Self-Validating Inference Loop:** 8 phases (A-H) to pull 7 spatial signals into `.bb` fragments with mirror-pass validation. *(NOTES-ON-3d-INFERANCE.md)*
- **PhysicsContext and SpatialContext structs** for Rust `Predict` trait extension. *(NOTES-ON-3d-INFERANCE.md)*
- **Cross-validation matrix with tolerances:** acoustic_depth ↔ visual_depth ±15cm indoor, skeletal_coords ↔ MediaPipe_pose per-joint Euclidean < 5cm, etc. *(NOTES-ON-3d-INFERANCE.md)*
- **Ground-truth oracle:** 30 `.mov` skinned videos + 10 `Skeleton_Rigged_*.mp4` rig-only videos on black background. *(NOTES-ON-3d-INFERANCE.md)*
- **Two execution modes:** GENERATIVE MODE (FBX → video output, PURE RUST, 10ms/frame, no GPU) and ANALYSIS MODE (unknown video → spatial signals, ~150ms/frame, GPU concurrent). *(NOTES-ON-3d-INFERANCE.md)*
- **204 distinct fingerprints** — every spatial probe binds uniquely at every TinyTransformer layer. Zero collisions. Pure Rust. Deterministic. *(NOTES-ON-3d-INFERANCE.md)*
- **"Tom's depth-ordered insight"** — depth-ordered bone masks make occlusion handling deterministic instead of learned. *(NOTES-ON-3d-INFERANCE.md)*

---

## 13. Build & Deployment

### Build Philosophy
- **"The build sequence is strictly phased. Each phase produces something that works end-to-end. Don't start phase N+1 until phase N has a passing smoke test."** *(PLAN.md)*
- **Proposed repo layout:** `core/`, `adapters/`, `frontends/`, `examples/`, `docs/`. *(PLAN.md)*
- **Build order is strictly phased:** 1) Canvas, 2) Palette+Inspector+dynamic param-form, 3) Runtime topo-sort+subprocess+cache, 4) Type-specific viewers, 5) Recipe loader, 6) Job queue UI, 7) Round-trip with DAG.md (Mermaid), 8) Sub-recipe collapse+persistence. *(DAG-GUI.md)*
- **Workflow jobs differ from todos:** Multi-step, typed, inference-driven. A single todo is freeform; a workflow_job is a fully-specified execution plan. *(TWINS-MASTER.md)*
- **Rebuild TWINS-MASTER.md whenever:** schema changes, new namespace of `cmd_X` functions, new subsystem, new device class, new studio-side SQLite cache, new lifecycle added. *(TWINS-MASTER.md)*

### Portability
- **"Bash for the substrate"** — bash is on Linux/macOS/NixOS/WSL; Windows punted to Docker. *(PORTABILITY.md)*
- **"SQLite for state"** — no daemon, no network bind, no migration tool; DB file portable across OSes. *(PORTABILITY.md)*
- **OS matrix:** NixOS first-class (`nix run .#myspace`), Linux first-class (`./install.sh`), macOS first-class (`./install.sh`), Windows container-only (`.\install.ps1` → Docker Desktop), WSL2 first-class, anywhere else container-only. *(PORTABILITY.md)*

### Deployment
- **M2 — Rust chain as web handler:** The runtime IS the HTTP server. No Flask/FastAPI mediator. Axum/Tide wrapper around `gently_runtime::run()`. *(CONSOLIDATION.md)*
- **Local-only deployment today;** droplet is production target; mobile-friendly (responsive, iPad/Pixel/Samsung). *(WEAVE.md)*
- **Security done:** salted-token registry exists. Security needed: wire token into `/worker/ws`, sign worker registration, sign job payloads with HMAC, signed model whitelist, TLS, rate limiting. *(WEAVE.md)*

---

## 14. Multi-Tenancy & SaaS

### Three-Level Hierarchy
- **L0 — PLATFORM (Zero2oneZ / MySpace++):** We run the factory. We own `_factory/templates/` and the build pipeline. We manage `_tenants/`, `_users/`, `_billing/`, `_compute/`, `_network/`. *(studio/assets/README.md)*
- **L1 — TENANTS / CLIENTS (Businesses who subscribe):** They get workspaces. They pick templates, configure them, and deploy. *(studio/assets/README.md)*
- **L2 — END USERS (Users of the software L1 builds):** Acme Corp's customers tour the 3D walkthrough. Their data lives in `_factory/clients/acme_corp/users/`. *(studio/assets/README.md)*
- **Key insight:** The same architecture recurses. `_factory/clients/acme_corp/` is a mini `studio/assets/` scoped to that tenant. *(studio/assets/README.md)*

### RBAC & Permissions
- **No permission table. No SQL JOINs. One file per grant.** *(studio/assets/README.md)*
- **Role inheritance:** Roles are JSON files in `_users/roles/`. A role lists its `inherits_from`. Resolution is done by reading the role file + all ancestors, then deduplicating permissions. No database recursion needed — it's just file reads. *(studio/assets/README.md)*
- **Quota check is a `find` + `jq` pipeline.** No counters table. No race conditions (files are append-only). *(studio/assets/README.md)*

### Factory Pipeline
- **TEMPLATE (L0 creates once)** → CONFIGURE (L1 tenant customizes) → BUILD (factory runs) → DEPLOY (factory deploys) → CLIENT WORKSPACE (L2 lives here). *(studio/assets/README.md)*
- **Every stage is a file move:** `template.v0.json` → `build.run_99.pending.json` → `build.run_99.completed.json` → `deployment.prod.active.json`. *(studio/assets/README.md)*

### Isolation Models
- **Shared:** All tenants read `_global/` directly. No copies.
- **Symlinked:** Tenant workspace symlinks into `_global/`. No copies.
- **Copied:** Build step copies assets into `_factory/clients/<tenant>/`. Full isolation. *(studio/assets/README.md)*

---

## 15. Prohibitions

### Things That Must NOT Be Done
- **Do not commit Tom's pending edits unless explicitly told.** Tom has a lot of in-flight files. *(CLAUDE.md)*
- **Never commit `.env`.** *(CLAUDE.md · NOTES-FOR-INFERANCE.md)*
- **No two sessions can corrupt each other's work.** *(TWINS-MASTER.md)*
- **No two devices can claim to be the source of truth.** *(TWINS-MASTER.md)*
- **No two friends can use the same IP-bound token from different networks.** *(TWINS-MASTER.md)*
- **No two terminals can pin `current_task` to conflicting values without the later one winning atomically.** *(TWINS-MASTER.md)*
- **No agent modifies another agent's active block without explicit handoff.** *(R-001)*
- **No file-type operation crosses project boundary without a Bridge DAG.** *(R-002)*
- **No plan checkpoint is marked complete unless all substeps verified.** *(R-003)*
- **No SVG is emitted without `<dag:metadata>` block.** *(R-004)*
- **No model dispatch exceeds 5 concurrent calls.** *(R-005)*
- **Cloud models (`:cloud`) are ONLY for synthesis/audit.** *(R-006)*
- **JSONL rows are NEVER deleted.** *(R-007)*
- **Master MUST check work before opening `GO` gate.** *(R-008)*
- **Neither project can unilaterally redefine shared nodes.** *(R-009)*
- **Every new file type MUST complete onboarding protocol.** *(R-010)*
- **All multi-node workflows MUST produce a UI/UX SVG.** *(R-011)*
- **Work outside project roots requires bridge DAG + explicit approval.** *(R-012)*
- **No prompt runs without a `/PLAN` entry.** *(ToDo-JobBoard.md)*
- **No daemon.** `cc` is a one-shot command. *(ARCHITECTURE.md)*
- **No asset generation step.** *(AVATAR_ASSETS.md)*
- **NO mosquito classifier model.** *(ToDo-JobBoard.md)*
- **No third-party JS, no external auth, no analytics beacon, no email collection, no consent gates.** *(CONSOLIDATION.md)*
- **Do NOT duplicate Lucid data in MASTER-INFERENCE.svg.** Point into existing Tesseract.svg instead. *(CONSOLIDATION.md)*
- **The daemon NEVER reshapes geometry, NEVER adds or removes nodes, NEVER mutates styles or layout, NEVER silently drops a mirror pair.** *(REFLECTION.md)*
- **This software is NOT open source.** *(LICENSE.draft.md)*
- **Prohibited:** redistribute, modify for distribution, commercial use without license, use as training data for ML models, reverse engineer for competing product. *(LICENSE.draft.md)*
- **No contributions without signed CLA** assigning copyright to Tom Lee (Zero2oneZ). *(LICENSE.draft.md)*

---

*Compiled from all project documentation. Last updated: 2026-05-28.*
*Add new principles here; never remove. The canon only grows.*
