# Portability — supported OS matrix

| OS                | Install path        | Status            | Notes                                          |
|-------------------|---------------------|-------------------|------------------------------------------------|
| NixOS             | `nix run .#myspace` | **first-class**   | Reference platform; flake is the source of truth |
| Linux (other)     | `./install.sh`      | **first-class**   | apt/dnf/pacman/zypper/apk detected             |
| macOS (Apple Silicon) | `./install.sh`  | **first-class**   | brew required for sqlite/coreutils             |
| macOS (Intel)     | `./install.sh`      | **first-class**   | same as Apple Silicon                          |
| Windows 10/11     | `.\install.ps1`     | **container-only**| Docker Desktop required (per OPEN_QUESTIONS Q5) |
| WSL2              | `./install.sh`      | **first-class**   | Use the Linux path inside WSL                  |
| Anywhere else     | `docker build .`    | **container-only**| The Dockerfile is the universal escape hatch  |

## What "first-class" means

The smoke test suite passes natively on the OS. Determinism test passes
if ollama is running locally. You can `myspace -setup` in any directory
and have it work without any other prerequisites beyond what `install.sh`
checks for.

## What "container-only" means

There is no native install. The installer builds the Dockerfile and
drops a wrapper that does `docker run` on every invocation. There's
a per-call container startup overhead (~200 ms on a recent laptop, more
on Windows because of Docker Desktop's VM). Tradeoff: zero porting work,
identical behavior everywhere.

## Why these choices

**Bash for the substrate** — bash is on every Linux, macOS ships it,
NixOS provides it, WSL has it. The one place bash is hostile is native
Windows, and we punt that to Docker. The alternative (rewrite the
substrate in Python or Go) costs weeks of work and removes the
"one bash file you can read top-to-bottom" property that makes cc
debuggable.

**SQLite for state** — every OS ships with sqlite, every Python ships
with the sqlite3 module. No daemon, no network bind, no migration tool
required. The DB file is portable across OSes — copy `.cc/local.db`
from a Linux machine to a Mac and it just works.

**Ollama for the local model** — has builds for Linux/macOS/Windows
natively, plus Docker. The `model_call` HTTP client in cc doesn't care
which is running, only that `localhost:11434/api/generate` answers.

## Known cross-OS gotchas (live list)

1. **macOS `sha256sum`** — not present by default. `install.sh` checks
   for it and tells you to `brew install coreutils`. The Nix flake
   bundles it via `pkgs.coreutils`.

2. **macOS `readlink -f`** — the BSD readlink doesn't support `-f`.
   The cc script's install-root discovery falls back to a Python
   one-liner when `readlink -f` fails, so this is handled.

3. **Alpine Linux `bash`** — Alpine ships ash, not bash. `apk add bash`
   is required. The Dockerfile uses debian-slim specifically to avoid
   this when building the image; users who install on Alpine bare-metal
   need to add bash themselves.

4. **NixOS Python `/usr/bin/env python3`** — works because of the
   built-in env shim, but some scripts that hardcode `/usr/bin/python3`
   would break. cc uses `python3` via `command -v`, which is correct.

5. **Windows line endings** — git on Windows can auto-convert LF to
   CRLF for `.sh` files, which then fail to execute inside the
   container. The repo includes a `.gitattributes` (TODO — phase 1.1)
   that pins all `.sh`/`cc` files to LF.

6. **WSL `/proc/sys/kernel/random/uuid`** — exists in WSL2, doesn't
   in WSL1. UUID generation has a 4-level fallback chain so this is
   handled.

## What we don't support

- **DOS/Win9x-era Windows** — obviously
- **OpenBSD** — should work via install.sh, untested
- **Solaris/Illumos** — untested, probably broken (no bashisms?
   needs investigation)
- **Termux (Android)** — bash is there, sqlite is there, ollama is
   not — could work for the substrate-only subset, untested

## How to add an OS

1. Run `core/tests/smoke.sh` on the target OS. Report what fails.
2. If `install.sh`'s package-manager detection doesn't know the OS's
   package manager, add a branch to `detect_pm` and `pkg_for_bin`.
3. If a missing OS-specific binary substitution is needed, add it to
   the cc script with a clearly-flagged fallback chain (see
   `CC_AGENT_UUID` generation for the pattern).
4. Add a row to the matrix above.

## Test cadence

- **NixOS (z21)** — every commit. `nix flake check` runs the smoke
  suite.
- **Linux (Debian-slim)** — every commit. Docker build runs the smoke
  suite inside the container.
- **macOS** — manual, pre-tag. No GH Actions runner allocated yet.
- **Windows** — manual, pre-tag. Container build is what we verify.
