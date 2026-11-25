# MySpace++ Defold Walkthrough

**Project:** Real estate walkthrough with embedded VM + Chain + TaskChain architecture.

## Structure

```
walkthrough/
├── game.project              # Defold project config
├── README.md                 # This file
├── scripts/
│   ├── walkthrough.lua       # Main controller
│   ├── vm_navigator.lua     # VM graph walking
│   ├── chain_runner.lua     # Chain coordination
│   ├── task_manager.lua     # TaskChain rails
│   └── sym_indexer.lua      # SYM_INDEX generation
├── scenes/
│   └── main.collection      # Main scene with camera + controller
├── assets/
│   └── data/
│       ├── vm_registry.json    # VM metadata
│       ├── task_chains.json    # TaskChain data
│       └── sym_index.json      # Symbol index
└── docs/
    └── VM_ARCHITECTURE.md    # Embedded architecture doc
```

## Running

1. Open Defold editor: `~/apps/Defold-x86_64-linux/defold`
2. Open project: `File > Open > studio/defold/walkthrough/`
3. Build: `Project > Build`

## Architecture

All MySpace++ / gently concepts are embedded as Lua scripts + JSON data:
- VMs = `vm_navigator.lua` + `vm_registry.json`
- Chain = `chain_runner.lua`
- TaskChain = `task_manager.lua` + `task_chains.json`
- SYM_INDEX = `sym_indexer.lua` + `sym_index.json`

The walkthrough demonstrates room transitions that trigger chain steps.

---

*Part of MySpace++ / GentlyOS consolidation.*
