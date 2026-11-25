# Defold Integration - MySpace++ Mod Integration Guide

## Overview

This document describes how MySpace++ integrates modifications into Defold for real estate walkthrough applications.

## Core Architecture

### Two-Part System

```
┌─────────────────────────────────────────────────────────────────┐
│                    Defold-x86_64-linux                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  /home/tom/apps/Defold-x86_64-linux                      │  │
│  │  ├── defold → /nix/store/.../bin/defold                  │  │
│  │  ├── Defold/                                             │  │
│  │  │   ├── config/                                         │  │
│  │  │   ├── Defold.jar (editor + bundled JDK)              │  │
│  │  │   └── packages/jdk-25+36/                            │  │
│  │  ├── run-defold.sh                                       │  │
│  │  └── defold.nix                                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  MySpace++ Modifications                                 │  │
│  │  └── studio/defold/                                      │  │
│  │      ├── walkthroughs/                                   │  │
│  │      │   ├── template.defoldproj                         │  │
│  │      │   └── config/                                     │  │
│  │      ├── assets/                                         │  │
│  │      │   ├── textures/                                   │  │
│  │      │   ├── models/                                     │  │
│  │      │   └── scripts/                                    │  │
│  │      └── integration.sh                                  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Asset VM Architecture

Each walkthrough project lives in a VM structure:

```
~/.vmfs/vm_<hash>/
├── vm.card.txt           # VM metadata (PROJECT, ROLE, CRYSTAL)
├── files/                # Symlinks to real assets
├── docs/                 # Symlinks to documentation
└── imports/              # References to other VMs
    ├── vm_<other_hash> → ../../vm_<other_hash>/
```

## File Naming Convention

### Canonical Format

```
symbol{array}.project.folder.file.git.branch.txt
```

### Example

```
vm_a1b2c3{0}.realestate.scenes.livingroom.abcd1234.main.txt
```

| Component | Description |
|-----------|-------------|
| `vm_a1b2c3` | VM ID (derived from cwd + agent_id) |
| `{0}` | Slot/index within VM |
| `realestate` | Project name |
| `scenes` | Logical folder role |
| `livingroom` | Base file name |
| `abcd1234` | Git tree/commit hash |
| `main` | Git branch |
| `.txt` | Metadata card extension |

## Integration Steps

### Step 1: Defold Bundle Location

Move the Defold bundle to a permanent location:

```bash
# Current location
cd ~

# Create apps directory and move bundle
mkdir -p apps
mv Defold-x86_64-linux apps/

# Result: /home/tom/apps/Defold-x86_64-linux
```

### Step 2: Path Configuration

Add to `~/.bashrc` or `~/.zshrc`:

```bash
export DEFOLD_ROOT="$HOME/apps/Defold-x86_64-linux"
export PATH="$DEFOLD_ROOT:$PATH"
```

Reload shell:
```bash
source ~/.bashrc
```

### Step 3: VM Structure Creation

For each walkthrough project:

```bash
# Create VM directory structure
mkdir -p ~/.vmfs/vm_$(short_hash "$PWD|$(uuid)").files
mkdir -p ~/.vmfs/vm_$(short_hash "$PWD|$(uuid)").docs
mkdir -p ~/.vmfs/vm_$(short_hash "$PWD|$(uuid)").imports

# Write VM metadata
cat > ~/.vmfs/vm_<hash>/vm.card.txt << EOF
VM_ID: vm_$(short_hash "$PWD|$(uuid)")
CASE: realestate
ROLE: walkthrough-crystal
SCOPE: $PWD
CREATED_AT: $(date -u +%Y%m%dT%H%M%SZ)
EOF
```

### Step 4: Asset Registration

Register each file with canonical naming:

```bash
function cc_see_file() {
    local path="$1"
    local vm_id="vm_$(short_hash "$PWD|$(uuid)")"
    local project=$(project_name_from_path "$path")
    local folder=$(classify_folder "$path")
    local file=$(basename "$path")
    local git=$(git_tree_or_nogit "$path")
    local branch=$(git_branch_or_nogit "$path")
    local slot=$(next_slot_for "$vm_id" "$project" "$folder" "$file")
    
    local name="${vm_id}{${slot}}.${project}.${folder}.${file}.${git}.${branch}"
    
    # Create metadata card
    cat > ~/.vmfs/vm_<hash>/files/${name} << EOF
CASE: realestate
ASSET: ${file}
PROJECT: ${project}
PATH: ${path}
TIMESTAMP: $(date -u +%Y%m%dT%H%M%SZ)
GIT_TREE: ${git}
GIT_BRANCH: ${branch}
ROLE: walkthrough-asset
DOC_SECTION: docs/walkthroughs/$(basename $(dirname "$path"))
EOF

    # Create symlink to real file
    ln -sf "$path" ~/.vmfs/vm_<hash>/files/current
}
```

## Defold Project Structure

### Walkthrough Template

```
studio/defold/walkthroughs/template.defoldproj
├── assets/
│   ├── models/
│   │   └── livingroom.model
│   ├── textures/
│   │   └── livingroom.png
│   └── scripts/
│       └── walkthrough.lua
├── scenes/
│   └── main.scene
└── config/
    └── defold.config
```

### Lua Scripts

Walkthrough logic in `scripts/walkthrough.lua`:

```lua
-- Fixed-state variables (prevents memory leaks)
local CURRENT_ROOM = "living_room"
local camera_node = nil

function init(self)
    -- Bind scene objects
    camera_node = go.get("camera")
    print("Walkthrough Ready. Current Room:", CURRENT_ROOM)
end

function update(self, dt)
    -- Render loop - monitor for memory drift
    if self.is_transitioning then
        smooth_glide_to_viewpoint(self)
    end
end

function on_message(self, message_id, message, sender)
    -- Handle hotspot clicks
    if message_id == hash("trigger_teleport") then
        local target_room = message.destination
        if target_room ~= CURRENT_ROOM then
            CURRENT_ROOM = target_room
            teleport_camera_to_node(target_room)
        end
    end
end
```

## cc.sh Integration

### New Subcommands

```bash
# cc -defold-integrate <project-path>
# Integrates a project into Defold VM structure
cmd_defold_integrate() {
    local project_path="$1"
    
    # 1. Create VM structure
    local vm_id=$(cc_current_vm_id)
    local vm_root="$HOME/.vmfs/$vm_id"
    
    mkdir -p "$vm_root/files"
    mkdir -p "$vm_root/docs"
    mkdir -p "$vm_root/imports"
    
    # 2. Write VM metadata
    cat > "$vm_root/vm.card.txt" << EOF
VM_ID: $vm_id
CASE: realestate
ROLE: walkthrough-crystal
SCOPE: $project_path
CREATED_AT: $(date -u +%Y%m%dT%H%M%SZ)
EOF
    
    # 3. Register all project files
    find "$project_path" -type f | while read -r file; do
        cc_see_file "$file" "$vm_id"
    done
    
    # 4. Link to Defold assets
    ln -sf "$DEFOLD_ROOT" "$vm_root/imports/defold"
}

# cc -defold-asset <project-path> <asset-type>
# Registers a new asset type for walkthrough
cmd_defold_asset() {
    local project_path="$1"
    local asset_type="$2"
    
    local vm_id=$(cc_current_vm_id)
    local asset_name=$(generate_asset_name "$project_path" "$asset_type")
    
    # Create asset VM if needed
    local asset_vm="vm_$(short_hash "$vm_id|$asset_type")"
    local asset_root="$HOME/.vmfs/$asset_vm"
    
    mkdir -p "$asset_root/files"
    
    # Link asset
    ln -sf "$project_path" "$asset_root/files/current"
    
    # Update main VM imports
    ln -sf "../$asset_vm" "$HOME/.vmfs/$vm_id/imports/$asset_vm"
    
    echo "Asset registered: $asset_name"
}
```

## Navigation System

### VM Graph Walking

```bash
# cc -defold-walk <vm-id>
# Walks the VM graph starting from given VM
cmd_defold_walk() {
    local start_vm="$1"
    
    # BFS walk of VM graph
    declare -A visited
    local queue=("$start_vm")
    
    while [ ${#queue[@]} -gt 0 ]; do
        local current="${queue[0]}"
        queue=("${queue[@]:1}")
        
        if [ -z "${visited[$current]}" ]; then
            visited[$current]=1
            echo "Visiting: $current"
            
            # Read VM metadata
            if [ -f "$HOME/.vmfs/$current/vm.card.txt" ]; then
                echo "  $(cat $HOME/.vmfs/$current/vm.card.txt)"
            fi
            
            # Add imports to queue
            if [ -d "$HOME/.vmfs/$current/imports" ]; then
                for import in "$HOME/.vmfs/$current/imports/"*; do
                    if [ -L "$import" ]; then
                        local import_name=$(basename "$import")
                        queue+=("$import_name")
                    fi
                done
            fi
        fi
    done
}
```

## Deterministic Chain Integration

### TaskChain + VM Sync

```bash
# cc -defold-chain-run <instruction>
# Runs a chain and creates VM snapshot
cmd_defold_chain_run() {
    local instruction="$*"
    
    # 1. Run chain (predict → execute → extend → mirror → crystallize)
    local forward_hash mirror_hash crystal chain_run_id
    read forward_hash mirror_hash crystal chain_run_id < <(run_chain "$instruction")
    
    # 2. Create VM named by crystal
    local vm_id="vm_crystal_${crystal:0:16}"
    local vm_root="$HOME/.vmfs/$vm_id"
    
    mkdir -p "$vm_root/files"
    mkdir -p "$vm_root/docs"
    
    # 3. Write metadata card
    cat > "$vm_root/vm.card.txt" << EOF
CHAIN_RUN_ID: $chain_run_id
CRYSTAL: $crystal
FORWARD_HASH: $forward_hash
MIRROR_HASH: $mirror_hash
CASE: realestate
SCOPE: $PWD
PROJECT: MySpace++
GIT_TREE: $(git_rev_parse HEAD 2>/dev/null || echo nogit)
GIT_BRANCH: $(git_rev_parse --abbrev-ref HEAD 2>/dev/null || echo nogit)
TIMESTAMP: $(date -u +%Y%m%dT%H%M%SZ)
DOC_SECTION: doc://defold/runtime/chain-coordination
EOF
    
    # 4. Refresh symlink views
    refresh_file_symlinks "$vm_root/files/" "$(touched_files)"
    refresh_doc_symlinks "$vm_root/docs/" "$(touched_docs)"
    
    echo "Chain executed. VM created: $vm_id"
    echo "Crystal: $crystal"
}
```

## Deployment

### Building Walkthroughs

```bash
# Build walkthrough package
cc -defold-build <project-path>

# This creates:
# 1. VM snapshot under ~/.vmfs/
# 2. Asset registry in ~/.vmfs/_local_assets/
# 3. Integration manifest in project/.cc/defold-integration.json

# Run walkthrough with Defold
cc -defold-run <project-path>
```

### File Tree Structure

```
~/.vmfs/
├── _local_assets/          # Only place with real files
│   ├── MySpace++/
│   │   └── core/
│   │       └── cc.sh → /data/Projects/MySpace++/core/cc.sh
│   └── defold/
│       └── Defold.jar → /home/tom/apps/Defold-x86_64-linux/Defold/Defold.jar
├── vm_crystal_abc123/
│   ├── vm.card.txt
│   ├── files/
│   │   └── MySpace_cc.sh.abc123.main → ../_local_assets/MySpace++/core/cc.sh
│   ├── docs/
│   │   └── NOTES-FOR-INFERANCE.md → ../_local_assets/docs/NOTES-FOR-INFERANCE.md
│   └── imports/
│       └── vm_defold → ../../vm_defold/
└── vm_defold/
    ├── vm.card.txt
    └── imports/
        └── vm_crystal_abc123 → ../../vm_crystal_abc123/
```

## Verification

### Crystal Hash Verification

```bash
# Verify chain + VM integrity
cc -defold-verify <vm-id>

# This checks:
# 1. vm.card.txt metadata matches VM structure
# 2. All symlinks point to valid targets
# 3. Crystal hash in metadata matches chain_runs in DB
# 4. Import references resolve correctly
```

### Global/Local DB Sync

```sql
-- TaskChain stored in both DBs with same ID
-- Global: ~/.cc/cc.db
-- Local:  .cc/local.db

SELECT * FROM task_chains WHERE task_chain_id = ?
-- Returns same row in both DBs

-- VM references stored as foreign keys
SELECT * FROM vm_snapshots WHERE task_chain_id = ?
SELECT * FROM chain_runs WHERE vm_id = ?
```

## Future Extensions

### Hopf Fibration Double Hash

For advanced use cases, add structural hashing:

```
id = blake3(normalized_IR)
structural_hash = blake3(IR_shape_only)
```

This creates a "fibration" where:
- `id` = exact logic (content hash)
- `structural_hash` = shape/topology of logic

### Integration with cc TaskChain

```
TaskChain = {
  sym_array: ["vm_defold", "vm_crystal_abc123"],
  task: "real estate walkthrough for property #123",
  steps: {
    "vm_defold": {
      project: "defold",
      role: "runtime",
      touched_files: ["Defold.jar", "run-defold.sh"],
      chains: ["chain_run_42"],
      status: "done"
    },
    "vm_crystal_abc123": {
      project: "MySpace++",
      role: "walkthrough",
      touched_files: ["cc.sh", "NOTES-FOR-INFERANCE.md"],
      chains: ["chain_run_43"],
      status: "running"
    }
  }
}
```

## Summary

Defold integration in MySpace++ follows a deterministic, content-addressed architecture:

1. **VMs** = frozen snapshots of project state, named by crystal hash
2. **Files** = canonical naming scheme: `symbol{array}.project.folder.file.git.branch.txt`
3. **Imports** = VM-to-VM references, creating a navigable graph
4. **TaskChain** = global + local sync of all operations
5. **cc.sh** = orchestrator with new subcommands for Defold workflows

This provides:
- Deterministic reproducibility
- Easy navigation and graph walking
- Cross-project asset sharing
- Chain-linked verification
