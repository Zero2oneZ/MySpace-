# MySpace++ — planning notes
# IP CONFIDENTIAL — Owner: Tom Lee (Zero2oneZ)
#
# The name nods to three things at once: HuggingFace Spaces (deployment
# target), MySpace (your-own-space personalization), and ++ (next-gen,
# increment). Filesystem dir is `MySpace++`; published artifact names
# get normalized — see OPEN_QUESTIONS §1.

This directory contains **planning notes only** — no code yet. The goal is to
agree on the shape of the repo before any file gets ported.

---

## Thesis

The `cc` bash terminal manager at `~/.local/bin/cc` (+ `~/.cc/lib/db.py`,
`tui.py`, `studio.py`) already does something rare: it executes deterministic
small-model dispatch with caching, agent lifecycle tracking, phase/swarm/
workflow orchestration, and two-DB scope discipline — all in **one bash file
and three python files, ~3300 lines total, with sqlite as the only persistent
store**.

We want to find out **how far that deterministic core can travel on its own**
before frontier models (Claude, Codex) need to be involved. If it can stand up
cross-OS in a container with just Ollama, that's the foundation. Everything
else — Streamlit/Gradio UIs, Hugging Face Spaces builders, the eventual
super-chatbot — composes on top.

---

## Why this matters

- **Determinism first, frontier second.** Most agent frameworks reach for
  frontier models on every step. We invert: try the small deterministic local
  model first (qwen2.5-coder:1.5b at temp=0, seed=42), only escalate when it
  fails or signals partial. Caching by `sha256(model + prompt + opts)` means
  the same prompt costs zero on repeat.
- **One substrate, many UIs.** `cc tui` (curses), `cc studio` (streamlit),
  future `cc chat` (gradio) — all share the same sqlite tables and the same
  agent lifecycle. The UI is replaceable; the substrate is not.
- **Portable scope.** Two-DB split (`~/.cc/cc.db` global, `<project>/.cc/local.db`
  per-project) means a user can drop into any directory and `cc` knows what
  project they're in. We want this to work identically on Linux, macOS,
  Windows, and inside a container.

---

## What "done" looks like

A user on **any OS** can:

1. Run **one install command** (`nix run`, `docker compose up`, or a single
   `install.sh`/`install.ps1`).
2. Get a working `cc` in their PATH, with Ollama pre-pulled, the global DB
   initialized, and the studio dashboard reachable at `localhost:8501`.
3. Run `cc -setup` in any project and have entrypoints / venv / repo
   auto-discovered.
4. Run `cc swarm define ... && cc swarm run ...` and watch deterministic
   multi-agent loops execute against the bundled local model, with full
   trace persisted in the project's `local.db`.
5. **Without ever touching a frontier API key**, build a working chatbot
   that exports to a Hugging Face Space.

Once that baseline is solid, frontier adapters (Claude Code, Codex) layer in
as **escalation paths**, not as the default.

---

## What's in scope

| Layer | Scope |
|---|---|
| **Substrate** | The bash `cc` script + `db.py` + `tui.py` + `studio.py`, hardened and portable |
| **Install** | nix flake (Linux/macOS native), Dockerfile (anywhere), install.sh, install.ps1 |
| **Container stack** | docker-compose with ollama + cc + optional streamlit/gradio |
| **Adapters** | ollama (deterministic core), then claude-code, then codex, then HF Spaces export |
| **Frontends** | streamlit (port of `cc studio`), gradio (chat-shaped wrapper), TUI launcher |
| **Examples** | simple chat, video pipeline scaffold, trading-bot scaffold, business-automation scaffold |

## What's out of scope (for now)

- GentlyOS integration (the 175-crate platform stays separate)
- `.bb` universal format (could connect later via an export adapter)
- `gently-cc` Claude Code substrate (different layer — that wraps Claude Code itself; this wraps the *terminal*)
- Anything requiring CUDA or > 4GB RAM (we want this to run on a laptop)

---

## Next steps

1. Read `PLAN.md` for the phased build sequence and repo layout.
2. Read `ARCHITECTURE.md` for the layer contracts (determinism, DONE protocol, two-DB split).
3. Answer the questions in `OPEN_QUESTIONS.md` so the first port can begin.
