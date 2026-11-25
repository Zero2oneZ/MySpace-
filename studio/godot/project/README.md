# MySpace++ Godot Studio

C++-accelerated 3D inference substrate for Godot 4.6.3.

## Structure

```
project/
├── project.godot          # Project config
├── src/
│   ├── main_controller.gd # Entry point + native loader
│   ├── vm_navigator.gd    # VM graph walking (autoload)
│   ├── chain_runner.gd    # Chain coordination (autoload)
│   ├── task_manager.gd    # TaskChain rails (autoload)
│   └── sym_indexer.gd     # SYM_INDEX generation (autoload)
├── cpp/
│   ├── mspc.gdextension   # Extension manifest
│   ├── SConstruct         # Build config
│   ├── include/
│   │   ├── spatial_bridge.h # PhysicsContext + crystal hash + depth fusion
│   │   └── ik_solver.h      # 2-bone analytic + CCD IK
│   └── src/
│       ├── register_types.cpp
│       ├── spatial_bridge.cpp
│       └── ik_solver.cpp
├── scenes/
│   └── main.tscn          # Boot scene
├── assets/data/
│   ├── vm_registry.json   # VM metadata (from Defold walkthrough)
│   ├── task_chains.json   # TaskChain data
│   └── sym_index.json     # Symbol index
└── build-cpp.sh           # One-shot C++ build
```

## Building the native extension

```bash
cd studio/godot/project
bash build-cpp.sh
```

Requires `scons` and `g++`. The script auto-clones `godot-cpp` on first run.

## Running

```bash
# From a machine with display:
/path/to/Godot_v4.6.3-stable_linux.x86_64 --path studio/godot/project

# Or project manager:
/path/to/Godot_v4.6.3-stable_linux.x86_64
# Then File > Open > studio/godot/project/
```

## Architecture

GDScript layer (autoloads) mirrors Defold's Lua scripts:
- **VMNavigator** — loads `vm_registry.json`, provides graph walking + SHA-256 crystal hashing
- **ChainRunner** — async chain execution with per-step signals + final crystal
- **TaskManager** — task queue + flush
- **SymIndexer** — symbol table CRUD + JSON persistence

C++ layer (GDExtension) accelerates spatial/inference math:
- **SpatialBridge** — `PhysicsContext` computation, depth fusion, mirror-pass drift
- **IKSolver** — analytic 2-bone + CCD chain IK, `ik_delta` for strain metrics

## Integration with Run #20

The C++ types map directly to the spatial-hardened inference loop:
- `PhysicsContext.joint_stretch` / `joint_ik_strain` → feed video-gen conditioning
- `mirror_drift()` → Run #20 mirror-pass validation
- `fuse_depth()` → free concurrent inference channel fusion

See `docs/NOTES-ON-3d-INFERANCE.md` for the full Run #20 plan.
