@.cc/CLAUDE.context.md

# MySpace++ — project instructions for Claude sessions

> **THIS IS ONE OF TWO HALVES.**
>
> - MySpace++ (you are here) — Python · bash · Streamlit · the user-facing studio
> - GentlyOS (`/data/Projects/gently/`) — Rust · `.bb` · crystal DAG · the deterministic runtime
>
> Both halves talk to each other through a single file: **`studio/docs/NOTES-FOR-INFERANCE.md`**
>
> Read it at the **start** of every session. Update it at the **end** of every session.

---

## What MySpace++ does (one paragraph)

A deterministic-first terminal substrate for orchestrating local + frontier AI models. One bash dispatcher (`cc`), one global SQLite DB (`~/.cc/cc.db`, 28 tables), one optional per-project DB (`<proj>/.cc/local.db`), a dozen Python helpers, and a Streamlit studio with passes/inference/wardrobe/Pinterest/YouTube/Tesseract/WEAVE/Lucid subsystems. Multi-device by design; friends register as compute workers via WebGPU.

Full architectural map: `studio/docs/TWINS-MASTER.{svg,md}` + `studio/docs/TESSERACT.{svg,md}`.

---

## Inter-session communication — the protocol

The other half (the GentlyOS Rust chain in `/data/Projects/gently/`) is doing complementary work:

- `.bb` stack-machine runtime (deterministic, content-addressed)
- Crystal DAG (IPFS + Sui NFT per session)
- `OpKind` instruction sequences targeting models via `telos-ml-tools` MCP
- `codie-v4-predict` (TabPFN-flavored opcode router)
- Mirror-pass + genesis-anchored self-validation

**Communication file**: `studio/docs/NOTES-FOR-INFERANCE.md`

Both sessions read + write this file. It contains:
1. A shared PLAN with checkboxes
2. TODOs split by side (`[mspc]` / `[gently]` / `[both]`)
3. Questions for the other side (numbered)
4. Answers to anticipated questions
5. What each side has walked of the other's DAG
6. Cadence rules

**Cadence**:
- Open every session by reading `NOTES-FOR-INFERANCE.md`
- When you finish a thing on the PLAN, mark it `[x]` and add the line `Updated by: <half> at <iso-ts>`
- When you have a question for the other side, add it to the Q&A section with a unique ID (`Q-MSPC-001`, `Q-GENTLY-001`)
- When you answer a question from the other side, copy it into the answers block + check it off
- Don't delete things — the file is append-only at the section level

Two companion docs frame the conversation:
- `studio/docs/RUST-CHAIN.md` — MySpace++ side's understanding of the gently chain
- `studio/docs/COMPLEX-DAG.svg` — the master DAG showing both halves + their interfaces

---

## Project tree (quick reference)

```
core/cc                          main bash dispatcher (~130 cmd_X functions)
core/lib/db.py                   28-table SQLite schema (the GLOBAL twin)
core/lib/chain.py                cc -chain parser + executor

studio/paths.py                  canonical layout (single source of truth)
studio/bootstrap.py              idempotent dir creator
studio/auth/                     gate + keys.sqlite + ssh_friend_setup
studio/proxy/claude_proxy.py     Claude guest-pass proxy (port 8520)
studio/passes/                   20 declarative passes + filetype DAG
studio/tesseract/                meta-DAG (8 sub-DAGs, 253 nodes, 729 edges)
studio/weave/                    cross-device compute fabric (WebGPU + PLANS)
studio/pinterest/                Pinterest search + auto-organize
studio/lucid/                    Lucid Standard Import bridge
studio/media/.tools/             intake + sidecar + separate + import_pipeline
studio/docs/                     TESSERACT · TWINS-MASTER · NOTES-FOR-INFERANCE
                                 PASSES_DAG · WEAVE · LUCID_INTEGRATION
                                 RUST-CHAIN · COMPLEX-DAG.svg
```

---

## Hard rules

1. **NOTES-FOR-INFERANCE.md is the only path** for coordinating with the gently half. Don't message the other side any other way.

2. **`.env`** is mirrored between `/data/Projects/MySpace++/.env` and `/data/Projects/gently/.env`. Keys: `claude_guest`, `client_api`, `pintrest_api`, `SUI_WALLET`. Never commit. Both halves read from their local copy.

3. **Opcode taxonomy** at `planning/hf_task_evolution.jsonl` is **shared canonical data**. If either side adds a new opcode, it goes here. The gently side reads this file too.

4. **Salted-token registry** at `studio/auth/keys.sqlite` (mode 600) is per-host. Friends' tokens issued via `cc -keys-distribute` are valid on the issuing host only.

5. **Tom's pending edits**: don't commit unless explicitly told. Tom has a lot of in-flight files (run-*.sh, wardrobe_studio.py, app.py, project_io.py, projects/, etc.).

6. **Agent identity header** required on every response (per `/home/tom/.claude/CLAUDE.md`).

---

## Quick commands

```bash
# Status overview
cc -scope                          # current project + agent UUID + DBs
cc -context                        # full state dump

# Cross-session
cc -tesseract-build                # rebuild master Tesseract SVG (after schema change)
python3 studio/tesseract/twins.py  # rebuild TWINS-MASTER SVG
python3 studio/tesseract/complex_dag.py  # rebuild COMPLEX-DAG (both halves)

# WEAVE (cross-device compute)
cc -weave-seed                     # seed 4 sample devices + 8 plans
cc -weave-status                   # online/offline counters
cc -weave-route mask HEAVY --import-time

# Inference loop
cc -passes-run <file>              # 6-step inference pipeline on one file
cc -passes-stats                   # what's already computed

# Comm channel
$EDITOR studio/docs/NOTES-FOR-INFERANCE.md
```

---

## When opening a fresh session, first 3 steps

```
1. Read this file (you just did).
2. Read studio/docs/NOTES-FOR-INFERANCE.md.
3. Run cc -context  (or studio/tesseract/twins.py to refresh state).
```

If the other half left a question in NOTES-FOR-INFERANCE.md, that's your top priority.
