# MySpace++ — Open Questions
# IP CONFIDENTIAL

Decisions Tom needs to make before phase 0 begins. Each block lists the
question, the options I see, and my recommendation. Reply inline (edit
this file) or just tell me your pick.

---

## 1. Name — DECIDED → `MySpace++`

The filesystem dir is `MySpace++`. The name carries three references
at once: HuggingFace Spaces (deployment target), MySpace (your-own-
space personalization), and `++` (next-gen, increment).

**Sub-question — normalized names for ecosystems that can't take `++`:**

| Where | Allowed chars | Proposed name |
|---|---|---|
| GitHub repo | `+` ok | `MySpace++` (preserves the look) |
| Docker Hub | lowercase + `-` only | `myspace-pp` or `myspace-plus` |
| npm package | no `+` | `myspace-pp` |
| PyPI package | `+` normalized → `-` | `myspace-pp` |
| Homebrew formula | lowercase + `-` only | `myspace-pp` |
| Nix flake output | lowercase + `-` recommended | `myspace-pp` |
| HF Space slug | lowercase + `-` only | `myspace-pp` |
| Binary on PATH | shell-safe | `myspace` (no `++` — calls itself the `myspace` CLI in terminals) |

**Recommendation:** **`myspace-pp`** as the universal normalized
slug, **`myspace`** as the on-disk binary name. The `++` lives in
the brand mark (logo, README header, screenshots) but never in code
or config strings. This avoids the worst-case scenario where a
shell-quoting bug or Docker pull silently fails because of `+`.

**Your pick:** _____

---

## 2. License — DECIDED → "fuckyou payme" (proprietary)

Tom's standing rule: all his projects are proprietary, all rights
reserved, no commercial use without a written paid license. Source
may be visible on GitHub for trust/audit but is NOT under any OSI
license. Personal eval is tolerated; everything else costs money.

Concrete terms (see `LICENSE.draft.md` for the actual text):
- Copyright Tom Lee (Zero2oneZ), all rights reserved
- No redistribution
- No commercial use without written license
- No warranty
- No contributions accepted without a signed CLA assigning copyright
  to Tom (CLA TBD; defer until first outside contributor shows up)

Implications for the repo:
- `LICENSE` file is the proprietary text, not an OSI identifier
- GitHub repo metadata: license = "Other" or "Source-Available"
- README must say "Not Open Source" in plain English near the top
  so casual visitors don't assume MIT-by-default
- Docker image `LABEL` carries the license string
- npm `package.json` "license" field gets `SEE LICENSE IN LICENSE`
- PyPI `License-Expression` gets `LicenseRef-Proprietary`

---

## 3. Schema sharing with gently-cc

**Context:** `gently-cc` already has its own state model (`~/.gently/`
agent-identity, CODIE compression, BARF foam). This repo's substrate
uses sqlite with 22 tables in `~/.cc/`.

**Options:**
- **Fully separate** — `~/.cc/` for MySpace++, `~/.gently/` for
  gently-cc. Users of both see two databases, two CLIs.
- **Cross-link via meta keys** — MySpace++'s local DB stores a
  `gently_session_id` meta key when gently-cc is also installed.
  Each tool reads its own DB; bridges are explicit.
- **Shared schema** — MySpace++'s `db.py` imports gently-cc's
  schema where they overlap. One DB for both tools.

**Recommendation:** **Cross-link via meta keys**. Fully separate is
the cleanest cross-OS story (gently-cc isn't on Windows yet), and
the meta-key bridge means power users get the unified view without
forcing every MySpace++ user to install gently-cc.

**Your pick:** _____

---

## 4. Bundled model

**Options for the docker-compose default model:**
- `qwen2.5-coder:0.5b` (~400 MB) — fits anywhere, often dumb
- `qwen2.5-coder:1.5b` (~1 GB) — your current `CC_TINY_MODEL` default
- `qwen2.5-coder:7b` (~4.5 GB) — much smarter, needs 8 GB RAM minimum
- `qwen2.5:3b` (~2 GB) — general-purpose, not code-tuned
- ship with NO model — user pulls one after `compose up`

**Recommendation:** **`qwen2.5-coder:1.5b` bundled**. It's already
your tested default; image stays under 2 GB; runs on a laptop without
a discrete GPU. Add a doc page on swapping to 7b for power users.

**Your pick:** _____

---

## 5. Windows strategy — DECIDED → container-only for v1

Windows users get the Docker UX. No native bash install, no WSL
installer, no python rewrite. The bash substrate stays pristine;
Docker Desktop is the supported entry point.

Implications for phase 0/1:
- `install.ps1` is a thin wrapper that checks for Docker Desktop
  and runs `docker compose up -d` against the bundled compose file.
  If Docker isn't installed, it points at docs/install-docker-windows.md.
- No Windows path in `core/tests/smoke.sh` — the Windows smoke test
  is "does `docker compose exec myspace cc -help` work after install".
- v2 may add native Windows once we have users asking for it.
  Until then, stop work on git-bash compatibility shims.

---

## 6. First-class frontend

**Phase 3 ships streamlit, gradio, and a TUI launcher. Which is the
"hero" UI in marketing/screenshots?**

**Options:**
- **Streamlit** — your existing `cc studio` already runs there.
  Lowest porting cost. Dashboard-flavored.
- **Gradio** — chat-flavored, more natural for the "super-chatbot"
  positioning. HF Spaces convention.
- **TUI** — terminal-native. Strong for developer audience. Doesn't
  screenshot well for non-devs.
- **All three equal** — marketing-neutral, but harder to pitch.

**Recommendation:** **Gradio as hero, streamlit as power-user
dashboard, TUI for the dev audience.** This matches phase 5's
super-chatbot positioning: the demo is a gradio chat, the workshop
is the streamlit studio, the daily-driver is the TUI.

**Your pick:** _____

---

## 7. CI/CD platform

**Options:**
- **GitHub Actions** — free for public repos, baseline expectation
- **Self-hosted runner on z21** — uses your dual-3090 box for big
  model tests; private; requires uptime
- **Both** — GH Actions for smoke tests, z21 runner for swarm
  determinism tests that need a GPU

**Recommendation:** **GitHub Actions for v1.** Don't put z21 in the
hot path. Run determinism tests against the 1.5b model which fits
on a GHA runner. Add z21 runner only when we have a regression
that requires it.

**Your pick:** _____

---

## 8. Telemetry / usage analytics

**Should `cc` ever phone home?**

**Options:**
- **Never.** No telemetry of any kind.
- **Opt-in.** First run prompts: "share anonymous usage stats?"
  Default no.
- **Opt-out crash reports only.** Tracebacks get sent to a
  MySpace++ Sentry. Default yes; user can disable.

**Recommendation:** **Never** for v1. Telemetry is a trust grenade
for a tool that markets itself as deterministic and scope-disciplined.
Revisit once we have paying users who actively want it.

**Your pick:** _____

---

## 9. Distribution channels

**Where do users discover and install this?**

**Possible (not mutually exclusive):**
- [ ] GitHub repo (the obvious)
- [ ] Docker Hub image (`docker pull tomlee/cc`)
- [ ] Hugging Face Space (a "try cc in the browser" demo Space)
- [ ] npm (`npm i -g cc-cli` — installs the dockerized version)
- [ ] PyPI (`pip install cc-determinist` — python wrapper that
      shells to bash)
- [ ] Homebrew formula (macOS)
- [ ] Nix flake (already in scope)
- [ ] AUR package (Arch users)

**Recommendation:** Start with **GitHub + Docker Hub + Hugging Face
Space demo**. The HF Space is your marketing surface — a one-click
chat with cc that anyone can try without installing. npm/PyPI come
after we know what the install ergonomics actually look like.

**Your pick (check all):** _____

---

## 10. Demo project for the launch

**Phase 5 builds a super-chatbot that can build automations. What's
the headline demo we show on day one?**

**Options:**
- **YouTube → captioned-clip pipeline** — user pastes a YT URL,
  gets back a vertical 30s clip with auto captions. Concrete,
  visually shareable, ties into existing MediaLab work.
- **TopstepX backtest snippet** — user describes an indicator
  rule, gets a backtest report. Ties into trade-blob. Niche
  audience but high-affinity.
- **Inbox triage bot** — user grants Gmail access, gets a daily
  summary + draft replies for low-effort messages. Broad appeal
  but requires OAuth complexity at demo time.
- **HF Space scaffolder** — user describes a Space, cc generates
  + pushes it. Meta-demo — cc building cc-shaped things. Strong
  story for the dev audience.

**Recommendation:** **HF Space scaffolder** as the headline. It's
the most honest demonstration of what the system actually does
(decompose → compose → deploy) and the deployment artifact is
itself a sharable URL. The YouTube clip demo is the natural
phase-5b once the scaffolder works.

**Your pick:** _____

---

## What I need from you to start phase 0

Phase 0 blockers — ALL RESOLVED:
- Name: `MySpace++` (slug `myspace-pp`, binary `myspace`)
- License: proprietary, "fuckyou payme" (see `LICENSE.draft.md`)
- Windows strategy: container-only for v1

**Phase 0 is unblocked. The port can begin on Tom's go-ahead.**

Remaining questions (3, 4, 6–10) defer to the phase they belong to:
- Q3 (gently-cc schema sharing) — answer before phase 4
- Q4 (bundled model) — answer before phase 2
- Q6 (hero frontend) — answer before phase 3
- Q7 (CI platform) — answer before first GitHub push
- Q8 (telemetry) — answer before public release
- Q9 (distribution channels) — answer before launch
- Q10 (demo project) — answer before phase 5
