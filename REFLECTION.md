# Reflection — how MASTER-INWARD ⇄ MASTER-OUTWARD stay in sync

**Created:** 2026-05-26
**Pair files:**
- `/data/Projects/MySpace++/MASTER-INWARD.svg` (forward chain — ingest, agentic flows, construction, storage, protective principles)
- `/data/Projects/MySpace++/MASTER-OUTWARD.svg` (mirror chain — downstream consumers, egress flows, served artifacts, read endpoints, verifiable proofs)
- `/data/Projects/MySpace++/MASTER-INFERENCE.svg` (request lifecycle — runtime view; remains the operational scheduler)
- `/data/Projects/MySpace++/studio/docs/Tesseract.svg` (sister Claude's 253-node inventory — WHAT exists)

---

## TL;DR

Two SVGs. One chain. Every node on one side has exactly one mirror node on the other side, bound by a shared ID. When a node updates on one side (a new file ingested, a new endpoint exposed), the `gently-mirror-pair` daemon propagates the change to its mirror by mutating only the bound data fields. The daemon refuses to extend the project chain if either side falls out of sync, so drift between forward and mirror becomes mechanically impossible. The pair IS the mirror-pass anti-particle construction (run #2.5) applied at the project-view layer.

---

## The reflection contract

### One-to-one pairing via IDs

```
MASTER-INWARD.svg                                MASTER-OUTWARD.svg
─────────────────                                ──────────────────
<g mspc:src-id="huggingface">                    <g mirror:id="hf-export">
   "HuggingFace Hub"                                "model graph subscribers"
   what we INGEST                                   what we PUBLISH
   ⇄ mirror:id=hf-export                            ⇄ mirror:id=huggingface
```

Every group on INWARD declares exactly one of:

| Attribute namespace | Meaning |
|---|---|
| `mspc:src-id` | Layer 0 — external source |
| `mspc:flow-id` | Layer 1 — agentic ingest flow |
| `mspc:construct-id` | Layer 2 — runtime construction step |
| `mspc:store-id` | Layer 3 — storage layer |
| `mspc:principle-id` | Layer 4 — constitutional principle |

Every group on OUTWARD declares the same value as `mirror:id`. The daemon walks both SVGs, builds the ID → element map, and verifies one-to-one bijection. Missing pairs are a hard error.

### Update propagation

1. **A change happens on the forward side** (e.g., agent ingests a new HF model — the corresponding `<g mspc:src-id="huggingface">` node has its `mono` counts updated: ~500 → ~501)
2. The agent writes the forward SVG change atomically
3. `gently-mirror-pair` daemon detects the change (file watcher OR explicit `cc -mirror-sync` call)
4. The daemon reads the new state, computes the change set
5. For each changed node on the forward side, locates the mirror node by ID
6. Updates ONLY the bound data fields on the mirror (model count, last-updated timestamp, derived attributes)
7. Recomputes the pair crystal: `crystal = blake3(forward_bytes ⊕ mirror_bytes)` and writes it to `<metadata>` on both files
8. If the daemon cannot find a matching mirror node, it refuses to commit the update — repair required first

### What the daemon NEVER does

- **Never** reshape geometry (no moved rects, no resized boxes, no swapped colors)
- **Never** add or remove nodes (changes to either count are flagged for human review)
- **Never** mutate styles or layout
- **Never** silently drop a mirror pair

Layout changes go through `cc -mirror-author` which prompts for the matching change on the sister file before commit.

---

## Why two SVGs instead of one

The mirror-pass anti-particle architecture (constitutional principle #3) says: every op has its inverse at the mirror position; tampering requires erasing both. Applying this at the project-view layer means:

- **Single SVG** → one tape; tampering can rewrite history undetected
- **Two SVGs with paired IDs** → forward + mirror; tampering requires editing both consistently, which the daemon catches
- The crystal in `<metadata>` is the deterministic identity of the WHOLE pair; mismatched bytes mean someone touched one without the other

This is the same construction `gently-runtime::run()` does for chain ops, just at the human-visible documentation layer.

---

## The full pair manifest

Listed once. The daemon's authoritative ID → element map.

| Layer | Forward (INWARD) ID | Mirror (OUTWARD) ID | What it means |
|---|---|---|---|
| 0 | `huggingface` | `hf-export` | HF as source / our index as subscribed mirror |
| 0 | `user-visit` | `svg-response` | browser GET / SVG response served |
| 0 | `agent-prompts` | `agent-actions` | Claude/codie prompts / their resulting actions |
| 0 | `local-files` | `published-assets` | FBX assets ingested / served |
| 0 | `btc-chain` | `sealed-crystals` | BTC block-height clock / BTC-anchored crystals |
| 0 | `friend-invites` | `reachable-nodes` | salted-key URLs / scope-filtered surfaces |
| 0 | `probe-calibration` | `binding-affinity` | probe runs / served binding maps |
| 0 | `claude-self` | `crystal-cascade` | self-reflection logs / session crystal feeds |
| 1 | `hf-scrape-flow` | `hf-export-flow` | scrape pipeline / serve pipeline |
| 1 | `codie-predict-flow` | `opcode-stream` | predict next op / stream op to client |
| 1 | `walker-identify-flow` | `svg-status-export` | walker.identify / tesseract status export |
| 1 | `import-pipeline-flow` | `indexed-pieces` | asset import / pieces_index served |
| 1 | `probe-calibrate-flow` | `scheduler-routing` | probe calibrate / scheduler routing served |
| 1 | `cc-chain-flow` | `chain-output` | cc -chain parser / chain output flow |
| 2 | `bb-fragments` | `task-routes-published` | .bb composition / served task routes |
| 2 | `meta-moe-nesting` | `meta-moe-served` | 4-level nested .bb / meta-MoE endpoint |
| 2 | `scheduler-pruning` | `active-layer-fingerprint` | binding pruning / active layer envelope |
| 2 | `dedup-gate` | `dedup-decisions` | dedup index / dont-rebuild-this responses |
| 2 | `recipe-composer` | `published-recipes` | composer / band+designer endpoints |
| 2 | `crystal-seal` | `sealed-publish` | seal forward+mirror / serve SealedChain |
| 3 | `cc-db-global` | `cc-global-publish` | global cc.db / cc -context-style endpoints |
| 3 | `local-db` | `local-project-export` | local.db / per-project exports |
| 3 | `gently-db` | `gently-db-export` | gently postgres / read API |
| 3 | `kimi-index` | `index-published` | consolidation JSONL / index endpoints |
| 3 | `probe-bb` | `routing-maps-served` | probe calibration files / served maps |
| 3 | `memory-files` | `session-continuity` | auto-memory dir / future-session reads |
| 4 | `gently-bb-rock` | `bb-rock-export` | constitutional rock / verifiable bb hash |
| 4 | `genesis-anchor` | `genesis-stamp-export` | chain[0..32] anchor / exported stamp |
| 4 | `mirror-pass` | `mirror-export-policy` | anti-particle construction / shipped pair |
| 4 | `open-window` | `open-window-publish` | session open windows / committed delta publish |
| 4 | `btc-anchor` | `btc-stamp-export` | opt-in BTC anchor / verifiable block stamp |
| 4 | `y-combinator` | `axiom-published` | runtime axiom / served 8-LOC for verification |

32 pairs across 5 layers. If either file gains or loses a pair without the other, the daemon refuses to extend. The pairs ARE the project's constitutional manifest.

---

## How the agent loop closes through this pair

```
                                forward (INWARD)
                                ─────────────────
                ┌─────────────► HF/users/agents/files/btc/probes ingest
                │               │
                │               ▼
                │            agentic flows (scrape, predict, walk, import, ...)
                │               │
                │               ▼
                │            runtime construction (.bb compose, meta-moe, scheduler, ...)
                │               │
                │               ▼
                │            storage (cc.db / local.db / gently db / indices / memory)
                │               │
                │               ▼
                │            constitutional protection (6 principles)
                │               │
                │               ▼
                │       gently-mirror-pair daemon walks
                │               │
                │               ▼
                │            mirror (OUTWARD)
                │            ─────────────────
                │            consumers (subscribers/visitors/agents/friends/etc.)
                │               │
                │               ▼
                │            agentic egress flows
                │               │
                │               ▼
                │            served artifacts (task routes, meta-MoE, recipes, ...)
                │               │
                │               ▼
                │            read endpoints (cc.db reads, /api/*, /api/index/*)
                │               │
                │               ▼
                │            verifiable proofs (bb-rock hash, BTC stamps, ...)
                │               │
                └───────────────┴─ consumer behavior feeds back into next visit ┐
                                                                                │
                  ◄────────────────────────────────────────────────────────────┘
                              (browser visit → forward chain again)
```

The loop is closed. Every consumer interaction creates a new forward-side ingest (the visit), which propagates through the mirror, which the consumer sees, which generates the next visit. The crystal seals the pair at every commit.

---

## Implementation status

- [x] MASTER-INWARD.svg landed (forward chain, 6 layers, 32 nodes)
- [x] MASTER-OUTWARD.svg landed (mirror chain, 6 layers, 32 paired nodes)
- [x] REFLECTION.md (this file) authored
- [x] gently/docs/NOTES-FOR-INFERENCE.md authored (the rust-chain inference notes mirror of sister's NOTES-FOR-INFERANCE.md)
- [x] **2026-05-26T17:55Z — FIRST PRACTICE UPDATE shipped (SYNC-7)**: gently bumped kimi-index count ~38k → 208,550 (actual wc -l), mirror updated symmetrically, pair crystal computed manually + written into both `<metadata>/<mirror:crystal>` blocks. Crystal: `sha256:d25eee261f22ca0c4d36c08e23ced778ef371ac2ddefe97e48c57ff067c7be81`. v1 method = `sha256(forward XOR mirror, zero-pad)`. Proves the contract mechanic by hand; daemon automates once shipped.
- [ ] gently-mirror-pair daemon (~150 LOC Rust crate, watches both files, propagates updates, gates commits) — NOT YET BUILT (ownership TBD per Q-GENTLY-001 in sister NOTES §7)
- [ ] CI gate that runs the daemon's bijection check on every commit — NOT YET BUILT
- [ ] cc -mirror-sync command — NOT YET BUILT
- [ ] cc -mirror-status command (shows pairs + their last-update timestamps) — NOT YET BUILT

The SVGs and this document define the contract. The Rust daemon and the CLI surface are the next implementation moves.

---

## Update log (append-only)

| timestamp | by | what changed | crystal after |
|---|---|---|---|
| 2026-05-26T17:55Z | gently (main) | SYNC-7 first practice update. Bumped INWARD `mspc:store-id="kimi-index"` node count (~38k → 208,550 — counted with `wc -l`). Bumped OUTWARD `mirror:id="index-published"` node to reflect same. Computed pair crystal manually via python `hashlib.sha256(bytes(a^b for a,b in zip(fwd, mir.ljust(len(fwd),0))))`. Wrote into both files' `<metadata>/<mirror:crystal>` blocks with `mirror:crystal-method` documenting v1 algorithm. | `sha256:d25eee261f22ca0c4d36c08e23ced778ef371ac2ddefe97e48c57ff067c7be81` |

---

## Drift signals (what to watch for)

| Symptom | Likely cause | Fix |
|---|---|---|
| Daemon refuses to commit | one side gained/lost a pair | `cc -mirror-diff` shows orphan IDs; add the missing mate |
| Crystal mismatch | one side edited without the other | `cc -mirror-rebuild-crystal` after fixing the asymmetry |
| Mirror node has stale counts | daemon hasn't run | `cc -mirror-sync` (manual trigger) or re-enable the watcher |
| New IDs missing from this REFLECTION.md table | someone added a pair without updating the manifest | add the row here; the daemon should also flag |
| `mirror:role` attribute changed | someone swapped which file is forward/mirror | refuse — the role is constitutional, never changes |

---

## The headline guarantee

**One side updates the other.** The two SVGs cannot drift without the daemon catching it, because their crystal in `<metadata>` is computed from both. Tampering with one without consistently updating the other breaks the seal. That is what "reflective" means in this context — not a render, but a constitutionally bound pair.

This applies the mirror-pass anti-particle construction at the project-documentation layer, turning the entire project view into a self-validating runtime.
