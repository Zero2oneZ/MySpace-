# VM + Chain Architecture (Defold Embedded)

**What this is:** The complete MySpace++ / gently consolidation, embedded as data inside the Defold walkthrough project.

---

## 1 · Three Rails

| Rail | Defold Equivalent |
|------|-------------------|
| **VM** | `vm_navigator.lua` + `assets/data/vm_registry.json` |
| **TaskChain** | `task_manager.lua` + `assets/data/task_chains.json` |
| **SYM_INDEX** | `sym_indexer.lua` + `assets/data/sym_index.json` |

---

## 2 · VM Filetree (in-engine)

```
vm_registry.json
├── vm_realestate_001/          ← Walkthrough VM
│   ├── vm.card.txt (in JSON)
│   ├── files/                   ← Scene references
│   ├── docs/
│   └── imports/                 ← vm_defold_runtime
└── vm_defold_runtime/          ← Engine VM
    ├── vm.card.txt
    └── imports/                 ← vm_realestate_001
```

---

## 3 · Chain Runner (predict → execute → extend → mirror → crystallize)

Implemented in `chain_runner.lua`:
- `genesis()` — runtime identity binding
- `predict()` — what op to execute
- `execute()` — run the op
- `extend()` — chain grows
- `mirror()` — anti-particle
- `crystallize()` — crystal = xor(forward, mirror)

---

## 4 · 2-Pass LLM (in-engine approximation)

- **Pass 1 (LLM-F):** `walkthrough.lua` handles semantic reasoning
- **Pass 2 (LLM-R):** `sym_indexer.lua` generates `SYM_INDEX` on every state change

---

## 5 · Defold Integration

### Lua Scripts
| Script | Purpose |
|--------|---------|
| `vm_navigator.lua` | VM graph walking, canonical naming, imports |
| `chain_runner.lua` | Chain coordination, hashing, crystal |
| `task_manager.lua` | TaskChain rails, global+local sync |
| `sym_indexer.lua` | Symbolic index generation |
| `walkthrough.lua` | Main controller, room transitions, camera |

### Data Files
| File | Purpose |
|------|---------|
| `vm_registry.json` | VM metadata registry |
| `task_chains.json` | TaskChain data |
| `sym_index.json` | Symbol index for navigation |

---

## 6 · Cross-Half Protocol

The walkthrough can communicate with the GentlyOS half via:
- HTTP requests to `localhost:7445` (telos-ml-tools MCP)
- Shared `.env` keys
- `correlation_id = sha256(mspc_uuid || gn_uuid)`

---

*This doc is embedded in the Defold project so the architecture travels with the build.*
