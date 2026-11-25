# TWINS-MASTER

The multi-device, multi-session runtime view of MySpace++.

> **Companion SVG:** `studio/docs/TWINS-MASTER.svg` (84K) — same content rendered visually.
> **Sibling doc:** `studio/docs/TESSERACT.md` — static knowledge graph (DAG-of-DAGs).
> **TWINS-MASTER** = the dynamic side. Reads/writes, sessions, devices, lifecycles.

Direct. Complete. Every child file accounted for.

---

## 1 · What MySpace++ is (one paragraph)

A **deterministic-first terminal substrate** for orchestrating local and frontier AI models. One bash script (`cc`), one global SQLite database (`~/.cc/cc.db`), one optional per-project SQLite database (`.cc/local.db`), a dozen Python helpers, and a separate Streamlit studio with passes/inference/wardrobe/Pinterest/YouTube/Tesseract/Lucid subsystems. The thesis: deterministic small-model dispatch is enough for most agent tasks; frontier models (Claude, codex) belong on the escalation path, not the entry point. Multiple devices, multiple terminals, multiple friends — all sharing state through the two-DB pattern + agent UUID tagging.

---

## 2 · The TWINS (the headline)

```
GLOBAL  ~/.cc/cc.db              ONE per user
                                 28 tables · cross-project · cross-device
                                 every cc invocation writes here
                                 WAL + busy_timeout 30s + agent_uuid tagging

LOCAL   <project>/.cc/local.db   ONE per project
                                 chain runs + project-scoped session state
                                 discovered by walking up from cwd
                                 absent → cc still works (no local writes)
```

The name **TWINS** is literal: every record about who-did-what lives in one of two paired stores. Global is the *user's* memory; local is the *project's* memory. They share schema patterns (`agent_uuid` foreign-key everywhere) but never the same row.

### Discovery order (cc.cc:_resolve_local_db)

```
1. $CC_LOCAL_DB          explicit env override (test harness uses this)
2. $CC_SCOPE_LOCAL_DB    cc's own exported scope variable
3. walk-up from cwd      look for ./.cc/local.db, then ../.cc/local.db, …
4. None                  → "(unscoped)" — only global cc.db is touched
```

### Why this can't break under concurrent sessions

- **WAL mode** + **busy_timeout=30000ms**: writers don't block readers; conflicting writers retry.
- **`PRAGMA foreign_keys = ON`**: stale `agent_uuid` refs fail loudly, not silently.
- **`CC_AGENT_UUID`** generated from kernel UUID (fallback: `uuidgen`, fallback: Python `uuid4`): every cc invocation gets a unique stamp.
- **Every row** in `runs / agents / chats / chain_runs / phase_steps / swarm_run_steps / workflow_runs` carries `agent_uuid`. Two terminals doing the same command produce two rows, never overwrite.
- **`current_task`** is a singleton row, upserted only — atomic by definition.
- **`agents` table** uses claim/release semantics: a cc invocation INSERTs at start, DELETEs at exit (via EXIT trap). Stale slots auto-pruned by TTL.

---

## 3 · Multi-device topology

```
        ┌─────────────────────┐
        │  Tom's laptop       │ owner · full read/write
        │  ~/.cc/cc.db         │ every project's .cc/local.db
        │  studio/.venv        │ runs everything natively
        └───────┬─────────────┘
                │ SSH push / pull (no auto-sync; deliberate)
                ↓
        ┌─────────────────────┐         ┌──────────────────────┐
        │  Droplet (Linode)   │ ←──SSH──│  Friend's laptop      │ Jamie/Bronco/Pete/Ashley
        │  studio + proxy     │  fwd    │  Wardrobe via         │ + IP-bind via auth.gate
        │  Claude guest pass  │  8510+  │  http://localhost:8510│ + salted mspc_* token
        │  Lucid data conn    │         └──────────────────────┘
        └───────┬─────────────┘
                │ Lucid OAuth (read-only)
                ↓
        ┌─────────────────────┐
        │  Friend's phone     │ Lucid embed of Tesseract.svg / TWINS-MASTER.svg
        │  Lucid mobile       │ scope: mspc:read
        └─────────────────────┘
```

Tom is the only writer of cc.db. Droplet hosts the *services* (proxy, studio, Lucid connector) but holds no truth — those services proxy to / sync from Tom's box. Friends never touch cc.db; their access stops at the SSH tunnel + auth gate + salted token + Lucid embed.

---

## 4 · Session lifecycle (one cc invocation)

```
  bash ↓
    1. Resolve CC_INSTALL_ROOT (script dir → ~/.cc fallback)
    2. Generate CC_AGENT_UUID (kernel-uuid → uuidgen → python)
    3. Resolve CC_GLOBAL_DB ($CC_DB → $CC_GLOBAL_DB → ~/.cc/cc.db)
    4. Resolve CC_LOCAL_DB (4-step discovery above)
    5. Export CC_SCOPE_* env for child processes
    6. Claim agents row (INSERT uuid, pid, cwd, action, started)
    7. Trap EXIT → release agent row + clean tmpfiles
    8. Dispatch (case statement, ~130 cmd_X functions)
    9. cmd_X reads + writes via G() (global) or L() (local) helpers
   10. On exit → INT/TERM traps fire → consistent cleanup
```

If cc is killed `-9`, the agents row is left as an orphan; `cc -agents` shows it as "stale" by checking if PID is still alive. `cc -setup` and the smoke test prune stale slots automatically.

---

## 5 · Every child file (the exhaustive inventory)

### Repository root (12 files)

| File | Purpose |
|---|---|
| `README.md` | Project overview + quick start |
| `LICENSE` | Proprietary "fuckyou payme" license |
| `Dockerfile` | Substrate image (debian-slim + ollama) |
| `studio.Dockerfile` | Studio apps image (heavier: Streamlit + opencv + rembg + ffmpeg) |
| `docker-compose.yml` | Multi-service: substrate + ollama + studio profile |
| `install.sh` | Linux/Mac installer (detects apt/dnf/pacman/zypper/apk/brew/nix) |
| `install.ps1` | Windows installer (container-only path via Docker Desktop) |
| `flake.nix` + `flake.lock` | Nix build path (reproducible) |
| `.gitignore` + `.dockerignore` + `.gitattributes` | Standard hygiene |
| `.env` | Shared keys (claude_guest, client_api, pintrest_api, SUI_WALLET). MIRROR of `~/Projects/gently/.env`. NEVER committed. |

### core/ — the substrate

```
core/
├── cc                          2612 lines · ~130 cmd_X functions · main script
├── lib/
│   ├── db.py                   28-table sqlite schema + CLI · the global/local writer
│   ├── chain.py                cc -chain parser + executor (| + - cc{} grammar)
│   ├── studio.py               Streamlit dashboard for cc studio (legacy admin)
│   ├── tui.py                  Curses TUI (chats/agents/swarms/phases/todos)
│   ├── author_cards.py         Tiny-model 3-step chain → capability_cards rows
│   ├── author_gui.py           Hybrid heuristic + tiny-model → gui_cards rows
│   ├── author_templates.py     Claude-authored workflow_templates rows (~$0.02 each)
│   ├── dag_builder.py          Hash-addressed DAG cache builder (dag_nodes/edges/chains)
│   ├── template_walker.py      Dry-run walk a template; predict GUI; validate binds
│   ├── template_lint.py        4 lint passes (outputs / unique / flow / cycles)
│   ├── fix_template_binds.py   Repair Claude terminal-bind bug; rewrite to __PASSTHROUGH__
│   └── mui_map.py              widget kind → Material UI v5 component mapping
├── setup/
│   ├── setup.sh                Linux/Mac local bootstrap (no docker required)
│   ├── setup.ps1               Windows local bootstrap
│   └── README.md
└── tests/
    ├── smoke.sh                Phase 0 integration (drops + recreates a project)
    ├── determinism.sh          Verifies temp=0+seed=42+sha256 cache is byte-stable
    ├── dag_cache.sh            DAG cache exhaustive (schema, queue, hit tracking)
    └── chain_parser.py         Unit tests for chain.py grammar
```

### studio/ — the apps

```
studio/
├── paths.py                    Single source of truth for every directory
├── bootstrap.py                Idempotently creates the canonical tree
├── project_io.py               CRUD for studio/projects/<slug>/
├── app.py                      DAG Studio Streamlit (port 8501) — node-based canvas
├── wardrobe_studio.py          Wardrobe app (port 8510) — cutout/try-on/mockup/3D
├── yt_cutter.py                YouTube cutter (port 8511) — waveform edit + stems
├── pinterest_app.py            Pinterest search (port 8512) — auto-classify + save
├── runtime.py                  DAG executor (topo-sort + type-check + content cache)
├── nodes.py                    NODES_BY_ID — 47 model/tool/input/output specs
├── recipes.py                  C01-C25 + S01-S21 — pre-built chains
├── flows.py                    12 named flows + deck-card predictor (deterministic)
├── types_meta.py               Port-type colors + legal coercions
│
├── auth/
│   ├── gate.py                 Streamlit login gate + first-login IP bind
│   ├── keys.py                 Salted-token registry (keys.sqlite)
│   ├── seed_permissions.py     friends.jsonl seeder + idempotent
│   ├── ssh_friend_setup.sh     SSH authorized_keys helper (port-forward-only)
│   ├── test_gate.py            10 unit tests for the gate
│   └── README.md
│
├── proxy/
│   ├── claude_proxy.py         FastAPI proxy: /v1/messages → Anthropic (signed)
│   ├── test_proxy_logic.py     6 unit tests
│   └── requirements.txt        fastapi + httpx + uvicorn
│
├── passes/
│   ├── registry.py             20 declarative Pass dataclasses
│   ├── inference.py            Default callable per pass; graceful PassUnavailable
│   ├── timing.py               Per-machine duration cache (passes_timing.sqlite)
│   ├── filetype_dag.py         NEW DAG: ext → import_time vs lazy plan
│   ├── svg_layers.py           Bundle pass outputs → labeled <g> in one SVG
│   └── pieces_index.py         pieces.sqlite — searchable pre-computed pieces
│
├── tesseract/
│   ├── inventory.py            Pulls 253 nodes / 729 edges from 8 source DAGs
│   ├── svg.py                  Emits docs/Tesseract.svg
│   ├── walker.py               Agent walker contract (identify N, neighbors, subjects)
│   ├── plan.py                 tesseract_plan.sqlite — 22 seeded steps
│   ├── projects.py             SUBSYSTEMS catalog + 9 project types
│   └── twins.py                Emits docs/TWINS-MASTER.svg (this doc's SVG)
│
├── pinterest/
│   ├── __init__.py
│   └── client.py               OAuth API + scrape fallback
│
├── lucid/
│   ├── __init__.py
│   ├── standard_import.py      Tesseract inventory → Lucid Standard Import JSON
│   └── data_connector/         (scaffolding only — manifest.json + README + .ts.example)
│
├── media/
│   ├── .tools/
│   │   ├── process.py          Classify + bg-remove (rembg fallback to GrabCut)
│   │   ├── fetch-url.sh        URL/Pinterest-page → classify → bg-remove → place
│   │   ├── sidecar.py          Per-asset JSON sidecar with variants/uses/tags
│   │   ├── separate.py         Audio stem split (demucs / ffmpeg karaoke)
│   │   ├── import_pipeline.py  One asset → all import-time passes → SVG → index
│   │   └── backfill_passes.py  Loop over media/ for assets not yet processed
│   ├── Cloths/{Female,Male}/{Tops,Bottoms,Dresses,Outerwear,Footwear,Accessories,Swimwear,Underwear,Sleepwear}/
│   ├── Furniture/RoomsType/{Bedroom,LivingRoom,Kitchen,Bathroom,DiningRoom,Office,Outdoor,Hallway,Studio}/
│   ├── Models/{Females,Males,Babies}/{HeadShots,Group,Solo,Sex}/
│   ├── Media/
│   │   ├── Image/{Screenshots,}/
│   │   ├── Video/
│   │   ├── Sounds/{Vocals,Music,Noise}/
│   │   ├── Mask/
│   │   └── 3d/{assets,textures,normal_maps,rigs,mesh,ground_truth,bed,dresser,…}/
│   ├── House_Blueprints/  HEAD_TEMPLET/
│   ├── .staging/  .logs/  (runtime — gitignored)
│   └── (all content gitignored except .tools/)
│
├── projects/<slug>/            (per-project saved scenes)
│   ├── scene.json              flow graph + 3D scene
│   ├── assets/  exports/  makeup/  renders/  layers/
│
├── cache/
│   ├── dag/
│   │   ├── pieces.sqlite       passes.pieces_index
│   │   ├── passes_timing.sqlite passes.timing
│   │   └── tesseract_plan.sqlite tesseract.plan
│   └── yt/                     yt-dlp cache
│
├── logs/                       runtime logs
│
├── docs/                       (next section)
│
└── shell launchers:
    ├── run.sh                  → app.py    (DAG Studio, port 8501)
    ├── run-wardrobe.sh         → wardrobe_studio.py (port 8510)
    ├── run-pinterest.sh        → pinterest_app.py   (port 8512)
    └── run_yt_cutter.sh        → yt_cutter.py       (port 8511)
```

### studio/docs/ — every reference doc

| File | What |
|---|---|
| `TESSERACT.md` | Static knowledge graph: 8 DAGs / 253 nodes / 729 edges |
| `Tesseract.svg` | The master SVG (119K) |
| `Tesseract.lucid-si.json` | Tesseract → Lucid Standard Import (347K) |
| `TWINS-MASTER.md` | **This file** |
| `TWINS-MASTER.svg` | Dynamic runtime view (84K) |
| `NOTES-FOR-INFERANCE.md` | Pre-inference checklist + DAG↔Lucid mapping |
| `LUCID_INTEGRATION.md` | 4-layer Lucid bridge plan |
| `LAYOUT.md` | Studio directory taxonomy |
| `PASSES_DAG.md` | Auto-generated filetype → passes mapping |
| `DAG.md` · `DAG-GUI.md` · `DAG-FLOW.md` | Spec docs imported from dag_studio |
| `DOWNLOAD_INSYRUCTIONS.md` | Model seed download guide (WIP) |

### planning/ — design + generators

```
planning/
├── README.md                   Planning index
├── PLAN.md                     Phase 0-5 roadmap
├── ARCHITECTURE.md             3-layer contract (Frontend / Adapter / Substrate)
├── OPEN_QUESTIONS.md           Decisions for Tom
├── LICENSE.draft.md            Internal license draft
├── hf_task_evolution.jsonl     53 HF opcodes (the opcode DAG source)
├── hf_task_evolution.md        Human-readable opcode DAG
├── path_builder.py             Interactive REPL + rank/build walker
├── task_dag.py                 Compact DAG introspection
├── PATH_BUILDER.md             Quick reference
├── PIPELINES.md                Verdict table for canonical HF pipelines
├── dag_generator.py            Emits planning/DAG.md from registry
├── dag_cross_generator.py      Emits planning/DAG_CROSS.md
├── DAG.md · DAG_CROSS.md       Generated DAGs (master + cross-product)
├── TEMPLATES.md                107K — auto-summary of 53 templates
├── templates_summary.py        Template summarizer
├── AVATAR_ASSETS.md            N001 mesh + 210-anim Mega Pack manifest
├── TABPFN_ROUTER.md            Three TabPFN predictor design
├── WORKFLOW_LIBRARY.md         Compiled workflow examples
└── demo_pipelines.sh           Benchmark harness for path_builder.py
```

### docs/ (root)

| File | What |
|---|---|
| `PORTABILITY.md` | OS matrix: NixOS / Linux / Mac / Windows / WSL2 — first-class vs container-only |

### .github/workflows/

| File | What |
|---|---|
| `docker.yml` | Build + smoke + hadolint + compose-validate (15 min timeout) |
| `smoke.yml` | Dual-path: bare-metal Ubuntu + Nix flake (5 + 15 min) |

---

## 6 · Databases — the complete map

### cc.db tables (28) at `~/.cc/cc.db`

| Table | Writers | Readers | What it stores |
|---|---|---|---|
| `projects` | db.py | db.py, tui.py | User-wide project registry; active project tracking |
| `todos` | db.py | db.py, tui.py | Per-project task list (text, priority, status) |
| `bash_scripts` | db.py | db.py | Registered shell scripts per project |
| `directory_log` | db.py | db.py | cwd + action history (one row per cc invocation) |
| `queue` | db.py | db.py | Command queue rows (queued / running / done) |
| `current_task` | db.py | db.py, tui.py | **Singleton row** — which todo is pinned |
| `meta` | db.py | db.py | Key-value metadata (versions, last-seen flags) |
| `entrypoints` | db.py | db.py | CLI entry scripts + last-run timestamps |
| `runs` | db.py | db.py | Command exec history (stdout-tail, rc, agent_uuid) |
| `agents` | db.py | db.py, tui.py | Live agent slots (uuid, pid, cwd, action, started) |
| `tools` | db.py | db.py | Tool registry (name, schema, executor) |
| `workflows` | db.py | db.py | Workflow definitions (steps_json, use_count) |
| `workflow_runs` | db.py | db.py, tui.py | Active workflow exec state |
| `agent_defs` | db.py, author_templates.py | db.py, tui.py | Reusable agent prompt templates |
| `swarm_defs` | db.py | db.py, tui.py | Swarm loop definitions + max_iters |
| `swarm_runs` | db.py | db.py, tui.py | Active swarm exec state + iteration count |
| `swarm_run_steps` | db.py | db.py | Per-iteration step output |
| `phases` | db.py | db.py, tui.py | Conversation phase grouping |
| `phase_steps` | db.py | db.py | Phase step outputs + agent_uuid |
| `chats` | db.py | db.py, tui.py | Chat session metadata (session_id, git_branch, forked_from) |
| `chain_runs` | db.py, chain.py | db.py, chain.py | cc -chain spec execution state + agent_uuid |
| `chain_run_steps` | db.py | db.py | Chain step outputs (prompt, output, ms_elapsed) |
| `capability_cards` | author_cards.py | author_*, dag_builder.py, fix_template_binds.py | Opcode capability definitions |
| `gui_cards` | author_gui.py | author_gui.py, dag_builder.py | Per-opcode GUI widget specs |
| `workflow_templates` | author_templates.py | author_templates.py, dag_builder.py, planning files | Claude-authored multi-step templates |
| `workflow_jobs` | db.py | db.py, author_gui.py | Template instantiation + job state |
| `workflow_job_steps` | db.py | db.py | Per-step exec + HITL gates |
| `dag_nodes` | dag_builder.py | dag_builder.py, studio files | Hash-addressed DAG cache: nodes |
| `dag_edges` | dag_builder.py | dag_builder.py | Hash-addressed DAG cache: edges |
| `dag_chains` | dag_builder.py | dag_builder.py, dag_generator.py | Pre-computed chains + score |
| `dag_build_queue` | dag_builder.py | dag_builder.py | Async builder task queue |

### local.db tables at `<project>/.cc/local.db`

| Table | Purpose |
|---|---|
| `chain_runs` | (when local.db scope detected) chain executions tagged to this project |
| `chain_run_steps` | per-step output, local copy |
| `(future)` | project-scoped session state — placeholder; schema TBD |

### Studio-side DBs (also global per user, but separate files)

| Path | Tables | Writers/Readers |
|---|---|---|
| `studio/auth/keys.sqlite` | `tokens` (PK token_id, user, kind, hmac, active) + `usage_log` (per-call cost) | `studio/auth/keys.py` |
| `studio/cache/dag/pieces.sqlite` | `pieces` (asset_sha, pass_id, path, label, tags) | `studio/passes/pieces_index.py` |
| `studio/cache/dag/passes_timing.sqlite` | `timings` (pass_id, file_kind, duration_ms, machine_id) | `studio/passes/timing.py` |
| `studio/cache/dag/tesseract_plan.sqlite` | `steps` + `help_edges` | `studio/tesseract/plan.py` |

---

## 7 · cc dispatch tree — every command, every namespace

```
project state         -setup  -scope  -context  -set-project  -list-projects
agents + runs         -agents  -runs  -log  -clear-cache
todos / tasks         -plan  -todos  -done  -edit-todo  -current  -current-set
                      -current-clear  -queue  -run
model dispatch        py  tiny  bash  claude  claude-import  chats  chat-show
chain runtime         -chain  -chain-last  -chain-show  -chain-list
capability cards      -cards  -card-show  -card-delete  -author-cards
GUI cards             -gui-cards  -gui-show  -gui-delete  -author-gui-cards
workflow templates    -templates  -template-show  -template-walk  -template-delete
                      -authorize-templates
workflow jobs         -jobs  -job-show  -job-last
DAG cache             -dag-bootstrap  -dag-status  -dag-node  -dag-chain  -dag-build
                      -dag-enqueue  -dag-successors  -dag-chains-from  -dag-chains
                      -dag-invalidate
studio launchers      -studio  -dag-studio  -wardrobe  -yt-cut  studio
auth + SSH            -auth-seed  -auth-list  -auth-grant  -auth-revoke
                      -auth-status  -auth-ssh
intake / media        -intake  -fetch-url
salted keys           -keys-distribute  -keys-list  -keys-status  -keys-revoke
                      -keys-verify  -proxy-start
passes pipeline       -passes-list  -passes-dag  -passes-run  -passes-search
                      -passes-stats  -passes-timing  -passes-backfill
tesseract             -tesseract-build  -tesseract-status  -tesseract-walk
                      -tesseract-identify  -tesseract-reset  -tesseract-project
                      -tesseract-plan  -tesseract-plan-seed  -tesseract-open
orchestration         agent  swarm  tool  workflow  phase  tui
```

~130 commands total. Color coded in the SVG by scope (global / local / both / studio).

---

## 8 · ToDo lifecycle (global cc.db)

```
1. cc -plan "ship the wardrobe feature"
   → tiny model decomposes → N rows in todos (priority auto-assigned)

2. cc -todos
   → SELECT * FROM todos WHERE project = active_project AND status='open'

3. cc -current-set <id>
   → UPSERT INTO current_task — singleton row

4. ... work happens; agents read current_task to know what to do ...

5. cc -done <id>
   → UPDATE todos SET status='done' WHERE id=?; current_task cleared

6. cc -edit-todo <id> "new text"
   → UPDATE todos SET text=? — status preserved
```

Todos are **per-project** but live in global `cc.db`. The `project` column filters them. `current_task` is the active focus — used by the TUI + auto-injected into model prompts when `CC_AUTO_SCOPE=1`.

---

## 9 · workflow_jobs lifecycle (local-preferred)

```
1. cc -authorize-templates --execute      # Claude writes templates row
2. user picks template + invokes it       # → workflow_jobs row created
3. cc -template-walk <name>               # dry-run validates binds + GUI
4. each step executes inference           # → workflow_job_steps row per step
5. HITL gate?                             # human_checkpoint set → wait
6. terminal step (__PASSTHROUGH__)        # surface upstream artifact
```

Workflow jobs differ from todos: they're **multi-step**, **typed**, and **inference-driven**. A single todo is a freeform note; a single workflow_job is a fully-specified execution plan.

---

## 10 · Agents vs agent_defs (the distinction)

| Concept | Table | Lifetime | Identity |
|---|---|---|---|
| **Definition** | `agent_defs` | persistent | by `name` (e.g. "validator-claude") |
| **Active slot** | `agents` | one cc invocation | by `CC_AGENT_UUID` |
| **Run history** | `runs` | persistent | tagged by `agent_uuid` |

A single `agent_def` can be invoked by many concurrent `agents` rows — each with a unique UUID — and each invocation produces its own rows in `runs / chats / chain_runs`. Definitions are reusable prompt templates; slots are runtime claims; history is the audit log.

---

## 11 · How sessions stay isolated (concrete examples)

### Three terminals, same project

```
term-A   CC_AGENT_UUID = 31b98932-…
         claims agents.row(uuid=31b9…, pid=20001, cwd=/proj, action=studio)
         runs `cc -passes-backfill` → all writes tagged 31b9…

term-B   CC_AGENT_UUID = 7ca18131-…
         claims agents.row(uuid=7ca1…, pid=20055, cwd=/proj, action=tesseract)
         runs `cc -tesseract-walk` → all writes tagged 7ca1…

term-C   CC_AGENT_UUID = 4a8c846f-…
         claims agents.row(uuid=4a8c…, pid=20099, cwd=/proj, action=auth)
         runs `cc -auth-list` → reads only
```

All three write to the *same* `cc.db`. None collide because:
- WAL allows concurrent readers + serialized writers
- Every row tagged with its writer's UUID
- `current_task` is a singleton, last-wins, atomic
- `agents` rows live until each terminal's EXIT trap fires

### Friend on a different device

```
friend-laptop    ssh -L 8510:localhost:8510 jamie@droplet
                 → SSH-tunnel into droplet
                 → wardrobe app login (auth.gate)
                   → IP bound: jamie@<friend-ip>
                   → salted token mspc_claude_…
                 → no access to ~/.cc/cc.db
                 → all inference goes through claude_proxy → Tom's key
                 → usage logged in studio/auth/keys.sqlite
```

The friend never sees cc.db. Their session lives entirely inside the studio's per-session Streamlit state + the keys.sqlite usage log.

---

## 12 · Subsystem status snapshot

| Subsystem | Status | Code | Why |
|---|---|---|---|
| Inference system | **impl** | `studio/passes/`, `studio/nodes.py`, `studio/runtime.py` | 20 passes registered, pipeline ships |
| Search system | **impl** | `studio/passes/pieces_index.py`, `studio/pinterest/` | Pinterest + pieces_index both live |
| 3D Scene engine | partial | `studio/media/Media/3d/`, `projects/*/scene.json` | dirs + sidecars; no editor yet |
| Texture system | partial | `studio/media/Media/3d/textures/` | normal_map pass works; PBR pipeline TODO |
| Render system | partial | `studio/runtime.py`, `passes/svg_layers.py` | runtime + SVG layered output; full render TODO |
| Furniture design | stub | `studio/media/Furniture/` | dirs + buckets; no design UI |
| Makeup design system | placeholder | `studio/projects/*/makeup/` | reserved dir; no code |
| Business system | placeholder | _TODO: studio/business/_ | earmarked |
| App + website builder | placeholder | _TODO: studio/app_builder/_ | earmarked |
| Communications system | placeholder | `studio/proxy/` | proxy lives here; inbox/messaging TODO |

---

## 13 · Plan steps (live)

22 steps in `studio/cache/dag/tesseract_plan.sqlite`:

```
done (11):
  cc bash hardening + INT/TERM traps
  MySpace++ cross-OS port
  Studio merge (dag_studio → studio/)
  Auth gate + SSH friend onboarding
  Salted-key registry + Claude proxy
  Pinterest search + auto-organize
  YouTube cutter + vocal separation
  Passes registry + filetype DAG
  Passes inference shims + SVG bundle
  Pieces searchable index
  Import pipeline + backfill loop

in_progress (1):
  Tesseract Renderer scaffold

planned (10):
  Wire real DepthPro inference
  Wire real CLIP-Interrogator caption
  Wire MediaPipe Pose keypoints
  Mesh thumbnail via Blender headless
  3D scene editor MVP
  Makeup designer MVP
  Furniture designer MVP
  Business / CRM module
  App + website builder
  Comms hub (inbox / messaging)
```

`cc -tesseract-plan list` always shows current state.

---

## 14 · When TWINS-MASTER needs to regenerate

Re-run `python3 studio/tesseract/twins.py` whenever ANY of these change:

- core/lib/db.py schema (new table, new column)
- A new namespace of `cmd_X` functions in core/cc (more than 1 new command)
- A new subsystem appears in `tesseract/projects.py SUBSYSTEMS`
- A new device class is added to the share story (e.g. iOS app, web client)
- A new studio-side SQLite cache is created (studio/cache/dag/*.sqlite)
- A new lifecycle is added (e.g. swarm → swarm_runs → swarm_run_steps)

The doc is **derived** from code. Drift between this doc and code is the most expensive drift we have — fix the code first if needed, then rebuild this.

---

## 15 · Quick verification (the unfuckability check)

```bash
# 1. The TWINS file exists + global DB is sane
ls -la ~/.cc/cc.db
sqlite3 ~/.cc/cc.db ".tables" | wc -w    # → 28 (or more after future additions)

# 2. Local DB discovery works
cd /data/Projects/MySpace++
cc -scope                                  # shows project + local DB path

# 3. Agent UUID is unique per invocation
cc -agents                                 # shows all active slots

# 4. Studio caches are reachable
ls -la studio/auth/keys.sqlite \
       studio/cache/dag/pieces.sqlite \
       studio/cache/dag/passes_timing.sqlite \
       studio/cache/dag/tesseract_plan.sqlite

# 5. TWINS-MASTER itself is current
ls -la studio/docs/TWINS-MASTER.svg studio/docs/TWINS-MASTER.md

# 6. The whole picture
cc -tesseract-status     # walk state
cc -tesseract-plan list  # plan state
cc -keys-status          # token state
cc -passes-stats         # pieces state
```

If all 6 return clean — the runtime is consistent.

---

## 16 · The headline guarantee

> **No two sessions can corrupt each other's work.**
>
> No two devices can claim to be the source of truth.
>
> No two friends can use the same IP-bound token from different networks.
>
> No two terminals can pin `current_task` to conflicting values without the
> later one winning atomically.
>
> Every row in every table can answer the question "which agent_uuid
> wrote this and when?" — that's the audit trail.

If any of those guarantees ever breaks, it's a bug in the substrate, not a feature. File against `core/lib/db.py` first.

---

*Generated 2026-05-26 from a 4-agent parallel walk of /data/Projects/MySpace++/. Rebuild after schema changes: `python3 studio/tesseract/twins.py`.*
