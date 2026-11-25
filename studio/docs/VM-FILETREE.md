# VM Filetree — Root-Level Design

> **THIS IS THE ROOT FILETREE.** All VMs live directly under one root directory.

---

## 1 · Root Directory

```
~/.vmfs/
```

This is the **single root** for all virtual filesystems. No subdirectories, no nesting.

---

## 2 · VM Directory Structure

Each VM lives directly under `~/.vmfs/` with this structure:

```
~/.vmfs/vm_<id>/
├── vm.card.txt           # VM metadata (ID, CASE, ROLE, CRYSTAL, SCOPE)
├── files/                # Symlinks to real assets
├── docs/                 # Symlinks to documentation
└── imports/              # References to other VMs
    ├── vm_<other_id> → ../../vm_<other_id>/
```

**Key principle:** No VMs inside VMs. All VMs live at the same level.

---

## 3 · VM Metadata (vm.card.txt)

```
VM_ID: vm_a1b2c3d4
CASE: realestate
ROLE: chain-crystal | walkthrough | asset | doc-view | ...
CRYSTAL: <optional chain crystal hash>
SCOPE: /data/Projects/MySpace++
CREATED_AT: 2026-05-27T21:30:00Z
CHAIN_RUN_ID: <optional>
AGENT_UUID: <cc-agent-uuid>
```

---

## 4 · File Naming Convention (Canonical)

All asset files use this naming scheme:

```
symbol{array}.project.folder.file.git.branch.txt
```

**Example:**
```
vm_a1b2c3d4{0}.MySpace++core.cc.sh.abcd1234.main.txt
```

| Field | Description |
|-------|-------------|
| `vm_a1b2c3d4` | VM ID (same as directory name) |
| `{0}` | Slot/index within VM (0, 1, 2, or label like "notes") |
| `MySpace++` | Project name |
| `core` | Logical folder role (src, core, docs, etc.) |
| `cc.sh` | Base file name |
| `abcd1234` | Git tree/commit hash |
| `main` | Git branch |
| `.txt` | Metadata card extension |

---

## 5 · Asset VM Files

Each VM's `files/` directory contains:

```
~/.vmfs/vm_<id>/files/
├── symbol{slot}.project.folder.file.git.branch.txt  # canonical metadata card
├── current → symbol{slot}.project.folder.file.git.branch.txt  # convenience symlink
└── <original_name> → /real/path/to/file  # back-link to real file
```

**Example:**
```
vm_a1b2c3d4/files/
├── vm_a1b2c3d4{0}.MySpace++core.cc.sh.abcd1234.main.txt  # canonical name
├── current → vm_a1b2c3d4{0}.MySpace++core.cc.sh.abcd1234.main.txt
└── cc.sh → /data/Projects/MySpace++/core/cc.sh
```

---

## 6 · Doc VM Files

Each VM's `docs/` directory contains:

```
~/.vmfs/vm_<id>/docs/
├── doc_name.txt → /real/path/to/doc  # symlinks to docs
└── current → doc_name.txt  # convenience symlink
```

**Example:**
```
vm_a1b2c3d4/docs/
├── NOTES-FOR-INFERANCE.md → /data/Projects/MySpace++/studio/docs/NOTES-FOR-INFERANCE.md
└── current → NOTES-FOR-INFERANCE.md
```

---

## 7 · Imports (Cross-VM References)

Each VM can reference other VMs via symlinks in `imports/`:

```
~/.vmfs/vm_a1b2c3d4/imports/
├── vm_d4e5f6g7 → ../../vm_d4e5f6g7/  # import another VM
└── vm_h8i9j0k1 → ../../vm_h8i9j0k1/
```

**Key principles:**
- Imports reference other VMs by their `vm_<id>` name
- No VMs inside VMs — all VMs at root level
- Imports create a navigable graph

---

## 8 · Local Asset Root (Only Place with Real Files)

```
~/.vmfs/_local_assets/
```

This is the **only** place that contains actual files (not symlinks).

```
~/.vmfs/_local_assets/
├── gently/
│   └── crates/
│       └── gently-runtime/
│           └── src/
│               └── lib.rs  # real file
└── MySpace++/
    └── core/
        └── cc.sh  # real file
```

**All VMs point to files here via symlinks.**

---

## 9 · VM Graph Navigation

To walk the VM graph:

```
1. Start at a root VM (e.g., vm_a1b2c3d4)
2. Read vm.card.txt for metadata
3. Look at imports/ for referenced VMs
4. Follow each import symlink
5. Repeat for each imported VM (BFS/DFS)
```

**Graph walking ensures:**
- All VMs discoverable from any starting point
- Import cycles detectable
- No VMs hidden inside other VMs

---

## 10 · Integration with cc

### cc Derives VM ID from Scope

```bash
cc_current_vm_id() {
  local base="${CC_SCOPE_CWD}|${CC_AGENT_UUID}"
  local hash
  hash=$(printf '%s' "$base" | sha256sum | awk '{print $1}')
  echo "vm_${hash:0:8}"
}
```

### cc Sees Files and Creates VM Assets

```bash
cc_see_file() {
  local path="$1"
  local vm_id
  vm_id=$(cc_current_vm_id)
  local project folder file git branch slot
  project="$(project_name_from_path "$path")"
  folder="$(classify_folder "$path")"
  file="$(basename "$path")"
  git="$(git_tree_or_nogit "$path")"
  branch="$(git_branch_or_nogit "$path")"
  slot="$(next_slot_for "$vm_id" "$project" "$folder" "$file")"
  
  local name="${vm_id}{${slot}}.${project}.${folder}.${file}.${git}.${branch}"
  
  # Write canonical metadata card
  cat > "$HOME/.vmfs/$vm_id/files/$name" <<EOF
CASE: realestate
ASSET: ${file}
PROJECT: ${project}
PATH: ${path}
TIMESTAMP: $(date -u +%Y%m%dT%H%M%SZ)
GIT_TREE: ${git}
GIT_BRANCH: ${branch}
ROLE: asset
DOC_SECTION: doc://assets/$(dirname "$path")
EOF

  # Create back-link to real file
  ln -sf "$path" "$HOME/.vmfs/$vm_id/files/${file}"
}
```

---

## 11 · TaskChain + VM Sync

**Global (MSPC) + Local (Project) TaskChain share same `task_chain_id`:**

```
Global DB (~/.cc/cc.db):
  task_chains:
    - task_chain_id: abc123...
    - sym_array: ["vm_a1b2c3d4", "vm_d4e5f6g7"]
    - task: "analyze gently chain coordination"
    - steps: {...}

Local DB (.cc/local.db):
  task_chains:  # same task_chain_id
    - task_chain_id: abc123...
    - sym_array: ["vm_a1b2c3d4", "vm_d4e5f6g7"]
    - task: "analyze gently chain coordination"
```

**VMs correspond to symbols in `sym_array`.**

---

## 12 · Filetree Summary

```
~/.vmfs/                                    ← ROOT
├── vm_a1b2c3d4/                            ← VM 1 (MSPC project)
│   ├── vm.card.txt
│   ├── files/
│   │   ├── vm_a1b2c3d4{0}.MySpace++core.cc.sh.abcd1234.main.txt
│   │   └── cc.sh → /data/Projects/MySpace++/core/cc.sh
│   ├── docs/
│   │   └── NOTES-FOR-INFERANCE.md → .../NOTES-FOR-INFERANCE.md
│   └── imports/
│       └── vm_d4e5f6g7 → ../../vm_d4e5f6g7/
├── vm_d4e5f6g7/                            ← VM 2 (gently)
│   ├── vm.card.txt
│   ├── files/
│   │   └── vm_d4e5f6g7{0}.gentlycrates.lib.rs.efgh5678.main.txt
│   └── imports/
│       └── vm_a1b2c3d4 → ../../vm_a1b2c3d4/
├── _local_assets/                          ← ONLY place with real files
│   ├── gently/crates/gently-runtime/src/lib.rs
│   └── MySpace++/core/cc.sh
└── vm_crystal_abc123/                      ← VM 3 (chain snapshot)
    ├── vm.card.txt
    └── ...
```

**Key rules:**
1. All VMs at root level under `~/.vmfs/`
2. `_local_assets/` is the only place with actual files
3. All VMs contain only symlinks to `_local_assets/`
4. VMs import each other via `imports/` symlinks

---

## 13 · Next Steps for cc.sh Integration

1. Add `_cc_vmfs_init()` to create `~/.vmfs/` and `_local_assets/`
2. Add `cc_current_vm_id()` to derive VM ID from scope
3. Add `cc_see_file(path, vm_id)` to register assets
4. Add `cc_vm_import(vm_id_a, vm_id_b)` for cross-VM imports
5. Add subcommands: `-vmfs-list`, `-vmfs-walk`, `-vmfs-show`

[ end: main | scope: /data/Projects/MySpace++ ]
