# MySpace++

**Not Open Source.** Proprietary, all rights reserved. See `LICENSE`.

A deterministic-first terminal substrate for orchestrating local and
frontier AI models. One bash script, one sqlite database, three Python
helpers — the whole system fits in your head.

> Status: **Phase 0 — substrate port** in progress. See `planning/PLAN.md`
> for the full roadmap.

---

## What it is

`MySpace++` (binary name: `myspace`, package slug: `myspace-pp`) packages
the [`cc` terminal manager](planning/README.md) for cross-OS deployment.
The core thesis: **deterministic small-model dispatch is enough for most
agent tasks**, and frontier models (Claude, Codex) belong on the
escalation path, not the default path.

What you get:

- **Deterministic dispatch.** Every model call goes through `temp=0, seed=42`
  and a `sha256(model + prompt + opts)` cache. Same input → same output,
  byte for byte.
- **Two-DB scope discipline.** Global `~/.cc/cc.db` (projects, todos, queue)
  + per-project `<project>/.cc/local.db` (runs, agents, phases, chats).
  Walk-up resolution from `cwd` finds the right scope automatically.
- **Agent lifecycle tracking.** Every `myspace` invocation gets a UUID,
  claims an agent row at start, releases on exit. 5–10 concurrent
  terminals stop blurring together.
- **DONE-sentinel completion protocol.** Every model call gets a
  "end with DONE" directive appended. Responses are returned as
  `(text, rc)` where rc=0 means completed, rc=1 means transport
  failure, rc=2 means partial (truncation detected).
- **Swarm / workflow / phase orchestration.** Define agents, define
  swarms with `loop_until` sentinels, define workflows as JSON DAGs of
  registered tools.

---

## Install

Pick whichever fits your machine. All paths produce an interchangeable
`myspace` binary; the substrate is identical.

### Option A — Docker (recommended for first-time users)

The compose stack pulls ollama, fetches the default tiny model, and
gives you a ready-to-exec `myspace` container in one command.

```bash
git clone <repo> MySpace++ && cd MySpace++
docker compose up -d
docker compose exec myspace cc -help
docker compose exec myspace cc tiny "what is 2 + 2"
```

Add the **Studio** profile to get the Streamlit apps too (Wardrobe
background-removal + try-on + product mockup + image-to-3D, DAG canvas,
YouTube cutter):

```bash
docker compose --profile studio up -d --build
# Then in a browser:
#   http://localhost:8510   Wardrobe Studio
#   http://localhost:8501   DAG canvas (Models DAG Studio)
#   http://localhost:8511   YouTube cutter
```

See `docker-compose.yml` for volume mounts and env overrides.

### Option B — Nix (NixOS, macOS with nix, anywhere with the nix installer)

```bash
NIXPKGS_ALLOW_UNFREE=1 nix run --impure github:zero2onez/MySpace-pp -- -help
```

Or from a local clone:

```bash
NIXPKGS_ALLOW_UNFREE=1 nix build --impure .#myspace
./result/bin/myspace -help
```

`NIXPKGS_ALLOW_UNFREE=1` is required because the LICENSE is proprietary
(see below). Nix refuses non-OSI licenses by default — that's a feature.

### Option C — Bare-metal Linux/macOS install

```bash
git clone <repo> MySpace++ && cd MySpace++
./install.sh               # installs to ~/.local — no sudo
myspace -help              # if ~/.local/bin is on your PATH
```

`install.sh` detects your package manager (apt/dnf/pacman/zypper/apk/brew)
and tells you the exact command to install missing deps.

### Option D — Windows (container-only for v1)

```powershell
git clone <repo> MySpace++ ; cd MySpace++
.\install.ps1              # requires Docker Desktop
myspace -help              # after adding %USERPROFILE%\bin to PATH
```

### Option E — Repo checkout (zero install, for hacking)

```bash
git clone <repo> MySpace++ && cd MySpace++
./core/cc -help
./core/tests/smoke.sh
```

See `docs/PORTABILITY.md` for the full OS matrix and known gotchas.

---

## Quick start

```bash
# In any project dir
cd ~/my-project
myspace -setup                       # discovers venv/repo/entrypoints
myspace scope                        # one-line scope summary
myspace tiny "what is 2 + 2"         # deterministic local-model call
myspace -context                     # dump everything cc knows about cwd
```

That's the entire surface for Phase 0/1/2. Subcommands documented in
`myspace -help`. The local model defaults to `qwen2.5-coder:1.5b` — change
with `CC_TINY_MODEL=qwen2.5-coder:7b`.

---

## How it's different from other agent frameworks

| Framework | Default model | State | Determinism contract | Cross-terminal coord |
|---|---|---|---|---|
| LangChain | frontier | RAM | none | none |
| AutoGen | frontier | RAM | none | none |
| Claude Code | frontier | session file | per-session | none |
| **MySpace++** | **local (ollama)** | **sqlite** | **temp=0+seed+sha256 cache** | **agents table** |

The honest pitch: most agent flows don't need a frontier model. They need
*reproducibility*, *traceability*, and *coordination*. Frontier models
are the escalation, not the entry point.

---

## Studio (DAG canvas + Wardrobe + YouTube cutter)

`studio/` ships a set of [Streamlit](https://streamlit.io) apps that drive
the model graph visually. Built on top of the same opcode taxonomy as the
core substrate, but with a node-based canvas and a Wardrobe vertical for
non-technical use cases (digital clothing previews, product mockups,
image-to-3D).

```bash
# After install.sh: launchable from anywhere
myspace -wardrobe        # http://localhost:8510 — cutout, try-on, mockup, 3D
myspace -studio          # http://localhost:8501 — full DAG canvas
myspace -yt-cut          # http://localhost:8511 — YouTube clip extractor
```

The studio is **friend-installable end-to-end**: clone the repo, run
`./install.sh` (Linux/Mac) or `./install.ps1` (Windows), open the
printed URL. First launch creates a Python venv inside `studio/` — takes
~2 minutes, then every subsequent launch is instant.

Studio docs:
- `studio/docs/DAG.md` — type graph (13 tools + 12 models + 1 lora)
- `studio/docs/DAG-GUI.md` — chain enumeration + UX spec
- `studio/docs/DAG-FLOW.md` — deterministic deck-predictor flows

### Share GPU access with friends (SSH + IP-bind auth)

The studio supports a friend-scoped access model: SSH port-forward grants
on the network layer + a per-user IP-binding gate on the app layer. See
`studio/auth/README.md` for the full threat model. TL;DR:

```bash
# Tom's side — onboard a friend whose pubkey he received
cc -auth-ssh add Jamie ~/Downloads/jamie.pub
cc -auth-ssh share Jamie     # prints the SSH command Jamie should run

# Optional: add a new friend not in the default seed list
cc -auth-grant Mike

# Audit
cc -auth-list                # rows + IP-binding state
cc -auth-status              # one-line counts

# Revoke
cc -auth-revoke Jamie
cc -auth-ssh revoke Jamie
```

Default whitelist: `localhost`, `Jamie`, `Bronco`, `Pete`, `Ashley`, plus a
`friends@Tmail.com` solo email row. Same password (`"passwd"`) for all
four named friends; the strong factor is **SSH key + sticky IP binding**,
not the password.

---

## Documentation

- `planning/README.md` — thesis, why it exists, what done looks like
- `planning/PLAN.md` — Phase 0–5 roadmap + repo layout
- `planning/ARCHITECTURE.md` — three-layer model, determinism contract, DONE protocol
- `planning/OPEN_QUESTIONS.md` — decision log, deferred questions
- `planning/LICENSE.draft.md` — license text and rationale

---

## License

**Proprietary. Commercial use requires a paid written license.**

You may read the source and run the code for personal evaluation.
You may not redistribute, fork commercially, host for paying users,
or train ML models on the source. See `LICENSE` for full terms.

For commercial licensing inquiries, contact Tom Lee (Zero2oneZ).
