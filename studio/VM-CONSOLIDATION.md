# VM + Chain Consolidation

**What this is:** A single-page map of the three rails we designed — VM filetree, TaskChain, and 2-pass LLM — plus the first applied case (Defold).

---

## 1 · The Three Rails

Everything cc does rides three rails that are always in sync:

| Rail | Where it lives | What it tracks |
|------|----------------|----------------|
| **VM** | `~/.vmfs/vm_<id>/` | Files, docs, imports as symlinks |
| **TaskChain** | `~/.cc/cc.db` + `.cc/local.db` | Global + local task state with same `task_chain_id` |
| **SYM_INDEX** | Appended to every LLM reply | Symbolic dictionary that makes the reply navigable |

---

## 2 · VM Filetree

### Root layout

```
~/.vmfs/
├── vm_a1b2c3d4/              ← VM 1 (cc scope)
│   ├── vm.card.txt
│   ├── files/                 ← symlinks to _local_assets
│   ├── docs/                  ← symlinks to docs
│   └── imports/               ← symlinks to other VMs
│       └── vm_d4e5f6g7 → ../../vm_d4e5f6g7/
├── vm_d4e5f6g7/              ← VM 2 (gently scope)
│   └── ...
└── _local_assets/             ← ONLY place with real files
    ├── gently/...
    └── MySpace++/...
```

### Canonical naming

```
symbol{array}.project.folder.file.git.branch.txt

# Example:
vm_a1b2c3d4{0}.MySpace++.core.cc.sh.abcd1234.main.txt
```

| Field | Meaning |
|-------|---------|
| `symbol` | `vm_<id>` — derived from `sha256(cwd \| agent_uuid)` |
| `{array}` | Slot/index or label inside this VM |
| `project` | Project name (MySpace++, gently, realestate) |
| `folder` | Logical role (core, src, docs, scenes) |
| `file` | Base filename |
| `git` | Tree hash or `nogit` |
| `branch` | Branch name or `nogit` |

### VM card

```
VM_ID: vm_a1b2c3d4
CASE: realestate
ROLE: chain-crystal | walkthrough | asset | doc-view
CRYSTAL: <optional chain crystal hash>
SCOPE: /data/Projects/MySpace++
CREATED_AT: 2026-05-27T12:34:56Z
CHAIN_RUN_ID: <optional>
AGENT_UUID: <cc-agent-uuid>
```

---

## 3 · TaskChain Rails

### One object for every task

```
TaskChain = {
  sym_array: ["vm_a1b2c3d4", "vm_d4e5f6g7", ...],
  task:      "analyze gently chain coordination",
  steps:     { vm_id -> StepState }
}
```

### StepState per VM

```
StepState = {
  vm_id:      "vm_a1b2c3d4",
  local_db:   "/path/.cc/local.db",
  global_db:  "~/.cc/cc.db",
  files:      [file-coords...],
  chain_ids:  [chain_run_ids...],
  tags:       ["analysis", "runtime"],
  status:     "pending" | "running" | "done"
}
```

### Global + Local symmetry

- `task_chain_id = sha256(sym_array + task + scope_header)`
- Same ID stored in BOTH global DB and local DB
- Global sees all projects; each project sees its slice

---

## 4 · Chain Coordination (MSPC ↔ GENTLY)

### The loop

```
1. predict   → what op to execute
2. execute   → run the op (model call, pass, etc.)
3. extend    → chain grows forward
4. mirror    → anti-particle for tamper detection
5. crystallize → crystal = sha256(forward || mirror)
```

### Correlation

- `correlation_id = sha256(cc_uuid || gn_uuid)`
- Appears in BOTH halves' cadence logs
- Both verify `crystal = sha256(forward || mirror)`

### Tables

```sql
-- chain_runs
id, hash, prev_hash, op, data_json, crystal, timestamp

-- chain_mirror
id, run_id, mirror_hash, inverse_op

-- cross_half_correlations
id, mspc_agent_uuid, gently_agent_uuid, correlation_id, timestamp
```

---

## 5 · 2-Pass LLM

### Pass 1: LLM-F (Forward / Semantic)

**Input:** scope header `{sym_array, task, steps}` + user instruction
**Output:** human-readable reasoning
**Rule:** can mention symbols, but doesn't emit the full table

### Pass 2: LLM-R (Reverse / Symbolic Indexer)

**Input:** same scope header + LLM-F's full text
**Output:** compact `SYM_INDEX` block at the end

```
SYM_INDEX = {
  "vm_a1b2c3d4": {
    project: "MySpace++",
    roles: ["chain-coordinator"],
    touched_files: ["core/cc.sh"],
    related_tasks: ["analyze gently chain coordination"],
    chains: ["chain_run_42"]
  },
  "vm_d4e5f6g7": {
    project: "gently",
    roles: ["runtime"],
    touched_files: ["gently-runtime/src/lib.rs"],
    related_tasks: ["analyze gently chain coordination"],
    chains: ["chain_run_43"]
  }
}
```

**Why:** bridges user language + deterministic structure. Every reply is navigable.

---

## 6 · Graph Walking

```
FUNCTION walk_vm_graph(start_vm_id):
    visited = SET()

    FUNCTION dfs(vm_id):
        IF vm_id IN visited: RETURN
        visited.ADD(vm_id)
        visit(vm_id)  # do work here

        FOR entry IN list_directory("~/.vmfs/" + vm_id + "/imports/"):
            IF entry.name STARTS_WITH "vm_":
                dfs(entry.name)

    dfs(start_vm_id)
```

---

## 7 · Defold Integration (First Applied Case)

### Bundle location

```bash
# Move from home to permanent location
mkdir -p ~/apps
mv ~/Defold-x86_64-linux ~/apps/

# Result: ~/apps/Defold-x86_64-linux/
# Symlink defold -> /nix/store/... keeps working
```

### VM for a walkthrough project

```
~/.vmfs/vm_realestate_001/
├── vm.card.txt
├── files/
│   ├── vm_realestate_001{0}.realestate.scenes.livingroom.abcd1234.main.txt
│   └── livingroom.model → ~/.vmfs/_local_assets/realestate/scenes/livingroom.model
├── docs/
│   └── walkthrough-spec.md → /path/to/spec.md
└── imports/
    └── vm_defold_runtime → ../../vm_defold_runtime/
```

### Lua script pattern

```lua
-- Fixed-state variables (prevents memory leaks)
local CURRENT_ROOM = "living_room"

function init(self)
    msg.post(".", "acquire_input_focus")
end

function on_message(self, message_id, message, sender)
    if message_id == hash("trigger_teleport") then
        local target = message.destination
        if target ~= CURRENT_ROOM then
            CURRENT_ROOM = target
            teleport_camera_to_node(target)
        end
    end
end
```

---

## 8 · cc.sh Integration Points

### New helpers to add

```bash
_cc_vmfs_init()      # create ~/.vmfs/ + _local_assets/
cc_current_vm_id()   # derive vm_id from cwd + agent_uuid
cc_see_file(path)    # register asset with canonical name
cc_vm_import(a, b)   # cross-VM import symlink
```

### New subcommands

```bash
cc -vmfs-list         # list all VMs
cc -vmfs-walk <id>    # BFS walk from VM
cc -vmfs-show <id>    # show VM metadata + files + imports
cc -chain-run <instr> # predict→execute→extend→mirror→crystallize
```

---

## 9 · Design Principles

| Principle | How we enforce it |
|-----------|-----------------|
| **Only one real file root** | `~/.vmfs/_local_assets/` — everything else is symlinks |
| **VMs never nest** | All VMs at `~/.vmfs/` root level; imports via `imports/` |
| **Content-addressed** | Canonical names include git tree + timestamp |
| **Global + Local symmetry** | Same `task_chain_id` in both DBs |
| **Deterministic ID** | `vm_id = sha256(cwd \| agent_uuid)` — same scope → same VM |
| **LLM replies are navigable** | `SYM_INDEX` at end of every reply |
| **Tamper-evident** | Mirror pass catches any byte flip in chain |

---

## 10 · Files Map

| File | What it covers |
|------|----------------|
| `VM-FILETREE.md` | Full VM specification (13 sections) |
| `DEFOLD-INTEGRATION.md` | Defold-specific integration (490 lines) |
| `CONSOLIDATION.md` | Tesseract/SVG layer (285 lines) |
| `studio/docs/NOTES-FOR-INFERANCE.md` | Inter-session protocol (MSPC ↔ GENTLY) |
| `studio/docs/RUST-CHAIN.md` | MSPC's view of gently rust chain |
| `studio/docs/TESSERACT.md` | 253-node meta-DAG |

---

*Last updated: 2026-05-27*
