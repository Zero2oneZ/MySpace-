# studio/assets/ — Unified Asset Root

> **THE ONE REAL FILE ROOT.** Everything else is symlinks.
> **THE FILENAME IS THE VARIABLE. THE HOLDER IS CONSTANT.**

This directory is the canonical `_local_assets` equivalent from `VM-CONSOLIDATION.md`. All engines (Godot, Defold), all infrastructure (MCP, GPU, network, agents, web, comms), and all projects symlink into here. The 3-layer architecture is:

- **Layer 0 (Platform Root):** `_global/`, `_inference/`, `_godot/`, `_meta/`, `_compute/`, `_network/`, `_agents/`, `_web/`, `_comms/` — shared across all projects
- **Layer 1 (Tenant/Project):** `projects/<name>/` — per-project overrides and builds
- **Layer 2 (Client Workspace):** `_factory/clients/<tenant>/` — software produced by the factory for tenants

**Plus the SaaS domains:**
- **Tenancy:** `_tenants/`, `_users/`, `_billing/` — RBAC, memberships, subscriptions
- **Factory:** `_factory/` — templates → builds → deployments → client workspaces

This is the architecture for selling software that produces software that sells business to clients.

---

## The Golden Rule

```
DIRECTORY = CONSTANT HOLDER          (never changes)
FILENAME  = VARIABLE                 (encodes all state)
```

The path tells you *what kind of thing* it is. The filename tells you *which specific thing, its state, version, and origin*.

---

## Canonical Naming Convention

Adapted from `VM-CONSOLIDATION.md §2`:

```
{symbol}{array}.{domain}.{category}.{name}.{state}.{version}.{ext}

# symbol    = vm_id derived from sha256(cwd + agent_uuid)
# array     = slot/index or label inside this VM [0], [gpu_0], [run_42]
# domain    = _global | _inference | _godot | _compute | _network | _agents | _web | _comms
# category  = subdir under domain (jobs, routers, mcp_servers, etc.)
# name      = descriptive identifier (rtx3090ti, droplet_main, gently_watchdog)
# state     = active | pending | failed | online | offline | completed
# version   = v0, run_42, wg0, 3100 (port), or git branch
# ext       = json | bb | rs | py | gd | lua | fbx | npy | glsl
```

### Examples across every domain

```
# COMPUTE — GPU profile
vm_mspc_001.compute.gpu_profiles.rtx3090ti.24gb.v0.json

# COMPUTE — queued inference job
vm_mspc_001.compute.jobs.infer_depth_pro.run_42.pending.json

# NETWORK — WireGuard peer
vm_mspc_001.network.peers.droplet_z21_tunnel.wg0.json

# AGENTS — MCP server
vm_mspc_001.agents.mcp_servers.gently_watchdog.3100.json

# AGENTS — Inference chain
vm_mspc_001.agents.inference_chains.run_20_avatar_pipeline.active.json

# WEB — Livestream config
vm_mspc_001.web.streams.livestream_001.active.json

# COMMS — Permission registry
vm_mspc_001.comms.permissions.friend_access_registry.active.json

# GLOBAL — Avatar mesh
vm_mspc_001.global.models.avatars.N001.v0.fbx

# GLOBAL — Motion clip
vm_mspc_001.global.animations.dance.Northern_Soul_Spin.v0.fbx

# INFERENCE — Cached depth map
vm_mspc_001.inference.cache.depth_map.a3f7.v0.npy

# TENANTS — Tenant configuration
vm_mspc_001.tenants.configs.acme_corp.active.json

# TENANTS — Membership grant
vm_mspc_001.tenants.memberships.acme_corp.user_123.admin.active.json

# USERS — User profile
vm_mspc_001.users.profiles.tom_lee.active.json

# USERS — Role definition
vm_mspc_001.users.roles.tenant_admin.active.json

# USERS — Permission grant
vm_mspc_001.users.grants.user_123.tenant_acme.project_walk_v1.write.active.json

# BILLING — Subscription plan
vm_mspc_001.billing.plans.enterprise_monthly.v0.json

# BILLING — Active subscription
vm_mspc_001.billing.subscriptions.acme_corp.plan_enterprise_monthly.active.json

# BILLING — Usage report
vm_mspc_001.billing.usage.acme_corp.gpu_hours.may_2026.json

# FACTORY — Template definition
vm_mspc_001.factory.templates.realestate_walkthrough.v0.json

# FACTORY — Build result
vm_mspc_001.factory.builds.acme_dashboard.run_99.completed.json

# FACTORY — Deployment
vm_mspc_001.factory.deployments.acme_walk_v1.prod.active.json
```

**Why this matters:** A simple `find` query tells you everything:

```bash
# All active MCP servers
find studio/assets/_agents/mcp_servers/ -name "*.active.json"

# All pending jobs
find studio/assets/_compute/jobs/ -name "*.pending.json"

# All failed jobs in the last hour
find studio/assets/_compute/jobs/failed/ -name "*.json" -mtime -0.04

# Everything on droplet 159.89.181.146
find studio/assets/ -name "*159_89_181_146*"

# Everything related to Run #20
find studio/assets/ -name "*run_20*"
```

---

## Full Tree

```
studio/
├── assets/                           ← THE ONE REAL FILE ROOT
│   ├── README.md                     ← This file
│   │
│   ├── _global/                      ← Layer 0: MEDIA + DATA (shared)
│   │   ├── models/
│   │   │   ├── avatars/              → N001.fbx (791 KB — the MySpace++ avatar)
│   │   │   ├── scenes/               → Shared 3D rooms, worlds
│   │   │   └── primitives/           → Cubes, spheres, grid helpers
│   │   ├── textures/
│   │   │   ├── tile_skin/            → N001 tile-decomposed textures
│   │   │   ├── environment/          → HDRI, skyboxes
│   │   │   └── ui/                   → MUI theme atlases
│   │   ├── animations/               → 228 FBX motion library
│   │   │   ├── dance/
│   │   │   ├── walk/
│   │   │   ├── combat/
│   │   │   ├── idle/
│   │   │   ├── gesture/
│   │   │   ├── sport/
│   │   │   ├── action/
│   │   │   ├── sit/
│   │   │   ├── reaction/
│   │   │   └── misc/
│   │   ├── shaders/
│   │   │   ├── spatial_depth.glsl
│   │   │   ├── normal_blend.glsl
│   │   │   └── skin_tile.gdshader
│   │   ├── audio/
│   │   │   ├── sfx/
│   │   │   ├── music/
│   │   │   └── tts_output/           → F5-TTS / XTTS-v2 rendered clips
│   │   ├── fonts/
│   │   └── data/
│   │       ├── vm_registry.json
│   │       ├── task_chains.json
│   │       ├── sym_index.json
│   │       └── motion_index.json
│   │
│   ├── _inference/                   ← Layer 0: MODEL WEIGHTS + ARTIFACTS
│   │   ├── weights/
│   │   │   ├── depth/
│   │   │   │   ├── apple_depth_pro/
│   │   │   │   └── marigold_normals/
│   │   │   ├── pose/
│   │   │   │   └── mediapipe_pose/
│   │   │   ├── video/
│   │   │   │   └── longcat_video_avatar/
│   │   │   ├── faceswap/
│   │   │   │   └── flux2_klein/
│   │   │   └── llm/
│   │   │       └── kimi_k2_6/
│   │   ├── cache/
│   │   │   └── <crystal_prefix>/
│   │   │       ├── depth_map.npy
│   │   │       ├── pose_sequence.json
│   │   │       └── frame_*.png
│   │   └── configs/
│   │       └── model_cards.json
│   │
│   ├── _compute/                     ← Layer 0: GPU + JOBS + QUEUES
│   │   ├── gpu_profiles/             → rtx3090ti.24gb.v0.json
│   │   ├── jobs/
│   │   │   ├── active/               → infer_depth_pro.run_42.pending.json
│   │   │   ├── completed/            → (moved here on success)
│   │   │   └── failed/               → (moved here on failure)
│   │   ├── queues/                   → inference_priority.default.json
│   │   ├── workers/                  → droplet_159_89_181_146.online.json
│   │   └── schedules/                → cron-style job schedules
│   │
│   ├── _network/                     ← Layer 0: ROUTERS + DEVICES + PEERS
│   │   ├── routers/                  → droplet_main.active.json
│   │   ├── devices/                  → z21_dual_rtx3090ti.active.json
│   │   ├── peers/                    → droplet_z21_tunnel.wg0.json
│   │   ├── configs/                  → wireguard, caddy configs
│   │   ├── tunnels/                  → VPN tunnel state
│   │   └── traffic_logs/             → (ephemeral, .gitignored)
│   │
│   ├── _agents/                      ← Layer 0: MCP + INFERENCE + AGENTS
│   │   ├── mcp_servers/              → gently_watchdog.3100.json
│   │   ├── inference_chains/         → run_20_avatar_pipeline.active.json
│   │   ├── agent_defs/               → infra_orchestrator.active.json
│   │   ├── prompts/                  → system prompts, task templates
│   │   └── orchestrator/             → agent coordination state
│   │
│   ├── _web/                         ← Layer 0: WEBSITES + LIVESTREAMS
│   │   ├── sites/                    → myspace_studio.active.json
│   │   ├── streams/                  → livestream_001.active.json
│   │   ├── html/                     → flat HTML (HTMX + salvo)
│   │   ├── js/                       → minimal JS (no framework)
│   │   ├── css/                      → MUI theme stylesheets
│   │   └── static/                   → images, icons, favicon
│   │
│   ├── _comms/                       ← Layer 0: PERMISSIONS + MESSAGES
│   │   ├── permissions/              → friend_access_registry.active.json
│   │   ├── messages/                 → inter_session_protocol.active.json
│   │   ├── auth/                     → SSH keys, tokens, salted registry
│   │   ├── tokens/                   → per-host friend tokens
│   │   └── webhooks/                 → external service callbacks
│   │
│   ├── _tenants/                     ← Layer 0: TENANT ORGS + MEMBERSHIPS
│   │   ├── configs/                  → acme_corp.active.json
│   │   ├── memberships/              → acme_corp.user_123.admin.active.json
│   │   └── hierarchies/              → parent/child tenant relationships
│   │
│   ├── _users/                       ← Layer 0: USER ACCOUNTS + RBAC
│   │   ├── profiles/                 → tom_lee.active.json
│   │   ├── roles/                    → tenant_admin.active.json
│   │   ├── sessions/                 → active login sessions
│   │   └── grants/                 → user_123.project_walk_v1.write.active.json
│   │
│   ├── _billing/                     ← Layer 0: PLANS + SUBSCRIPTIONS + USAGE
│   │   ├── plans/                    → enterprise_monthly.v0.json
│   │   ├── subscriptions/            → acme_corp.plan_enterprise_monthly.active.json
│   │   ├── usage/                    → acme_corp.gpu_hours.may_2026.json
│   │   └── invoices/                 → generated PDF + metadata
│   │
│   ├── _factory/                     ← Layer 0: SOFTWARE FACTORY
│   │   ├── templates/                → realestate_walkthrough.v0.json
│   │   ├── builds/
│   │   │   ├── active/               → currently running builds
│   │   │   ├── completed/            → successful builds
│   │   │   └── failed/               → failed build logs
│   │   ├── deployments/
│   │   │   ├── active/               → currently deployed instances
│   │   │   └── archived/             → old deployments
│   │   └── clients/                  ← LAYER 2: PRODUCED WORKSPACES
│   │       └── acme_corp/
│   │           ├── workspace.manifest.json
│   │           ├── assets/             → tenant-specific media
│   │           ├── projects/           → tenant's Godot/Defold projects
│   │           ├── users/              → tenant's end users (L2)
│   │           ├── permissions/        → tenant's internal RBAC
│   │           └── billing/            → tenant's internal billing (if they charge L2)
│   │
│   ├── _godot/                       ← Layer 0: GODOT ENGINE + SHARED
│   │   ├── engine/
│   │   │   ├── standard/             → Godot 4.6.3 standard binary
│   │   │   └── mono/                 → Godot 4.6.3 mono/C# binary
│   │   ├── templates/
│   │   │   └── blank_project/        → Minimal scaffold
│   │   └── addons/
│   │       └── mspc_bridge/          → Shared GDExtension wrapper
│   │
│   ├── _meta/                        ← Layer 0: META-BUILD LAYER
│   │   ├── build_scripts/
│   │   │   ├── build_gdext.sh        → Compile C++ extension
│   │   │   ├── build_project.sh      → Pack project for export
│   │   │   └── sync_assets.py        → Sync _global/ → projects/
│   │   ├── templates/
│   │   │   ├── vm_card.template.txt
│   │   │   └── project.manifest.json
│   │   └── registry/
│   │       ├── asset_registry.json   → Every asset: id, path, crystal, type
│   │       ├── project_index.json    → All projects + manifests
│   │       └── infrastructure_registry.json → All MCP, GPU, network, agents
│   │
│   └── projects/                     ← Layer 1: PER-PROJECT
│       ├── default/                  → Built-in default project
│       │   ├── project.manifest.json
│       │   ├── scenes/
│       │   ├── scripts/
│       │   ├── resources/
│       │   └── exports/
│       │
│       └── <your-project>/           → Created via cc -project-init <name>
│           ├── project.manifest.json
│           ├── scenes/
│           ├── scripts/
│           ├── resources/
│           └── exports/
│
├── godot/
│   ├── standard → ../assets/_godot/engine/standard
│   ├── mono → ../assets/_godot/engine/mono
│   └── project/
│       ├── project.godot
│       ├── src/                      → GDScript (in repo)
│       ├── cpp/                      → C++ GDExtension (in repo)
│       └── assets → ../../assets/projects/default
│
└── defold/
    └── walkthrough/
        ├── game.project
        ├── scripts/                    → Lua (in repo)
        └── assets → ../../assets/projects/default
```

---

## The Three-Level Hierarchy

This architecture supports selling **software that produces software that sells business to clients**:

```
L0 — PLATFORM (Zero2oneZ / MySpace++)
  │   We run the factory. We own _factory/templates/ and the build pipeline.
  │   We manage _tenants/, _users/, _billing/, _compute/, _network/.
  │   We set pricing, quotas, and global RBAC.
  │
  ├── L1 — TENANTS / CLIENTS (Businesses who subscribe)
  │   │   Acme Corp pays for Enterprise tier. They get a workspace.
  │   │   They pick templates, configure them, and deploy.
  │   │   They manage their own users, permissions, and (optionally) billing.
  │   │
  │   ├── L2 — END USERS (Users of the software L1 builds)
  │   │   Acme Corp's customers tour the 3D walkthrough.
  │   │   They log in via Acme's branded domain.
  │   │   Their data lives in _factory/clients/acme_corp/users/
```

**Key insight:** The same architecture recurses. `_factory/clients/acme_corp/` is a mini `studio/assets/` scoped to that tenant. If Acme wants to white-label and resell, their workspace gets its own `_factory/` directory.

---

## RBAC: Filename-Based Permission Grants

No permission table. No SQL JOINs. One file per grant:

```json
// _users/grants/user_123.tenant_acme.project_walk_v1.write.active.json
{
  "grant_id": "grt_001",
  "user_id": "usr_123",
  "tenant_id": "tnt_acme_corp",
  "resource_type": "project",
  "resource_id": "proj_walkthrough_v1",
  "actions": ["read", "write", "deploy"],
  "granted_by": "usr_tom_lee_001"
}
```

**Querying permissions without a database:**

```bash
# What can user 123 do?
find _users/grants/ -name "*user_123*.json" | xargs jq '.actions'

# Who has write access to project walk_v1?
find _users/grants/ -name "*project_walk_v1.write*.json"

# All admins in tenant acme_corp
find _tenants/memberships/ -name "*acme_corp*.admin.active.json"

# All permissions granted by Tom
find _users/grants/ -name "*granted_by_tom_lee*.json"
```

**Role inheritance:** Roles are JSON files in `_users/roles/`. A role lists its `inherits_from`. Resolution is done by reading the role file + all ancestors, then deduplicating permissions. No database recursion needed — it's just file reads.

---

## The Software Factory Pipeline

```
TEMPLATE (L0 creates this once)
  │
  ├── _factory/templates/realestate_walkthrough.v0.json
  │   Defines: engine, configurable params, source assets, license
  │
  CONFIGURE (L1 tenant customizes)
  │
  ├── Tenant picks template → fills config (brand_color, logo, room_count)
  │
  BUILD (factory runs)
  │
  ├── _factory/builds/active/*.json            → job queued
  ├── _factory/builds/completed/*.json           → output to _factory/clients/<tenant>/
  ├── _factory/builds/failed/*.json              → logs for debugging
  │
  DEPLOY (factory deploys)
  │
  ├── _factory/deployments/active/*.json         → live instance
  ├── Tenant gets custom domain: acme.zero2onez.studio
  │
  CLIENT WORKSPACE (L2 lives here)
  │
  ├── _factory/clients/acme_corp/
  │   ├── assets/          → tenant-specific media (their logo, their rooms)
  │   ├── projects/        → their Godot/Defold projects
  │   ├── users/           → their end users (L2 accounts)
  │   ├── permissions/     → their internal RBAC
  │   └── billing/         → their internal billing (if THEY charge L2)
```

**Every stage is a file move:**
- `template.v0.json` → `build.run_99.pending.json` → `build.run_99.completed.json` → `deployment.prod.active.json`
- No UPDATE statements. No state mutations. Just `mv` and `cp`.

---

## Multi-Tenancy Isolation

**Three isolation models supported:**

| Model | How it works | Use case |
|-------|-------------|----------|
| **Shared** | All tenants read `_global/` directly. No copies. | Common media (N001, generic animations) |
| **Symlinked** | Tenant workspace symlinks into `_global/`. No copies. | Templates that share engine binaries |
| **Copied** | Build step copies assets into `_factory/clients/<tenant>/`. Full isolation. | Custom branded assets, tenant-specific configs |

**Quotas enforced by filename inspection:**

```bash
# How many projects does acme_corp have?
find _factory/clients/acme_corp/projects/ -type d | wc -l

# How many users?
find _factory/clients/acme_corp/users/profiles/ -name "*.json" | wc -l

# GPU hours this month?
find _billing/usage/ -name "*acme_corp*$(date +%Y-%m)*.json" | xargs jq '.metrics.gpu_hours_used' | jq -s 'add'
```

The quota check is a `find` + `jq` pipeline. No counters table. No race conditions (files are append-only).

---

## How Self-Organization Works

### 1. Filename encodes everything

No database lookup needed. The filename IS the database:

```
vm_mspc_001.agents.mcp_servers.gently_watchdog.3100.json
│  │       │      │            │              │
│  │       │      │            │              └── port (variable)
│  │       │      │            └── name (variable)
│  │       │      └── category (constant holder)
│  │       └── domain (constant holder)
│  └── array slot (variable)
└── vm_id / symbol (variable)
```

### 2. State transitions by moving files

```bash
# Job lifecycle
mv _compute/jobs/active/*.pending.json _compute/jobs/active/*.running.json
mv _compute/jobs/active/*.running.json _compute/jobs/completed/
mv _compute/jobs/active/*.running.json _compute/jobs/failed/

# Device lifecycle
mv _network/devices/*.active.json _network/devices/*.offline.json

# Stream lifecycle
mv _web/streams/*.active.json _web/streams/*.ended.json
```

No UPDATE statements. No state tables. The filesystem IS the state machine.

### 3. Querying without a database

```bash
# What GPUs are online?
find _compute/gpu_profiles/ -name "*.active.json" | xargs cat | jq '.hardware.gpu'

# What's the droplet's router config?
cat _network/routers/*droplet_main*.json

# Which MCP servers are healthy?
find _agents/mcp_servers/ -name "*.active.json" -exec cat {} \; | jq '.last_healthcheck'

# All agents in the PLATFORM tier
cat _agents/agent_defs/*.json | jq 'select(.tier == "L0")'

# Everything tagged with "run_20"
find . -name "*run_20*" -type f
```

### 4. Cross-domain linking via crystal hash

Every JSON file contains a `crystal` field. The registry maps crystals to paths. A job references its input model by crystal, not by path:

```json
// In _compute/jobs/active/*.json
{
  "input_crystal": "a3f7c2d1",
  "model": "apple_DepthPro"
}
```

The build script resolves:
```python
# sync_assets.py
crystal_to_path = {
    "a3f7c2d1": "_inference/weights/depth/apple_depth_pro/...",
}
```

---

## Integration with VM-CONSOLIDATION.md

Every file has a VM card in `_meta/registry/`:

```
ASSET_ID: vm_mspc_001.compute.gpu_profiles.rtx3090ti.24gb.v0.json
VM_ID: vm_mspc_001
CASE: gpu_allocation
ROLE: compute-profile
CRYSTAL: <sha256 of file content>
SCOPE: /data/Projects/MySpace++/studio/assets/_compute/gpu_profiles/
CREATED_AT: 2026-05-27T23:00:00Z
CHAIN_RUN_ID: run_20_avatar_pipeline
AGENT_UUID: <cc-agent-uuid>
```

The registry is auto-generated from filenames + file content hashes. It exists for fast lookup, but the filename is the source of truth.

---

## The Meta-Build Layer: Thing Building Things Building Things

```
Meta build (_meta/build_scripts/)
    │
    ├── sync_assets.py
    │   ├── reads: _meta/registry/asset_registry.json
    │   ├── reads: projects/<name>/project.manifest.json
    │   ├── creates: symlinks from _global/ → projects/<name>/
    │   └── creates: symlinks from _compute/ → projects/<name>/ (if project needs GPU)
    │
    ├── build_gdext.sh
    │   ├── compiles: cpp/ → godot/project/bin/
    │   └── outputs: libmspc.linux.template_debug.x86_64.so
    │
    ├── build_project.sh
    │   ├── packs: projects/<name>/ + assets/
    │   └── outputs: .pck + binary → projects/<name>/exports/
    │
    └── deploy_infra.sh
        ├── reads: _network/routers/*.json
        ├── reads: _agents/mcp_servers/*.json
        ├── reads: _compute/workers/*.json
        └── restarts: Caddy, MCP servers, watchdog
```

---

## Design Principles (from VM-CONSOLIDATION.md §9)

| Principle | Enforcement |
|-----------|-------------|
| **Only one real file root** | `studio/assets/` — everything else is symlinks |
| **VMs never nest** | All VMs at root level; imports via `imports/` |
| **Content-addressed** | Every file has a crystal hash in its JSON + registry |
| **Global + Local symmetry** | Same asset ID in global registry + project manifest |
| **Deterministic ID** | `vm_id = sha256(cwd \| agent_uuid)` |
| **LLM replies are navigable** | `SYM_INDEX` at end of every reply |
| **Tamper-evident** | Mirror pass catches any byte flip |
| **Self-organizing** | Filename encodes all state; directory is constant |
| **No UPDATE, only MOVE** | State changes by renaming/moving files |
| **Query via find/grep** | No SQL needed for 90% of lookups |

---

## What's in Git vs What's Ignored

**In Git (source of truth):**
- `studio/assets/_meta/` — all build scripts, templates, registry schemas
- `studio/assets/_global/data/*.json` — VM registry, task chains, sym index, motion index
- `studio/assets/_compute/gpu_profiles/*.json` — GPU configs (small)
- `studio/assets/_network/routers/*.json` — Router configs (small)
- `studio/assets/_agents/mcp_servers/*.json` — MCP server configs (small)
- `studio/assets/_agents/agent_defs/*.json` — Agent definitions (small)
- `studio/assets/_agents/inference_chains/*.json` — Chain definitions (small)
- `studio/assets/_web/sites/*.json` — Site configs (small)
- `studio/assets/_web/streams/*.json` — Stream configs (small)
- `studio/assets/_comms/permissions/*.json` — Permission registries (small)
- `studio/assets/_comms/messages/*.json` — Protocol definitions (small)
- `studio/assets/projects/default/` — default project scaffold + manifest
- `studio/godot/project/src/`, `cpp/` — GDScript and C++ source
- `studio/defold/walkthrough/scripts/` — Lua source

**In .gitignore (generated/large/runtime):**
- `studio/assets/_global/models/` — large binary assets (N001.fbx, etc.)
- `studio/assets/_global/animations/` — 228 FBX files
- `studio/assets/_global/textures/` — texture atlases
- `studio/assets/_global/audio/` — audio files
- `studio/assets/_global/fonts/` — font files
- `studio/assets/_inference/weights/` — model weights (GBs)
- `studio/assets/_inference/cache/` — crystal-hashed results
- `studio/assets/_godot/engine/` — Godot binaries
- `studio/assets/_compute/jobs/completed/` — job artifacts
- `studio/assets/_compute/jobs/failed/` — failed job logs
- `studio/assets/_compute/queues/*.snapshot.json` — runtime snapshots
- `studio/assets/_network/traffic_logs/` — packet captures
- `studio/assets/_agents/orchestrator/*.state.json` — runtime state
- `studio/assets/_agents/mcp_servers/*.log` — connection logs
- `studio/assets/_web/static/build/` — bundled JS/CSS
- `studio/assets/_web/streams/*.recording.mp4` — stream recordings
- `studio/assets/_comms/messages/*.queue.json` — message queues
- `studio/assets/_comms/auth/*.rotated.json` — rotated tokens
- `studio/assets/projects/*/exports/` — build artifacts

---

*This tree is canonical. Add new categories to any Layer 0 domain. Add new projects to Layer 1. Never put real files outside this root. The filename is the variable; the holder is constant.*
