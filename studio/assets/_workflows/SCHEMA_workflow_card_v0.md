# Workflow Card Schema v0

> The fifth substrate. A `workflow_card` describes a processing pipeline once;
> the `workflow_generator` then emits **5 semantically-equivalent surfaces**
> from the same card: Streamlit prototype, Godot scene (C++ default),
> Blender headless script, SpriteForge MCP call, ComfyUI workflow JSON.

## Filename convention

`vm_mspc_001.workflows.<category>.<name>.<state>.<version>.json`

Lives in `studio/assets/_workflows/`. Same VM symbol scheme as agent_defs.

## Required top-level fields

| Field | Type | Notes |
|---|---|---|
| `_schema` | str | `"workflow_card_v0"` |
| `vm_id` | str | always `"vm_mspc_001"` for now |
| `name` | str | snake_case |
| `category` | str | `avatar` / `realestate` / `texture` / `sprite` / `compose` / ... |
| `state` | str | `active` / `draft` / `archived` |
| `version` | str | `v0`, `v1`, ... |
| `inputs[]` | list | each: `{name, type, required, default?}` |
| `outputs[]` | list | each: `{name, type}` |
| `passes[]` | list | the chain — see below |
| `layer_stack[]` | list | Hypershade/Photoshop layer vocabulary — see below |
| `surfaces{}` | obj | one entry per target — see below |
| `depends_on[]` | list | crystal hashes of cards/models this references |

## passes[]

Each pass is a one-step inference call. Maps to either a local model in `/home/tom/models/`, an MCP tool call, or a ComfyUI node.

```json
{
  "id": "depth",
  "agent": "apple_DepthPro",
  "model_path": "/home/tom/models/apple_DepthPro",
  "engine": "diffusers|comfyui|mcp|blender|spriteforge",
  "in": ["photo"],
  "out": "depth_map",
  "tier": "medium",
  "status": "ACTIVE | IN-FLIGHT | STUB"
}
```

## layer_stack[]

The universal vocabulary. Drives Godot shader uniforms, Blender material sockets, SpriteForge composition, and ComfyUI image-mix nodes — same names everywhere.

```json
{ "name": "albedo",  "source": "pass:bake",      "blend": "base" }
{ "name": "normal",  "source": "pass:bake",      "blend": "normal_map" }
{ "name": "ao",      "source": "pass:bake",      "blend": "multiply" }
{ "name": "depth",   "source": "pass:depth",     "blend": "depth_uniform" }
{ "name": "alpha",   "source": "pass:faceswap",  "blend": "alpha" }
{ "name": "opacity", "source": "literal:1.0",    "blend": "opacity" }
{ "name": "gradient","source": "pass:style",     "blend": "screen" }
```

Allowed `blend`: base, multiply, screen, overlay, additive, normal_map, depth_uniform, alpha, opacity, gradient_h, gradient_v, color_dodge, soft_light, hard_light.

## surfaces{}

```json
{
  "streamlit":   { "template": "templates/<name>_proto.py.j2" },
  "godot":       { "language": "cpp",
                   "scene":  "templates/<name>_scene.tscn.j2",
                   "script": "templates/<name>_controller.gd.j2",
                   "native": "templates/<name>_native.cpp.j2" },
  "blender":     { "template": "templates/<name>_bake.py.j2",
                   "blender_bin": "blender --background --python" },
  "spriteforge": { "mcp_server": "spriteforge-mcp",
                   "tools": ["sprite_refine_prompt", "sprite_generate"] },
  "comfyui":     { "workflow_json": "templates/<name>_comfy.json.j2",
                   "install_path": "/data/Projects/ComfyUI",
                   "node_packs": ["impact", "ipadapter"] }
}
```

Default Godot language is **C++ GDExtension** (matches Rust ABI; no .NET runtime). Override to `"language": "csharp"` per-card when Microsoft tooling integration is needed.

## Surface determinism rule

Every surface emitted from a single card MUST produce identical observable behavior for the same inputs. The workflow_generator hashes each emitted artifact and verifies they all carry the same `card_crystal` in their generated headers.

## Example: minimal card

```json
{
  "_schema": "workflow_card_v0",
  "vm_id": "vm_mspc_001",
  "name": "photo_to_depth_normal",
  "category": "texture",
  "state": "active",
  "version": "v0",

  "inputs":  [{"name": "photo", "type": "image", "required": true}],
  "outputs": [{"name": "depth", "type": "image/exr"},
              {"name": "normal","type": "image/png"}],

  "passes": [
    {"id":"d","agent":"apple_DepthPro","engine":"diffusers","in":["photo"],"out":"depth","status":"ACTIVE"},
    {"id":"n","agent":"marigold_normals","engine":"diffusers","in":["photo"],"out":"normal","status":"ACTIVE"}
  ],

  "layer_stack": [
    {"name":"depth", "source":"pass:d","blend":"depth_uniform"},
    {"name":"normal","source":"pass:n","blend":"normal_map"}
  ],

  "surfaces": {
    "streamlit": {"template":"templates/photo_to_depth_normal_proto.py.j2"},
    "godot":     {"language":"cpp","scene":"templates/photo_to_depth_normal_scene.tscn.j2"}
  },

  "crystal": "",
  "depends_on": []
}
```

That's the contract. Every workflow_card on disk must validate against this schema.
