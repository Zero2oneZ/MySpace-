# freetier_public — production deploy bundle

The two public-facing MySpace++ servers and the Caddy fragment that fronts
them with TLS, packaged for the DO droplet at `159.89.181.146`.

## What gets deployed

| Component | Bind | Purpose |
|-----------|------|---------|
| `mspc-callback.service` | `127.0.0.1:8540` | freetier callback server — terms/policies pages, acceptance recording, token issuance. Host-header routed: `trollz.fun` -> `/terms/*`, `GentlyOS.io` -> `/endpoint/freetier/*`. |
| `mspc-model-api.service` | `127.0.0.1:8521` | proprietary unified model API. `POST /v1/text/generate`, `POST /v1/code/generate`, `POST /v1/embed`. Bearer-token gated against the freetier registry. |
| `Caddyfile.droplet` | `:80`, `:443` | reverse proxy with auto Let's Encrypt for both domains. Routes by host + path to the two loopback servers. |

Both Python servers bind on `127.0.0.1` only. Caddy is the only public surface.

## Files in this directory

| File | Purpose |
|------|---------|
| `Caddyfile.droplet` | Caddy reverse-proxy fragment (drops into `/etc/caddy/Caddyfile.d/`) |
| `mspc-callback.service` | systemd unit for freetier_callback (`:8540`) |
| `mspc-model-api.service` | systemd unit for model_api (`:8521`) |
| `deploy.sh` | rsync + ssh deploy script. **Defaults to dry-run.** |
| `README.md` | this file |

## Prerequisites (before running deploy.sh)

1. **DNS A records** pointing at `159.89.181.146`:
   - `trollz.fun` -> `159.89.181.146`
   - `www.trollz.fun` -> `159.89.181.146`
   - `GentlyOS.io` -> `159.89.181.146`
   - `www.GentlyOS.io` -> `159.89.181.146`

2. **.env on laptop** at `/data/Projects/MySpace++/.env` containing every key
   the callback + model_api need (`claude_guest`, `client_api`, deepseek keys,
   HF router keys, etc.). Mirror to `/data/Projects/gently/.env` per project
   policy. The deploy ships this file to the droplet with mode 600.

3. **Caddy installed on droplet** (`apt-get install caddy`). The deploy script
   warns and continues if Caddy is missing; without it the Python servers are
   unreachable from the internet.

4. **SSH key** that authorizes `root@159.89.181.146`. The script auto-detects
   `~/.ssh/id_ed25519`, falls back to `id_rsa`, or override with
   `SSH_KEY=/path/to/key ./deploy.sh`.

5. **Firewall** — DO cloud firewall + ufw must allow `:80` and `:443`. Ports
   `8540` / `8521` must **not** be exposed; they're loopback only.

## How to deploy

```bash
cd /data/Projects/MySpace++/studio/deploy/freetier_public/

# Dry-run first (default — prints rsync actions, makes no changes):
./deploy.sh

# Real deploy:
DRY_RUN=0 ./deploy.sh
```

On real deploy the script:
1. SSHes to the droplet
2. Creates the `mspc` unprivileged user (if missing)
3. Creates `/opt/mspc-public/{freetier_callback,lib,auth,agent_defs,logs}`
4. rsyncs source trees + .env (mode 600) + units + Caddyfile
5. Installs both systemd units, daemon-reload, enable, restart
6. Drops the Caddy fragment, validates, reloads caddy
7. Smoke-tests both `/healthz` endpoints via loopback on the droplet

## Cert acquisition

Caddy handles TLS automatically via Let's Encrypt the first time a request
hits each domain. No manual `certbot` step. The Caddyfile uses bare
`trollz.fun, www.trollz.fun { ... }` blocks which trigger ACME on first load.

If certs fail to issue, common causes:
- DNS not yet propagated (`dig trollz.fun`)
- Port 80 not reachable (Let's Encrypt HTTP-01 needs `:80`)
- Rate limit hit (5 certs / domain / week on production endpoint)

## How to test after deploy

```bash
# Public TLS surface — both domains:
curl -i https://trollz.fun/terms/
curl -i https://trollz.fun/healthz
curl -i https://GentlyOS.io/endpoint/freetier/terms/
curl -i https://GentlyOS.io/healthz

# model_api (requires Bearer token from freetier registry):
curl -X POST https://trollz.fun/v1/text/generate \
  -H "Authorization: Bearer <freetier_token>" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Hello","max_tokens":32}'

# On the droplet itself (loopback, no TLS):
ssh root@159.89.181.146 'curl -s http://127.0.0.1:8540/healthz'
ssh root@159.89.181.146 'curl -s http://127.0.0.1:8521/v1/healthz'

# journalctl tails:
ssh root@159.89.181.146 'journalctl -u mspc-callback -f'
ssh root@159.89.181.146 'journalctl -u mspc-model-api -f'
ssh root@159.89.181.146 'tail -f /var/log/caddy/mspc-trollz.log'
```

## Rollback

```bash
# Stop services on the droplet:
ssh root@159.89.181.146 'systemctl stop mspc-callback mspc-model-api'

# (Optional) disable to prevent auto-start after reboot:
ssh root@159.89.181.146 'systemctl disable mspc-callback mspc-model-api'

# Restore a previous /opt/mspc-public/ from snapshot (if you took one):
ssh root@159.89.181.146 'mv /opt/mspc-public /opt/mspc-public.broken && \
                          mv /opt/mspc-public.prev /opt/mspc-public && \
                          systemctl restart mspc-callback mspc-model-api'

# Or roll the whole droplet back via DO snapshot UI (if you took one before deploy).
```

Caddy will continue serving (it's a separate unit) but will return upstream
errors until the loopback servers are healthy again. To fully take the public
surface offline, also reload Caddy with a stripped config (or stop caddy).

## Constraints baked in

- Both Python servers bind on `127.0.0.1` only — never publicly exposed.
- `mspc` runs as an unprivileged system user (`User=mspc Group=mspc`).
- `.env` is mode 600 on the droplet, owned by `mspc:mspc`.
- `keys.sqlite` is **excluded** from the rsync — the registry is host-scoped
  per the salted-token rule. The droplet creates its own DB on first run, and
  friends register against the droplet's host fingerprint separately.
- `agent_defs/` ships as a read-only audit snapshot — not loaded at runtime.
- `deploy.sh` defaults to `DRY_RUN=1` to prevent accidental smoke-run damage.
