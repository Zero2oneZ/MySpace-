# MySpace++ — Phased Build Plan
# IP CONFIDENTIAL

The build sequence is **strictly phased**. Each phase produces something
that works end-to-end. Don't start phase N+1 until phase N has a passing
smoke test.

---

## Phase 0 — Extract & document the deterministic core

**Goal:** the current `cc` lives in `~/.local/bin/cc` and `~/.cc/lib/`.
Move it into a self-contained repo, document every invariant, and write
smoke tests so future ports can't regress.

- [ ] Copy `~/.local/bin/cc` → `core/cc`
- [ ] Copy `~/.cc/lib/{db.py,tui.py,studio.py}` → `core/lib/`
- [ ] Copy `~/.cc/setup/{setup.sh,setup.ps1}` → `core/setup/`
- [ ] Write `core/tests/smoke.sh`:
      - `cc -help` returns text
      - `cc -setup` in tmpdir creates `.cc/local.db` with all 22 tables
      - `cc scope` outputs all the expected fields
      - `cc tiny "hello"` returns text (skip if ollama not running)
      - `cc -agents` shows the test process as live, then done after exit
      - Same prompt twice → same response, second one served from cache
- [ ] Write `core/tests/determinism.sh`: assert that two identical
      `cc tiny` calls produce byte-identical output and the cache file
      is reused (check mtime).
- [ ] Rip out hardcoded paths — everything goes through `CC_HOME`,
      `CC_GLOBAL_DB`, `CC_LIB`, `CC_CACHE` env vars (already mostly done).

**Exit criterion:** `cd /tmp/cc-test && CC_HOME=$PWD/.cc-home cc -setup`
works and all smoke tests pass.

---

## Phase 1 — Cross-OS install

**Goal:** one-command install on Linux, macOS, Windows.

- [ ] `flake.nix` — defines a `cc` package (bash + python + jq + curl +
      sqlite + sha256sum bundled). `nix run github:tom/MySpace++#cc -- -help`
      should just work on any NixOS or nix-installed machine.
- [ ] `Dockerfile` — Alpine or Debian-slim base. Installs the same deps.
      Image size target: under 200 MB without ollama, under 4 GB with
      a 1.5b model pre-pulled.
- [ ] `install.sh` — bash installer for Linux/macOS users without nix.
      Detects package manager (apt, brew, pacman, nix-env), installs
      deps, drops `cc` into `~/.local/bin`.
- [ ] `install.ps1` — PowerShell installer for Windows. Uses winget or
      scoop for jq/curl/python; bundles `cc` as a `.cmd` wrapper that
      shells out to bash (WSL or git-bash).
- [ ] Document the Windows story explicitly — bash on Windows is the
      tricky part. Either: require WSL, or rewrite `cc` core in python.
      See OPEN_QUESTIONS.md.

**Exit criterion:** the smoke tests from phase 0 pass on Linux, macOS,
and Windows (under WSL or whatever path we settle on).

---

## Phase 2 — Container stack with Ollama

**Goal:** `docker compose up` gives you cc + ollama + a default tiny
model, all wired and persistent.

- [ ] `docker-compose.yml`:
      - `cc` service (runs bash + python helpers)
      - `ollama` service (bind-mounts `~/.ollama` so models persist)
      - shared volume for `cc.db` and per-project `local.db`s
      - healthcheck on ollama before cc starts
- [ ] Default model: bundled `qwen2.5-coder:1.5b` (current
      `CC_TINY_MODEL` default). See OPEN_QUESTIONS.md for size trade-off.
- [ ] `docker compose exec cc cc tiny "hello"` returns deterministic text.
- [ ] Clean shutdown: `docker compose down` releases all agent rows.
- [ ] CI: GitHub Actions builds the image on every push, runs smoke
      tests inside.

**Exit criterion:** a fresh machine with only docker installed can
clone the repo and have a working `cc` + ollama stack in under 5
minutes (model download not counted).

---

## Phase 3 — Frontend layer

**Goal:** the same substrate, viewed through three windows.

- [ ] `frontends/streamlit_app.py` — port `cc studio` so it runs inside
      the container against the shared db. Reachable at `:8501`.
- [ ] `frontends/gradio_app.py` — chat-shaped UI. Each user message
      becomes a `cc phase step`, response renders inline. Reachable
      at `:7860` (HF Spaces convention).
- [ ] `frontends/tui_launcher.sh` — wraps `docker compose exec cc cc tui`
      so you can hit a key on the host and get the curses dashboard.
- [ ] All three frontends read/write the same `cc.db` — so a swarm run
      kicked off in gradio shows up live in tui.

**Exit criterion:** an end user can interact with cc through any of
the three frontends and see consistent state.

---

## Phase 4 — Frontier adapters

**Goal:** treat Claude and Codex as **escalation paths**, not defaults.

- [ ] `adapters/ollama.py` — already the substrate; formalize as the
      reference implementation.
- [ ] `adapters/claude_code.py` — invokes `claude -p` with cc context.
      Already exists in bash; port to python for testability.
- [ ] `adapters/codex.py` — calls OpenAI codex / GPT-4o via API.
- [ ] `adapters/hf_spaces.py` — pushes any HuggingFace model and runs
      inference via their inference API (free tier on many models).
- [ ] **The escalation rule:** every `cc swarm` / `cc workflow` step
      first tries the configured local model. If `model_call` returns
      `rc=2` (partial — no DONE) twice in a row, escalate to the next
      adapter in the chain. Log the escalation in the run row.
- [ ] Comparison harness: same prompt → ollama vs claude vs codex.
      Render side-by-side in studio. This is how we prove determinism
      is enough for the common case.

**Exit criterion:** a user can run a 10-step swarm with ollama-only
and a 10-step swarm with claude-only, and the system records cost
per step (zero for ollama, $X for claude).

---

## Phase 5 — Super-chatbot orchestrator

**Goal:** the user types "build me a trading bot that watches BTC and
posts to discord when RSI crosses 30" — cc decomposes, builds, deploys.

- [ ] Decomposer agent (defined as a `cc agent`): takes a free-form
      request, outputs a `cc swarm define` JSON.
- [ ] Scaffolder agent: takes the swarm JSON + context, outputs file
      content for a Hugging Face Space (app.py, requirements.txt,
      README.md, .gradio config).
- [ ] HF Spaces deployer: `huggingface_hub` library, creates a new
      space under user's account, pushes files, waits for build.
- [ ] Example library — pre-built decompositions:
      - `examples/simple_chat/` — gradio chat hitting ollama
      - `examples/video_pipeline/` — ffmpeg + whisper + caption overlay
      - `examples/trading_bot/` — ccxt + indicator lib + webhook poster
      - `examples/business_automation/` — Zapier-style task pipeline
- [ ] **The chatbot is just a wrapper** around `cc agent` and
      `cc workflow`. It MUST NOT introduce new primitives. If a new
      primitive is needed, add it to the substrate first.

**Exit criterion:** a user types one sentence and ends up with a
running HF Space within 5 minutes, with all build steps traceable
through `cc -context`.

---

## Proposed repo layout

```
MySpace++/                         # filesystem name; npm/docker get normalized
├── README.md                      # planning notes (this dir, for now)
├── PLAN.md
├── ARCHITECTURE.md
├── OPEN_QUESTIONS.md
├── LICENSE                        # TBD — see OPEN_QUESTIONS
├── flake.nix                      # Phase 1
├── flake.lock
├── shell.nix                      # back-compat for nix-shell users
├── Dockerfile                     # Phase 1
├── docker-compose.yml             # Phase 2
├── .dockerignore
├── .github/
│   └── workflows/
│       ├── smoke.yml              # Phase 0 tests
│       └── docker.yml             # Phase 2 image build
├── install.sh                     # Phase 1 — Linux/macOS
├── install.ps1                    # Phase 1 — Windows
├── core/                          # Phase 0
│   ├── cc                         # the bash script
│   ├── lib/
│   │   ├── db.py
│   │   ├── tui.py
│   │   └── studio.py
│   ├── setup/
│   │   ├── setup.sh
│   │   └── setup.ps1
│   └── tests/
│       ├── smoke.sh
│       ├── determinism.sh
│       └── fixtures/
├── adapters/                      # Phase 4
│   ├── ollama.py
│   ├── claude_code.py
│   ├── codex.py
│   └── hf_spaces.py
├── frontends/                     # Phase 3
│   ├── streamlit_app.py
│   ├── gradio_app.py
│   └── tui_launcher.sh
├── examples/                      # Phase 5
│   ├── simple_chat/
│   ├── video_pipeline/
│   ├── trading_bot/
│   └── business_automation/
└── docs/
    ├── DETERMINISM.md             # the contract
    ├── PORTABILITY.md             # OS matrix
    └── ESCALATION.md              # when to leave the local model
```

---

## What NOT to build

- A new schema. `db.py` already covers 22 tables across projects,
  todos, runs, agents, workflows, swarms, phases, tools, chats.
  Extend it; don't replace it.
- A new agent definition format. `cc agent define` + `cc swarm define`
  already work. The chatbot in phase 5 emits these, doesn't reinvent.
- A new orchestration engine. `cc swarm run` already loops with
  `loop_until` sentinel + `max_iters`. Use it.
- A new caching layer. `model_call` already caches by
  `sha256(model + prompt + opts)`. The HF Spaces adapter caches the
  same way against the inference API.

**The whole point of this repo is to prove that what's already built
is sufficient.** Every new file should make the existing core
*reachable from somewhere new*, not *duplicate* existing functionality.
