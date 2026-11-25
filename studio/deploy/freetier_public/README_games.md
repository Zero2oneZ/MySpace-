# Godot Instant Games — static hosting on `/play/*`

Companion to [`README.md`](README.md). Covers the static-file path for
serving Godot Web HTML5 builds at:

- `https://trollz.fun/play/<game_slug>/`
- `https://GentlyOS.io/play/<game_slug>/`

Both surfaces are FB Instant Games compliant (COEP/COOP/CORP headers + CSP
`frame-ancestors` allowing `facebook.com` and `messenger.com`), which lets
the same build run standalone in a browser *and* embedded as an Instant
Game inside Facebook.

## Files involved

| File | Purpose |
|------|---------|
| `Caddyfile.droplet` | Adds `/play/*` `handle_path` blocks to **both** domains, plus the shared `(games_headers)` and `(games_mime)` snippets. |
| `sync-games-build.sh` | Rsyncs a local Godot Web export to the droplet at `/opt/mspc-public/games/<game_slug>/`. **Defaults to dry-run.** Does not touch systemd or Caddy. |
| `README_games.md` | This file. |

The `deploy.sh` itself is untouched — it already ships the updated
`Caddyfile.droplet`, so after the next `DRY_RUN=0 ./deploy.sh` (or a manual
Caddy reload, see below) the `/play/*` routes go live.

## How to publish a new build

### 1. Build it locally with Godot

Use the project's `cc` wrapper, which knows the export-preset name:

```bash
cc godot-export web_instant_games
```

This writes the export to:

```
/data/Projects/MySpace++/studio/godot/builds/web_instant_games/
  index.html
  myspace_pp.wasm        # name varies by export preset
  myspace_pp.pck
  myspace_pp.js
  ... (optional: audio worklet, splash, icon)
```

A valid Godot 4 web export MUST include `index.html`. The sync script
spot-checks for `*.pck` and `*.wasm` and warns (without failing) if either
is missing.

### 2. Dry-run the sync

```bash
cd /data/Projects/MySpace++/studio/deploy/freetier_public/

# Defaults: game_slug=myspace_pp, build=studio/godot/builds/web_instant_games
bash sync-games-build.sh
# or be explicit:
bash sync-games-build.sh myspace_pp /data/Projects/MySpace++/studio/godot/builds/web_instant_games
```

Pre-flight checks (all run in dry-run too):

1. `game_slug` matches `^[a-z0-9_-]+$` (no `..` or `/`)
2. `BUILD_DIR` exists and contains `index.html`
3. `rsync` installed locally
4. Droplet reachable via SSH (BatchMode — uses the same key precedence as
   `deploy.sh`: `$SSH_KEY` env, then `~/.ssh/id_ed25519`, then `id_rsa`)

Pre-flight failures print a red `FAIL: ...` and exit 1 *before* any
network call to the droplet.

### 3. Real push

```bash
DRY_RUN=0 bash sync-games-build.sh myspace_pp
```

The script:

1. Re-runs pre-flight (idempotent)
2. SSHes to the droplet, creates `/opt/mspc-public/games/<game_slug>/`
3. Rsyncs the build contents into that dir (`--delete-after`)
4. `chown -R mspc:mspc` and sets `755` on dirs, `644` on files

Caddy is already routing `/play/*` to `/opt/mspc-public/games/`, so the
new build is live as soon as rsync finishes.

## DNS prereqs

Already done — both `trollz.fun` and `GentlyOS.io` have A records pointing
at the droplet at `159.89.181.146`. See [`README.md`](README.md) for the
DNS checklist.

If you add a brand-new domain in the future, also update its A record
*and* extend `Caddyfile.droplet` (don't reuse the existing snippets unless
they truly fit — FB Instant Games CSP is specifically scoped to Facebook).

## Caddy auto-reload after a Caddyfile change

When `deploy.sh` ships an updated `Caddyfile.droplet` it calls
`caddy validate && systemctl reload caddy` on the droplet. If you only
edit the Caddyfile (no source changes), you can manually reload without
re-running the whole deploy:

```bash
# Edit /etc/caddy/Caddyfile.d/mspc-freetier-public on the droplet,
# then validate + reload:
ssh root@159.89.181.146 \
    'caddy validate --config /etc/caddy/Caddyfile && \
     systemctl reload caddy'
```

`caddy reload` is graceful — in-flight requests finish on the old config.

## FB Instant Games headers — what each one buys you

| Header | Value | Why |
|---|---|---|
| `Cross-Origin-Embedder-Policy` | `require-corp` | Mandatory for `SharedArrayBuffer` (Godot 4 threaded WASM needs it). |
| `Cross-Origin-Opener-Policy`   | `same-origin` | Pair with COEP to satisfy the "cross-origin isolated" precondition. |
| `Cross-Origin-Resource-Policy` | `cross-origin` | Lets Facebook fetch our assets from inside its iframe. |
| `Content-Security-Policy: frame-ancestors` | `'self' https://www.facebook.com https://*.facebook.com https://www.messenger.com` | Whitelists who is allowed to iframe us. Without this, `X-Frame-Options: SAMEORIGIN` from Caddy defaults would block FB. |
| `Content-Type: application/wasm` | (override on `*.wasm`) | Required for `WebAssembly.instantiateStreaming`. |

## Manual rollback

If a freshly-pushed build is broken and you need the previous one back
*right now*, but you don't have a snapshot:

```bash
# 1. Move the broken build aside (instant — Caddy will start 404ing /play/<slug>/)
ssh root@159.89.181.146 \
    'mv /opt/mspc-public/games/myspace_pp{,.broken}'

# 2. Reload Caddy just to be safe (optional — file_server picks up changes live)
ssh root@159.89.181.146 'systemctl reload caddy'

# 3. Re-push a known-good build from local:
DRY_RUN=0 bash sync-games-build.sh myspace_pp /path/to/known/good/build
```

To take the games surface fully offline (e.g. while debugging), comment
the `handle_path /play/*` blocks in the Caddyfile and `systemctl reload
caddy`. The other freetier routes (`/terms/*`, `/v1/*`, `/healthz`,
`/endpoint/freetier/*`) keep serving unchanged.

## What this script does NOT do

- Does not start, stop, or modify any systemd unit.
- Does not touch the Caddyfile or reload Caddy (that already happened via
  `deploy.sh`; Caddy serves whatever files are under `/opt/mspc-public/games/`).
- Does not register the game with the Facebook Instant Games platform —
  that's the `facebook_games_sdk` connector's job (see
  `studio/assets/_agents/agent_defs/vm_mspc_001.agents.agent_defs.facebook_games_sdk.active.json`).
- Does not export the Godot project. Run `cc godot-export web_instant_games`
  first.
