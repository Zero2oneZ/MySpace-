# GENERATED from workflow_card: photo_to_avatar_rigged
# card_crystal: 1917513678f00c6919f700557f6e49c71caec383d7b90d5522066df93bd042811b23ae2f84cb585766a734a7388f2e1259496b1f20f10a1533e76ff9b79ccd5a
# rendered_at:  2026-05-29T00:00:00Z
# target:       blender
# schema:       workflow_card_v0
# template:     templates/avatar_bake.py.j2
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate photo_to_avatar_rigged

"""photo_to_avatar_rigged — Blender headless bake script.

Rendered: 2026-05-29T00:00:00Z
Card:     photo_to_avatar_rigged (avatar/active/v0)

Usage:
    blender --background --python photo_to_avatar_rigged_bake.py -- \\
        --photo <path> \\
        --voice_clip <path> \\
        --style_ref <path>

This script is deterministic. Identical inputs + identical card_crystal
yield identical output filenames under studio/assets/_bakes/.
"""

import bpy
import argparse
import hashlib
import json
import sys
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Card constants (frozen at generation time)
# ---------------------------------------------------------------------------
CARD_NAME     = "photo_to_avatar_rigged"
CARD_CRYSTAL  = "1917513678f00c6919f700557f6e49c71caec383d7b90d5522066df93bd042811b23ae2f84cb585766a734a7388f2e1259496b1f20f10a1533e76ff9b79ccd5a"
RENDERED_TS   = "2026-05-29T00:00:00Z"
CARD_CATEGORY = "avatar"
CARD_VERSION  = "v0"

LAYER_STACK = [
  {
    "blend": "base",
    "name": "albedo",
    "source": "pass:bake_pbr",
    "target_uniform": "u_albedo"
  },
  {
    "blend": "normal_map",
    "name": "normal",
    "source": "pass:bake_pbr",
    "target_uniform": "u_normal"
  },
  {
    "blend": "multiply",
    "name": "ao",
    "source": "pass:bake_pbr",
    "target_uniform": "u_ao"
  },
  {
    "blend": "depth_uniform",
    "name": "depth",
    "source": "pass:depth",
    "target_uniform": "u_depth"
  },
  {
    "blend": "alpha",
    "name": "alpha",
    "source": "pass:faceswap_lock",
    "target_uniform": "u_alpha"
  },
  {
    "blend": "opacity",
    "name": "opacity",
    "source": "literal:1.0",
    "target_uniform": "u_opacity"
  }
]

# Blend mode -> Principled BSDF / output socket mapping. Keep in sync with
# SCHEMA_workflow_card_v0.md and Godot u_* uniform conventions.
BLEND_SOCKET_MAP = {
    "base":          ("Principled BSDF", "Base Color"),
    "multiply":      ("Principled BSDF", "Roughness"),
    "normal_map":    ("Principled BSDF", "Normal"),
    "depth_uniform": ("Material Output", "Displacement"),
    "alpha":         ("Principled BSDF", "Alpha"),
    "opacity":       ("Principled BSDF", "Alpha"),   # mixed with existing alpha
    "additive":      ("Principled BSDF", "Emission"),
    "screen":        ("Principled BSDF", "Emission"),  # boosted via Strength
    # Stubs — wiring deferred to Hypershade-style group nodes:
    "overlay":       (None, None),   # stub: implement via MixRGB OVERLAY group
    "gradient_h":    (None, None),   # stub: implement via Gradient + Mapping (X axis)
    "gradient_v":    (None, None),   # stub: implement via Gradient + Mapping (Y axis)
    "color_dodge":   (None, None),   # stub
    "soft_light":    (None, None),   # stub
    "hard_light":    (None, None),   # stub
}


# ---------------------------------------------------------------------------
# Argparse — Blender requires args after `--` separator
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    """Parse CLI args. Blender swallows everything before `--`, so we slice."""
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser(
        prog="photo_to_avatar_rigged_bake",
        description="Deterministic Blender bake — card=photo_to_avatar_rigged",
    )
    p.add_argument(
        "--photo",
        type=str,
        required=True,
        help="image/jpeg|png (required)",
    )
    p.add_argument(
        "--voice_clip",
        type=str,
        required=False, default=None,
        help="audio/wav|mp3 (optional)",
    )
    p.add_argument(
        "--style_ref",
        type=str,
        required=False, default=None,
        help="image|workflow_ref (optional)",
    )
    p.add_argument(
        "--out_dir",
        type=str,
        required=False,
        default=None,
        help="Override output directory (default: studio/assets/_bakes/<card>_<ts>/)",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Deterministic output dir
# ---------------------------------------------------------------------------
def resolve_out_dir(args: argparse.Namespace) -> Path:
    """Deterministic: same card_crystal + same rendered_ts -> same directory."""
    if args.out_dir:
        out = Path(args.out_dir)
    else:
        # Resolve studio root by walking up from script location.
        here = Path(__file__).resolve()
        studio = here
        for _ in range(6):
            if (studio / "assets" / "_workflows").exists():
                break
            studio = studio.parent
        bakes_root = studio / "assets" / "_bakes"
        # Slug ts so it survives Windows + tab completion.
        ts_slug = RENDERED_TS.replace(":", "").replace("-", "").replace("T", "_").rstrip("Z")
        out = bakes_root / f"{CARD_NAME}_{ts_slug}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def deterministic_filename(out_dir: Path, pass_id: str, ext: str) -> Path:
    """Hash (card_crystal + pass_id) to make collisions impossible across cards."""
    h = hashlib.sha256(f"{CARD_CRYSTAL}|{pass_id}".encode()).hexdigest()[:16]
    return out_dir / f"{pass_id}_{h}.{ext}"


# ---------------------------------------------------------------------------
# Helper: scene + material scaffolding
# ---------------------------------------------------------------------------
def ensure_clean_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)
    for img in list(bpy.data.images):
        if img.users == 0:
            bpy.data.images.remove(img)


def load_mesh(path: str | None) -> bpy.types.Object | None:
    if not path or not Path(path).exists():
        print(f"  [warn] mesh not found: {path} — falling back to default cube")
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        obj.name = f"mesh_{CARD_NAME}"
        return obj
    suffix = Path(path).suffix.lower()
    if suffix in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    else:
        print(f"  [warn] unsupported mesh format {suffix} — using cube")
        bpy.ops.mesh.primitive_cube_add()
    return bpy.context.active_object


def ensure_pbr_material(name: str) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    mat.use_nodes = True
    return mat


def get_or_make_image(name: str, size: int = 1024, alpha: bool = False) -> bpy.types.Image:
    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.new(name, width=size, height=size, alpha=alpha)
    return img


# ---------------------------------------------------------------------------
# Pass functions — one per passes[] row with engine == "blender"
# ---------------------------------------------------------------------------


def pass_bake_pbr(args: argparse.Namespace, out_dir: Path, obj: bpy.types.Object | None) -> dict:
    """Pass `bake_pbr` — agent=blender_pbr_bake status=IN-FLIGHT.

    Inputs:  mesh_3d_raw, identity_locked_albedo, normal_map, depth_map
    Outputs: albedo_baked, normal_baked, ao_baked
    """
    print(f"  [pass] bake_pbr — agent=blender_pbr_bake")
    outputs = {}
    # Albedo / base-color bake — projects identity_locked_albedo (or photo) onto UV.
    albedo_img = get_or_make_image(f"bake_pbr_albedo", size=1024, alpha=True)
    src_path = getattr(args, "photo", None) or getattr(args, "identity_locked_albedo", None)
    if src_path and Path(src_path).exists():
        loaded = bpy.data.images.load(src_path, check_existing=True)
        # Paint source into bake image via UV project (placeholder; real impl
        # uses bpy.ops.paint.project_image once UV layout is finalized).
        albedo_img.pixels = list(loaded.pixels) if len(loaded.pixels) == len(albedo_img.pixels) else albedo_img.pixels[:]
    out_path = deterministic_filename(out_dir, "bake_pbr_albedo", "png")
    albedo_img.filepath_raw = str(out_path)
    albedo_img.file_format = "PNG"
    albedo_img.save()
    outputs["albedo_baked"] = str(out_path)
    # Normal bake — Cycles tangent-space normal off active object.
    if obj is not None:
        bpy.context.scene.render.engine = "CYCLES"
        normal_img = get_or_make_image(f"bake_pbr_normal", size=1024)
        mat = ensure_pbr_material(f"mat_bake_pbr_normal")
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        nodes = mat.node_tree.nodes
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = normal_img
        nodes.active = tex_node
        try:
            bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT")
        except RuntimeError as e:
            print(f"    [warn] normal bake skipped: {e}")
        out_path = deterministic_filename(out_dir, "bake_pbr_normal", "png")
        normal_img.filepath_raw = str(out_path)
        normal_img.file_format = "PNG"
        normal_img.save()
        outputs["normal_baked"] = str(out_path)
    # Ambient occlusion bake.
    if obj is not None:
        bpy.context.scene.render.engine = "CYCLES"
        ao_img = get_or_make_image(f"bake_pbr_ao", size=1024)
        mat = ensure_pbr_material(f"mat_bake_pbr_ao")
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        nodes = mat.node_tree.nodes
        tex_node = nodes.new("ShaderNodeTexImage")
        tex_node.image = ao_img
        nodes.active = tex_node
        try:
            bpy.ops.object.bake(type="AO")
        except RuntimeError as e:
            print(f"    [warn] ao bake skipped: {e}")
        out_path = deterministic_filename(out_dir, "bake_pbr_ao", "png")
        ao_img.filepath_raw = str(out_path)
        ao_img.file_format = "PNG"
        ao_img.save()
        outputs["ao_baked"] = str(out_path)
    print(f"    -> {len(outputs)} output(s): {list(outputs)}")
    return outputs


# ---------------------------------------------------------------------------
# compose_pbr — walks layer_stack[] and wires Principled BSDF
# ---------------------------------------------------------------------------
def compose_pbr(pass_outputs: dict, obj: bpy.types.Object | None) -> bpy.types.Material:
    """Build a single material that wires every layer_stack[] entry into the
    Principled BSDF / Material Output node per BLEND_SOCKET_MAP.

    Returns the assembled material so callers (export) can re-target it.
    """
    mat = ensure_pbr_material(f"mat_{CARD_NAME}_composed")
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Find or create canonical nodes.
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    mat_out = nodes.get("Material Output")
    if mat_out is None:
        mat_out = nodes.new("ShaderNodeOutputMaterial")
    links.new(bsdf.outputs["BSDF"], mat_out.inputs["Surface"])

    for layer in LAYER_STACK:
        name  = layer.get("name", "?")
        src   = layer.get("source", "")
        blend = layer.get("blend", "base")
        node_name, socket_name = BLEND_SOCKET_MAP.get(blend, (None, None))

        # Stub blends — leave breadcrumb comments and move on.
        if node_name is None:
            print(f"  [compose] layer {name!r} blend={blend!r}: STUB — wire via custom group node")
            # TODO: implement {blend} via MixRGB / Group node group.
            continue

        # Resolve the source. literal:* is constant; pass:<id> is upstream image.
        if src.startswith("literal:"):
            const_val = src.split(":", 1)[1]
            # Numeric literal -> set socket default directly when possible.
            try:
                v = float(const_val)
                target_node = mat_out if node_name == "Material Output" else bsdf
                if socket_name in target_node.inputs:
                    sock = target_node.inputs[socket_name]
                    if hasattr(sock, "default_value"):
                        try:
                            sock.default_value = v
                        except TypeError:
                            sock.default_value = (v, v, v, 1.0)
                print(f"  [compose] {name}={const_val} -> {node_name}.{socket_name} (literal)")
            except ValueError:
                print(f"  [compose] {name}={const_val} -> non-numeric literal, skipped")
            continue

        if src.startswith("pass:"):
            pass_id = src.split(":", 1)[1]
            # Find any output image produced by that pass.
            img_path = None
            for k, v in pass_outputs.items():
                if pass_id in k or k.startswith(pass_id):
                    img_path = v
                    break
            if not img_path or not Path(img_path).exists():
                print(f"  [compose] {name}: pass {pass_id!r} produced no image -> skipped")
                continue
            tex = nodes.new("ShaderNodeTexImage")
            tex.image = bpy.data.images.load(img_path, check_existing=True)
            target_node = mat_out if node_name == "Material Output" else bsdf

            if socket_name not in target_node.inputs:
                print(f"  [compose] {name}: socket {socket_name!r} missing on {node_name} -> skipped")
                continue

            if blend == "normal_map":
                # Normal needs a Normal Map node between Image and BSDF.Normal.
                nm = nodes.new("ShaderNodeNormalMap")
                links.new(tex.outputs["Color"], nm.inputs["Color"])
                links.new(nm.outputs["Normal"], target_node.inputs[socket_name])
            elif blend == "alpha":
                links.new(tex.outputs["Color"], target_node.inputs[socket_name])
            elif blend == "opacity":
                # Mix existing alpha with the opacity image via MixRGB.
                mix = nodes.new("ShaderNodeMixRGB")
                mix.blend_type = "MULTIPLY"
                mix.inputs["Fac"].default_value = 1.0
                links.new(tex.outputs["Color"], mix.inputs[2])
                links.new(mix.outputs["Color"], target_node.inputs[socket_name])
            elif blend == "screen" and socket_name == "Emission":
                # Screen -> Emission with boost (multiply via Math node).
                mul = nodes.new("ShaderNodeMath")
                mul.operation = "MULTIPLY"
                mul.inputs[1].default_value = 1.25  # screen boost
                links.new(tex.outputs["Color"], mul.inputs[0])
                # Emission socket is a color — fall back to direct color link.
                links.new(tex.outputs["Color"], target_node.inputs[socket_name])
            elif blend == "depth_uniform" and node_name == "Material Output":
                # Displacement needs a Displacement node between Image and output.
                disp = nodes.new("ShaderNodeDisplacement")
                links.new(tex.outputs["Color"], disp.inputs["Height"])
                links.new(disp.outputs["Displacement"], target_node.inputs[socket_name])
            else:
                # Default: Color -> socket.
                links.new(tex.outputs["Color"], target_node.inputs[socket_name])
            print(f"  [compose] {name}: pass:{pass_id} -> {node_name}.{socket_name} ({blend})")

    if obj is not None:
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
    return mat


# ---------------------------------------------------------------------------
# Export — single .glb under the deterministic out_dir
# ---------------------------------------------------------------------------
def export_glb(out_dir: Path) -> Path:
    out_path = deterministic_filename(out_dir, "composed", "glb")
    try:
        bpy.ops.export_scene.gltf(
            filepath=str(out_path),
            export_format="GLB",
            use_selection=False,
        )
    except RuntimeError as e:
        print(f"  [warn] glb export skipped: {e}")
    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    print(f"[{CARD_NAME}] blender headless start crystal={CARD_CRYSTAL[:16]}…")
    args = parse_args()
    out_dir = resolve_out_dir(args)
    print(f"[{CARD_NAME}] out_dir={out_dir}")

    ensure_clean_scene()

    # Try to load a base mesh from common input names; fall back to cube.
    mesh_path = (
        getattr(args, "mesh_3d_raw", None)
        or getattr(args, "rigged_mesh", None)
        or getattr(args, "photo", None)
    )
    obj = load_mesh(mesh_path) if isinstance(mesh_path, str) else None
    if obj is None:
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object

    pass_outputs: dict = {}
    pass_outputs.update(pass_bake_pbr(args, out_dir, obj))

    compose_pbr(pass_outputs, obj)
    glb = export_glb(out_dir)

    manifest = {
        "card_name":    CARD_NAME,
        "card_crystal": CARD_CRYSTAL,
        "rendered_ts":  RENDERED_TS,
        "out_dir":      str(out_dir),
        "passes":       pass_outputs,
        "glb":          str(glb),
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"[{CARD_NAME}] done -> {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
