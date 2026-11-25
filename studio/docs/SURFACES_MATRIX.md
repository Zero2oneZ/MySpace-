# SURFACES MATRIX — workflow_card → 5 surfaces

Smoke-test of `core/lib/workflow_generator.py` against the 4 cards in
`studio/assets/_workflows/vm_mspc_001.workflows.*.json` x the 5 user-facing
surfaces (Streamlit / Godot / Blender / SpriteForge / ComfyUI).

- Generator entry: `python3 core/lib/workflow_generator.py generate <card> --target <surface>`
- "OK" = file written to disk under repo root (or ComfyUI install path).
- "skip" = card's `surfaces{}` block does NOT declare that surface — `generate_all`
  graceful-skips it; this matrix reports it as skip.
- "ERR" = exception raised. First line of stack trace included (none observed).

Run-1 driver: `/tmp/run_matrix.py` calls `WorkflowGenerator.generate_one(card, target)`
per cell. Godot column rolls scene + gd + cpp into one cell: success if the card
declared any of the three sub-targets and at least one wrote, error if any raised.

Run-1 timestamp: 2026-05-29T03:47:37-04:00
Run-2 timestamp: 2026-05-29T03:53:08-04:00 (5m 31s after run-1)

## Run 1 — 4 x 5

| Card | Streamlit | Godot | Blender | SpriteForge | ComfyUI |
|---|---|---|---|---|---|
| avatar.photo_to_avatar_rigged             | OK | OK | OK | OK | OK |
| harvest.pinterest_vector_motherload       | OK | skip | skip | skip | skip |
| realestate.realestate_walkthrough_full    | OK | OK | OK | OK | OK |
| surf.pump_surf_pipeline                   | OK | OK | OK | skip | OK |

Run-1 tallies: 14 OK, 6 skip, 0 ERR.

## Run 2 — 4 x 5

| Card | Streamlit | Godot | Blender | SpriteForge | ComfyUI |
|---|---|---|---|---|---|
| avatar.photo_to_avatar_rigged             | OK | OK | OK | OK | OK |
| harvest.pinterest_vector_motherload       | OK | skip | skip | skip | skip |
| realestate.realestate_walkthrough_full    | OK | OK | OK | OK | OK |
| surf.pump_surf_pipeline                   | OK | OK | OK | skip | OK |

Run-2 tallies: 14 OK, 6 skip, 0 ERR.

Run-1 vs Run-2 cell delta: NONE. Skip cells stayed skip; OK cells stayed OK.

## Templates landed during this turn

Snapshot at start of turn (5 files in `studio/assets/_workflows/templates/`):
- avatar_comfy.json.j2
- avatar_proto.py.j2
- pinterest_spriteforge_manifest.json.j2
- realestate_walkthrough_full_controller.gd.j2
- realestate_walkthrough_full_scene.tscn.j2

Snapshot at end of turn (6 files):
- avatar_bake.py.j2 (NEW — landed during the 5-min wait)
- avatar_comfy.json.j2
- avatar_proto.py.j2
- pinterest_spriteforge_manifest.json.j2
- realestate_walkthrough_full_controller.gd.j2
- realestate_walkthrough_full_scene.tscn.j2

Diff: `+ avatar_bake.py.j2`. No removals, no other additions.

## Why template diffs did NOT change the matrix

`workflow_generator.py` at this revision uses INTERNAL f-string generators
(`gen_streamlit`, `gen_godot_tscn`, `gen_godot_gd`, `gen_godot_cpp`, `gen_blender`,
`gen_spriteforge`, `gen_comfyui`). It does **not** open or read the `.j2` files in
`studio/assets/_workflows/templates/`. The schema's `surfaces.<surface>.template`
field is documentation / future-use only at this revision.

Cell outcomes therefore depend solely on whether each card declares the surface
key in its `surfaces{}` block — not on which templates have landed on disk. So
"template_missing" here means "card omitted that surface entry", which is a
graceful-skip path inside `generate_all`. No template-landing event will flip a
skip into an OK until the generator is taught to read .j2 files (or until a card
is edited — which we are explicitly forbidden from doing this turn).

## Notable behaviors observed

- **surf card** declares `"godot_scene"` (not `"godot"`) as the outer surfaces
  key. The generator's `generate_one("godot_scene", ...)` falls back to
  `surfaces.get("godot", {})` and therefore loses the out_scene/out_script/out_native
  overrides → emitted files go to default paths
  (`studio/godot/project/scenes/pump_surf_pipeline.tscn` instead of the intended
  `.../pump_surf.tscn`). File IS written so the cell is OK, but the path is off.
  Worth flagging to the card author or generator author.
- **avatar + realestate cards** declare a proper `"godot"` block with
  out_scene/out_script/out_native → emitted to the card-specified paths.
- **pinterest card** declares only `"streamlit"`; every other surface graceful-skips.
- **surf card** has no `"spriteforge"` key → graceful skip on that cell.
- The generator never errored across 4 x 5 x 2 = 40 invocations. Run-1 and Run-2
  produced byte-identical headers (same card_crystal per card both runs).

## Files actually written on disk (for verification)

```
studio/web/streamlit/photo_to_avatar_rigged.py
studio/web/streamlit/pinterest_vector_motherload.py
studio/web/streamlit/realestate_walkthrough_full.py
studio/web/streamlit/pump_surf_pipeline.py
studio/godot/project/scenes/avatar_rigged.tscn
studio/godot/project/scenes/realestate_walkthrough_full.tscn
studio/godot/project/scenes/pump_surf_pipeline.tscn
studio/godot/project/src/avatar_rigged_controller.gd
studio/godot/project/src/realestate_walkthrough_full_controller.gd
studio/godot/project/src/pump_surf_pipeline_controller.gd
studio/godot/project/cpp/src/avatar_rigged_native.cpp
studio/godot/project/cpp/src/realestate_walkthrough_full_native.cpp
studio/godot/project/cpp/src/pump_surf_pipeline_native.cpp
studio/blender/scripts/avatar_rigged_bake.py
studio/blender/scripts/realestate_walkthrough_full_bake.py
studio/blender/scripts/pump_surf_pipeline_bake.py
studio/spriteforge/manifests/avatar_rigged_sheet.json
studio/spriteforge/manifests/realestate_walkthrough_full_sheet.json
/data/Projects/ComfyUI/user/workflows/photo_to_avatar_rigged.json
/data/Projects/ComfyUI/user/workflows/realestate_walkthrough_full.json
/data/Projects/ComfyUI/user/workflows/pump_surf_pipeline.json
```
