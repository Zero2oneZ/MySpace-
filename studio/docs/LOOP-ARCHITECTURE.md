# LOOP-ARCHITECTURE.md

> **The infinite loop — four sub-DAGs closing the cycle.**
>
> Owner: Tom Lee · Engine: `core/lib/dag_loop.py` · Renderer: `core/lib/dag_render.py`
>
> Companion doc: [BUILD_THESE_INNOVATE.md](../../BUILD_THESE_INNOVATE.md) · Visual: [LOOP-FOUR-DAG.svg](LOOP-FOUR-DAG.svg)

---

## §1 — The meta-product

MySpace++ stops being "an orchestrator" and becomes "the engine that builds itself." Every external service is an input. Every product is an output. The loop drives the cycle:

```
       ┌──────────────────┐         ┌────────────────┐
       │  PLATFORMS DAG    │  ──►   │   DOCS DAG      │
       │   (blue)          │         │   (green)       │
       │  37 nodes — every │         │  57 nodes —     │
       │  external service │         │  every parsed   │
       │  that has data    │         │  doc + module   │
       └──────────────────┘         └────────────────┘
              ▲                              │
              │                              ▼
       ┌──────────────────┐         ┌────────────────┐
       │   APPS DAG        │  ◄──   │ INFERENCE DAG  │
       │   (purple)        │         │   (orange)      │
       │   6 nodes —       │         │   27 nodes —    │
       │   products that   │         │   every routing │
       │   emerge          │         │   target        │
       └──────────────────┘         └────────────────┘
```

**The cycle is closed.** Apps deploy to platforms (NFT mints, Discord bots, slug pages) → platforms emit new events → docs parse them → inference routes → new app outputs. Forever.

---

## §2 — Auto-discovery (no manual enumeration)

`dag_loop` walks the existing substrate and assigns every node to one of 4 sub-DAGs without any hand-edited registry. Discovery sources:

| Sub-DAG | Source | Count today |
|---|---|---|
| PLATFORMS | `BUILD_THESE_INNOVATE.md` §3 MCP tables + `core/lib/third_party/*.py` | 37 |
| DOCS      | `studio/docs/*.md` + `studio/assets/_doc_corpus/` + `core/lib/*.py` modules + agent_def cards | 57 |
| INFERENCE | `hf_hub.INFERENCE_PROVIDERS` (19) + task_queue pools (4) + future placeholders (4) | 27 |
| APPS      | `studio/assets/_products/*.json` + `studio/assets/_workflows/vm_mspc_001.workflows.*.json` | 6 |
| **TOTAL** | | **127 nodes · 36 edges** |

When you add a new MCP card to BUILD_THESE, or drop a new product card in `_products/`, or land a new module in `core/lib/`, the next `cc loop cycle` picks it up automatically. The DAG re-discovers itself every cycle.

---

## §3 — Anatomy of a cycle

```
LOOP_CYCLE
   ├── ts                 ISO-8601
   ├── cycle_idx          monotonically increasing
   ├── nodes_total        snapshot of universe size
   ├── edges_total        snapshot of relation count
   ├── by_sub_dag         {PLATFORMS: 37, DOCS: 57, ...}
   ├── steps[4]           one per cycle transition
   │     ├── platforms→docs    src_count, dst_count, actions_taken
   │     ├── docs→inference     ...
   │     ├── inference→apps     ...
   │     └── apps→platforms     ...
   ├── prev_crystal       BLAKE3 of previous cycle (or "")
   └── crystal            BLAKE3 over canonical_json(this_cycle)
```

Each cycle:
1. Persists to `studio/assets/_loop_cycles/cycle_<idx>_<crystal12>.jsonl`
2. Appends one `InferenceRecord(tier="loop_cycle", chain_context="four_dag_infinite_loop")` to the crystal chain
3. Cycle N+1 carries `prev_crystal = crystal_N` → tamper-evident chain of cycles

Two cycles ran today:
- Cycle 0 crystal: `c5a99399b69010af…`  (genesis)
- Cycle 1 crystal: `92f5045689958ee7…`  (prev → c5a99399b69010af…)

---

## §4 — CLI surface

```bash
python3 core/lib/dag_loop.py status      # snapshot: nodes, edges, by_sub_dag, by_status
python3 core/lib/dag_loop.py partitions   # node IDs grouped by sub-DAG
python3 core/lib/dag_loop.py inspect      # full node listing per sub-DAG with status
python3 core/lib/dag_loop.py cycle [--dry-run]  # run one cycle (crystal-anchored)
python3 core/lib/dag_loop.py cycles --limit 5    # last N cycle records
python3 core/lib/dag_render.py [--out path]      # emit color-coded SVG
```

Color map for SVG:
- **PLATFORMS** → `#5b8def` (blue) — external services
- **DOCS** → `#4caf50` (green) — structured knowledge
- **INFERENCE** → `#ff9800` (orange) — routing tree
- **APPS** → `#9c27b0` (purple) — emergent products
- **ORCHESTRATION** → `#607d8b` (slate) — runtime spine (reserved)

Node opacity tracks status: ACTIVE=1.0, IN-FLIGHT=0.7, STUB=0.5, TEXT-PLACEHOLDER=0.35.

---

## §5 — How the cycle drives itself

Today the cycle is **observational** — it counts nodes and edges, crystal-anchors the snapshot. The next phase (rolling out per [lively-enchanting-parrot](../../../../home/tom/.claude/plans/lively-enchanting-parrot.md) plan) wires in **actions**:

| Transition | Today (observational) | Phase-1 (active) |
|---|---|---|
| PLATFORMS → DOCS    | counts cross-DAG edges | for each platform: poll new events → push through `doc_parser` → emit doc nodes |
| DOCS → INFERENCE     | counts cross-DAG edges | for each new doc: feed semantic context → `router_policy.choose` picks provider |
| INFERENCE → APPS     | counts cross-DAG edges | inference output triggers `studio_runtime.run_card(<app>)` → workflow materialized |
| APPS → PLATFORMS     | counts cross-DAG edges | app surface deploys: NFT mint (tensorchain-mcp), bot post (discord-mcp), page publish (slug-pages) |

The shape stays the same. Only the action handlers fill in.

---

## §6 — Why this design wins

1. **Self-discovery.** Drop a new MCP server, new product card, new module — the next cycle picks it up. No central registry to maintain.

2. **Tamper-evident.** Every cycle crystal-anchors with `prev_crystal`. Any node count change is detectable. Replay the entire universe at any time.

3. **Closed loop.** Apps that ship feed platforms that emit events that feed docs that feed inference that ships more apps. Compound growth.

4. **Visualizable.** One SVG, four quadrants, four colors. Anyone can see the system's surface area at a glance.

5. **Free retrieval surface.** Every cycle becomes a chain record → moe_router can retrieve "what did the system look like at cycle 42" → time-travel debugging built in.

6. **Auto-CI for the substrate.** Every commit that adds a node should produce a higher node count on the next cycle. Drop in count = something broke.

---

## §7 — What's next on the loop

| Phase | What lands | Who unblocks |
|---|---|---|
| **Action handlers** (1 day each transition) | Wire each step from observational to active | router_policy.choose + studio_runtime + connectors |
| **Per-platform pollers** (1 week) | Each platform_mcp gets a `poll_events(since=last_cycle_crystal)` method | MCP wrap (#61) |
| **Per-app deployers** (1 week) | Each app card carries a `deploy(target=<platform>)` callback | product cards + workflow_generator |
| **Continuous loop** (1 day) | `python3 core/lib/dag_loop.py run --interval 60` for autonomous operation | task_queue scheduling |
| **Cycle diff visualizer** (1 day) | `cc loop diff <cycle_a> <cycle_b>` shows additions/removals | dag_render extension |

---

## §8 — Hard rules

1. **Don't bypass auto-discovery.** Never hand-edit a sub-DAG node list. Drop the file where it belongs (product card, agent_def, MCP table row) and let the cycle find it.

2. **Crystal-anchor every cycle.** Never disable the crystal write — that's the auditability story.

3. **Closed loop or null loop.** A transition with `actions_taken=0` is not failed — it's an idle tick. Idle ticks are valid. They become signals: low actions = either nothing happened OR the action handler is missing.

4. **The 4 colors are canonical.** Don't add a 5th sub-DAG without first asking "is this really a different category, or a sub-role within an existing one?" ORCHESTRATION is reserved for the existing runtime spine.

5. **Reuse the substrate.** Every cycle reads existing files (BUILD_THESE, agent_defs, products, hf_hub). Never duplicate.

---

## §9 — The recursion principle (restated)

Every product ships → produces chain data → MoE retrieval gets smarter → next cycle has more context → router picks better providers → next product gets built cheaper. **The loop runs cheaper as the system grows.** Marginal inference cost trends to zero. Margin expands forever.

This is the engine. Everything else is interchangeable.

---

## §10 — The 5th sub-DAG: RECURSIVE_WORKFLOWS (added 2026-05-28)

`core/lib/recursive_workflows.py` walks the universal graph (ops_dag + dag_loop combined: 215 nodes × 164 edges) and detects three categories of self-reference:

### 10.1 Strongly-connected components (Tarjan)
Clusters where every node can reach every other. These are the system's **true feedback loops**.

Today's run found 1 SCC of size 4 spanning every sub-DAG:
```
op_provider_groq    (INFERENCE)
    ↓ produces
op_doc_dag_flow     (DOCS)
    ↓ feeds_into
op_discord_mcp      (PLATFORMS)
    ↓ feeds_back
op_product_avatar_nft (APPS)
    ↓ ingests_from
op_provider_groq    ← closes the ring
```
Crystal: `9abb1112e4931f2d…` — this is the canonical "the system is alive" recursion.

### 10.2 Simple cycles (bounded DFS, Johnson-style pruning)
Enumerated ordered loops up to length 8. Today: 2 simple cycles.

### 10.3 Repeated motifs (canonical signature matching)
3-node sequences (by node kind) appearing ≥3 times. Today's discoveries:

| Pattern | Repetitions | Meaning |
|---|---|---|
| `agent → placeholder → placeholder` | 62 | most common substrate shape — agents fronting forward-placeholder chains |
| `placeholder → placeholder → placeholder` | 52 | text_placeholder hop chains (the "to do" surface) |
| `pass → pass → pass` | 17 | workflow_card pass sequences |
| `agent → agent → agent` | 15 | agent call chains |
| `agent → agent → placeholder` | 14 | agents calling other agents that have forward stubs |
| `doc → app → platform` | 4 | the **canonical loop output direction** |
| `platform → app → platform` | 4 | apps that feed back to source platforms |

### 10.4 Integration
- 10 recursions persisted at `studio/assets/_recursions/<id>_<crystal>.json`
- `dag_loop.load_recursive_workflows()` loads them as the 5th sub-DAG (RECURSIVE_WORKFLOWS)
- `dag_render.py` adds a red center panel (`#e53935`) showing the recursions
- Each recursion has a crystal computed over `(kind, sorted(nodes), sorted(edge_kinds_traversed))` — deterministic, replay-able
- The 5th sub-DAG references back into source nodes via `kind="references"` edges (adds 157 new edges, mostly to the motifs that hold dozens of nodes)

### 10.5 CLI surface
```bash
python3 core/lib/recursive_workflows.py all       # full detection + persist + log
python3 core/lib/recursive_workflows.py scc       # Tarjan only
python3 core/lib/recursive_workflows.py cycles    # simple cycles only
python3 core/lib/recursive_workflows.py motifs    # repeated patterns only
python3 core/lib/recursive_workflows.py list      # persisted recursions
python3 core/lib/recursive_workflows.py graph     # universal graph metrics
```

### 10.6 Why recursions matter
- **A new product/MCP/module that doesn't appear in any recursion** is an isolated leaf — it needs feedback to compound. Easy detector for "you built a thing but nothing uses it."
- **Motif counts tell you what shapes the system favors**. Dominance of `agent→placeholder→placeholder` = lots of forward planning, less wiring — exactly today's state.
- **The SCC is the heartbeat**. If `cc loop cycle` runs but the SCC size drops, something disconnected the loop. Replay the previous cycle's crystal to find what broke.

### 10.7 Universe right now (final)

```
PLATFORMS    37 nodes
DOCS         59 nodes (parsed new ones this turn)
INFERENCE    27 nodes
APPS          6 nodes
RECURSIVE_WORKFLOWS  10 nodes   ← NEW
TOTAL       139 nodes · 174 edges · 4 cycles recorded · chain verified
```

The system now knows what's recursive about itself. Every new module ships into a universe that auto-detects whether the new module joined a recursion or stayed a leaf. That's the closure.

[ end of LOOP-ARCHITECTURE.md — v2 (5 sub-DAGs) ]
