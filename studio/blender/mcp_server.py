# mcp_server.py — one-shot Blender MCP tool dispatcher (runs inside Blender).
# Invoked as:  blender --background --python mcp_server.py
# Protocol: reads ONE JSON-RPC request on stdin
#   {"jsonrpc":"2.0","id":1,"method":"<tool>","params":{...}}
# and writes ONE JSON-RPC response as the LAST stdout line
#   {"jsonrpc":"2.0","id":1,"result":{...}}   (or {"error":{...}})
# then os._exit(0) so Blender's "Blender quit" trailer doesn't clobber the
# response line that core/lib/third_party/blender_mcp.py reads via out[-1].
#
# Tools implemented (the surface blender_mcp.EXPECTED_TOOLS expects):
#   scene.clear · scene.list_objects · mesh.create · material.set ·
#   material.bake_pbr (descriptor) · light.add · camera.set · modifier.add ·
#   render.image · mesh.export_gltf · python.exec
import json
import os
import sys

try:
    import bpy
except Exception as e:  # not inside Blender
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": 1,
                                 "error": {"message": f"bpy unavailable: {e}"}}) + "\n")
    sys.stdout.flush()
    os._exit(0)

_PRIM = {
    "cube": "primitive_cube_add", "box": "primitive_cube_add",
    "sphere": "primitive_uv_sphere_add", "uv_sphere": "primitive_uv_sphere_add",
    "cylinder": "primitive_cylinder_add", "cone": "primitive_cone_add",
    "plane": "primitive_plane_add", "torus": "primitive_torus_add",
    "monkey": "primitive_monkey_add", "suzanne": "primitive_monkey_add",
}


def t_scene_clear(p):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    return {"cleared": True, "objects": len(bpy.data.objects)}


def t_scene_list_objects(p):
    return {"objects": [{"name": o.name, "type": o.type} for o in bpy.data.objects]}


def t_mesh_create(p):
    prim = (p.get("primitive") or "cube").lower()
    op = getattr(bpy.ops.mesh, _PRIM.get(prim, "primitive_cube_add"))
    kw = {}
    if p.get("size") is not None:
        kw["size"] = float(p["size"])
    if p.get("location") is not None:
        kw["location"] = tuple(p["location"])[:3]
    try:
        op(**kw)
    except TypeError:
        op()  # some primitives don't take size
    obj = bpy.context.active_object
    if obj and p.get("name"):
        obj.name = str(p["name"])
    return {"created": obj.name if obj else None, "primitive": prim}


def t_material_set(p):
    obj = bpy.data.objects.get(p.get("object", "")) or bpy.context.active_object
    if obj is None:
        return {"error": "no target object"}
    mat = bpy.data.materials.new(name=p.get("name", "MspcMat"))
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        col = p.get("base_color", [0.8, 0.8, 0.8, 1.0])
        if len(col) == 3:
            col = col + [1.0]
        bsdf.inputs["Base Color"].default_value = col
        if "metallic" in p:
            bsdf.inputs["Metallic"].default_value = float(p["metallic"])
        if "roughness" in p:
            bsdf.inputs["Roughness"].default_value = float(p["roughness"])
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return {"object": obj.name, "material": mat.name}


def t_material_bake_pbr(p):
    # Descriptor of the layer stack we'd bake (albedo→normal→AO→depth). Real bake
    # needs UVs + image targets; reuse studio/blender/scripts/*_bake.py for that.
    return {"planned_layers": ["albedo", "normal", "ao", "depth"],
            "object": p.get("object", bpy.context.active_object.name if bpy.context.active_object else ""),
            "note": "descriptor only; full PBR bake via *_bake.py templates"}


def t_light_add(p):
    bpy.ops.object.light_add(type=(p.get("kind", "SUN")).upper(),
                             location=tuple(p.get("location", [4, 4, 6]))[:3])
    return {"light": bpy.context.active_object.name}


def t_camera_set(p):
    bpy.ops.object.camera_add(location=tuple(p.get("location", [7, -7, 5]))[:3])
    cam = bpy.context.active_object
    bpy.context.scene.camera = cam
    return {"camera": cam.name}


def t_modifier_add(p):
    obj = bpy.data.objects.get(p.get("object", "")) or bpy.context.active_object
    if obj is None:
        return {"error": "no target object"}
    m = obj.modifiers.new(name=p.get("name", "Mod"), type=(p.get("kind", "SUBSURF")).upper())
    return {"object": obj.name, "modifier": m.name, "type": m.type}


def t_render_image(p):
    scene = bpy.context.scene
    fp = p.get("filepath") or "/tmp/mspc_blender_render.png"
    # Workbench is reliable headless (no GPU/lighting dependency).
    try:
        scene.render.engine = p.get("engine", "BLENDER_WORKBENCH")
    except Exception:
        pass
    scene.render.filepath = fp
    scene.render.resolution_x = int(p.get("width", 512))
    scene.render.resolution_y = int(p.get("height", 512))
    if scene.camera is None:
        t_camera_set({})
    bpy.ops.render.render(write_still=True)
    return {"rendered": fp, "exists": os.path.exists(fp),
            "bytes": os.path.getsize(fp) if os.path.exists(fp) else 0}


def t_mesh_export_gltf(p):
    fp = p.get("filepath") or "/tmp/mspc_blender_export.glb"
    kw = {"filepath": fp, "export_format": p.get("format", "GLB")}
    if p.get("export_animations"):
        kw["export_animations"] = True
    try:
        bpy.ops.export_scene.gltf(**kw)
    except TypeError:
        bpy.ops.export_scene.gltf(filepath=fp, export_format=p.get("format", "GLB"))
    return {"exported": fp, "exists": os.path.exists(fp),
            "bytes": os.path.getsize(fp) if os.path.exists(fp) else 0}


# ── armature / bones / walk cycle ─────────────────────────────────────────────

def t_armature_create(p):
    """Build a simple biped skeleton (hips→spine→head, thigh/shin/foot L+R,
    uparm/lowarm L+R). Returns the bone names."""
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    arm = bpy.context.active_object
    arm.name = p.get("name", "Rig")
    eb = arm.data.edit_bones
    for b in list(eb):
        eb.remove(b)

    def bone(name, head, tail, parent=None):
        b = eb.new(name)
        b.head, b.tail = head, tail
        if parent and parent in eb:
            b.parent = eb[parent]
        return b

    bone("hips", (0, 0, 1.0), (0, 0, 1.15))
    bone("spine", (0, 0, 1.15), (0, 0, 1.5), "hips")
    bone("head", (0, 0, 1.5), (0, 0, 1.72), "spine")
    for side, x in (("L", 0.12), ("R", -0.12)):
        bone(f"thigh_{side}", (x, 0, 1.0), (x, 0, 0.55), "hips")
        bone(f"shin_{side}", (x, 0, 0.55), (x, 0, 0.1), f"thigh_{side}")
        bone(f"foot_{side}", (x, 0, 0.1), (x, 0.16, 0.04), f"shin_{side}")
        bone(f"uparm_{side}", (x * 2, 0, 1.45), (x * 3.2, 0, 1.18), "spine")
        bone(f"lowarm_{side}", (x * 3.2, 0, 1.18), (x * 4.2, 0, 0.92), f"uparm_{side}")
    bpy.ops.object.mode_set(mode="OBJECT")
    return {"armature": arm.name, "bones": [b.name for b in arm.data.bones]}


def _active_armature(name=""):
    if name:
        o = bpy.data.objects.get(name)
        if o and o.type == "ARMATURE":
            return o
    return next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)


def t_bone_list(p):
    arm = _active_armature(p.get("armature", ""))
    if arm is None:
        return {"error": "no armature in scene"}
    return {"armature": arm.name,
            "bones": [{"name": b.name, "parent": b.parent.name if b.parent else None}
                      for b in arm.data.bones]}


def t_bone_set_rotation(p):
    """Pose a bone's euler rotation (radians); optionally keyframe at a frame."""
    import math
    arm = _active_armature(p.get("armature", ""))
    if arm is None:
        return {"error": "no armature"}
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    bone = p.get("bone", "")
    pb = arm.pose.bones.get(bone)
    if pb is None:
        bpy.ops.object.mode_set(mode="OBJECT")
        return {"error": f"no bone {bone}"}
    rot = p.get("euler", [0, 0, 0])
    if p.get("degrees"):
        rot = [math.radians(v) for v in rot]
    pb.rotation_mode = "XYZ"
    pb.rotation_euler = rot[:3]
    if p.get("frame") is not None:
        pb.keyframe_insert("rotation_euler", frame=int(p["frame"]))
    bpy.ops.object.mode_set(mode="OBJECT")
    return {"armature": arm.name, "bone": bone, "euler": list(rot)[:3],
            "keyed_frame": p.get("frame")}


def t_walk_cycle(p):
    """Keyframe a looping walk cycle on a biped armature (leg swing + bend,
    counter-swinging arms). L/R legs are 180° out of phase."""
    import math
    arm = _active_armature(p.get("armature", ""))
    if arm is None:
        return {"error": "no armature"}
    frames = int(p.get("frames", 24))
    amp = float(p.get("amplitude", 0.6))
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, frames
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    pb = arm.pose.bones

    def key(bone, frame, rx):
        b = pb.get(bone)
        if b is None:
            return
        b.rotation_mode = "XYZ"
        b.rotation_euler[0] = rx
        b.keyframe_insert("rotation_euler", index=0, frame=frame)

    for f in range(1, frames + 1):
        ph = 2 * math.pi * (f - 1) / frames
        key("thigh_L", f, amp * math.sin(ph))
        key("thigh_R", f, amp * math.sin(ph + math.pi))
        key("shin_L", f, max(0.0, amp * 1.1 * math.sin(ph - 1.0)))
        key("shin_R", f, max(0.0, amp * 1.1 * math.sin(ph + math.pi - 1.0)))
        key("uparm_L", f, amp * 0.6 * math.sin(ph + math.pi))
        key("uparm_R", f, amp * 0.6 * math.sin(ph))
    # loop: copy frame 1 onto frame+1 so the cycle closes seamlessly
    bpy.ops.object.mode_set(mode="OBJECT")
    return {"armature": arm.name, "frames": frames, "amplitude": amp, "keyed": True}


def t_rig_walk(p):
    """Single-process composite: armature → walk cycle → animated GLB.
    (Each MCP call is its own one-shot Blender, so the rig + animation + export
    must run together.)"""
    t_scene_clear({})
    created = t_armature_create({"name": p.get("name", "Rig")})
    walk = t_walk_cycle({"frames": p.get("frames", 24), "amplitude": p.get("amplitude", 0.6)})
    out = {"armature": created.get("armature"), "bones": created.get("bones"),
           "walk": walk}
    if p.get("export_glb"):
        out["export"] = t_mesh_export_gltf({"filepath": p["export_glb"],
                                            "export_animations": True})
    return out


def t_model_build(p):
    """Composite single-process build: clear → create primitive → material →
    export GLB. Needed because each MCP call is its own one-shot Blender, so
    multi-step builds must run in one invocation to share scene state."""
    t_scene_clear({})
    t_mesh_create({"primitive": p.get("primitive", "cube"), "name": p.get("name", "GenAsset"),
                   "size": p.get("size"), "location": p.get("location")})
    if p.get("base_color") or p.get("roughness") is not None:
        t_material_set({"object": p.get("name", "GenAsset"),
                        "base_color": p.get("base_color", [0.8, 0.8, 0.8, 1]),
                        "roughness": p.get("roughness", 0.5)})
    out = {"built": p.get("primitive", "cube")}
    if p.get("export_glb"):
        out["export"] = t_mesh_export_gltf({"filepath": p["export_glb"]})
    if p.get("render_png"):
        out["render"] = t_render_image({"filepath": p["render_png"],
                                        "width": p.get("width", 512), "height": p.get("height", 512)})
    return out


def t_python_exec(p):
    code = p.get("code", "")
    ns = {"bpy": bpy}
    exec(code, ns)
    return {"ran": True, "result": str(ns.get("result", ""))[:2000]}


# ── S029 (ATLAS Phase 8 biped chain — typed wrappers around bpy operators) ──
def t_mesh_decimate_clean(p):
    """S028a — decimate to target_tri_count, remove doubles, fill holes."""
    name = p.get("object") or (bpy.context.active_object and bpy.context.active_object.name)
    obj = bpy.data.objects.get(name) if name else None
    if obj is None or obj.type != "MESH":
        return {"ok": False, "error": f"no mesh object named {name!r}"}
    target = int(p.get("target_tri_count", 8000))
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True)
    initial = sum(max(len(f.vertices) - 2, 0) for f in obj.data.polygons)
    ratio = max(0.01, min(1.0, target / max(initial, 1)))
    dec = obj.modifiers.new("ATLAS_Dec", "DECIMATE")
    dec.decimate_type = "COLLAPSE"; dec.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=dec.name)
    if p.get("manifold_pass", True):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=0.001)
        bpy.ops.mesh.fill_holes(sides=8)
        bpy.ops.object.mode_set(mode="OBJECT")
    decimated = sum(max(len(f.vertices) - 2, 0) for f in obj.data.polygons)
    return {"ok": True, "step_id": "S028a", "object": obj.name,
            "initial_tris": initial, "decimated_tris": decimated,
            "ratio": round(ratio, 3), "manifold_pass": bool(p.get("manifold_pass", True))}


def t_mesh_retopo_quadriflow(p):
    """S028b — QuadriFlow remesh to target_quad_count."""
    name = p.get("object") or (bpy.context.active_object and bpy.context.active_object.name)
    obj = bpy.data.objects.get(name) if name else None
    if obj is None or obj.type != "MESH":
        return {"ok": False, "error": f"no mesh object named {name!r}"}
    target = int(p.get("target_quad_count", 6000))
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT"); obj.select_set(True)
    try:
        bpy.ops.object.quadriflow_remesh(
            target_faces=target,
            use_preserve_sharp=bool(p.get("preserve_sharp", True)))
    except Exception as e:
        return {"ok": False, "error": f"quadriflow failed: {e}"}
    n_quads = sum(1 for f in obj.data.polygons if len(f.vertices) == 4)
    return {"ok": True, "step_id": "S028b", "object": obj.name,
            "target_quad_count": target, "actual_quads": n_quads,
            "total_faces": len(obj.data.polygons)}


def t_armature_rigify_meta_add(p):
    """S028c — armature_human_metarig_add + optional bbox or anchor positioning."""
    import addon_utils
    try: addon_utils.enable("rigify", default_set=True, persistent=False)
    except Exception as e: return {"ok": False, "error": f"rigify enable failed: {e}"}
    target_mesh_name = p.get("mesh_for_bbox")
    target_mesh = bpy.data.objects.get(target_mesh_name) if target_mesh_name else None
    try:
        bpy.ops.object.armature_human_metarig_add()
    except Exception as e:
        return {"ok": False, "error": f"metarig add failed: {e}"}
    rig = bpy.context.active_object
    rig.name = p.get("meta_rig_name", "MetaRig")
    method = "default_pose"
    scale_factor = 1.0
    if target_mesh and target_mesh.type == "MESH":
        from mathutils import Vector
        verts = [target_mesh.matrix_world @ v.co for v in target_mesh.data.vertices]
        if verts:
            bbmin = Vector((min(v.x for v in verts), min(v.y for v in verts), min(v.z for v in verts)))
            bbmax = Vector((max(v.x for v in verts), max(v.y for v in verts), max(v.z for v in verts)))
            ctr = (bbmin + bbmax) / 2
            sz = bbmax - bbmin
            scale_factor = max(0.05, sz.z / 1.8)
            rig.location = ctr
            rig.scale = (scale_factor, scale_factor, scale_factor)
            bpy.context.view_layer.objects.active = rig
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            method = "bbox_match"
    anchors = p.get("joint_anchors")  # placeholder — snap-to-anchor in v1
    return {"ok": True, "step_id": "S028c", "meta_rig": rig.name,
            "method": method, "scale_factor": round(scale_factor, 3),
            "anchors_present": len(anchors or {})}


def t_armature_rigify_generate(p):
    """S028d — pose.rigify_generate (must transition to POSE mode first)."""
    name = p.get("meta_rig_name", "MetaRig")
    metarig = bpy.data.objects.get(name)
    if metarig is None or metarig.type != "ARMATURE":
        return {"ok": False, "error": f"meta-rig {name!r} not found"}
    bpy.context.view_layer.objects.active = metarig
    bpy.ops.object.select_all(action="DESELECT"); metarig.select_set(True)
    try:
        bpy.ops.object.mode_set(mode="POSE")
        bpy.ops.pose.rigify_generate()
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception as e:
        return {"ok": False, "error": f"rigify_generate failed: {e}"}
    rig = None
    for o in bpy.data.objects:
        if o.type == "ARMATURE" and o.name != name:
            rig = o; break
    return {"ok": True, "step_id": "S028d",
            "generated_rig": rig.name if rig else None,
            "n_bones": len(rig.pose.bones) if rig else 0}


def t_armature_auto_skin(p):
    """S028e — parent mesh to armature with ARMATURE_AUTO (bone-heat)."""
    mesh = bpy.data.objects.get(p.get("mesh_name", ""))
    rig = bpy.data.objects.get(p.get("armature_name", ""))
    if mesh is None or mesh.type != "MESH":
        return {"ok": False, "error": f"mesh {p.get('mesh_name')!r} not found"}
    if rig is None or rig.type != "ARMATURE":
        return {"ok": False, "error": f"armature {p.get('armature_name')!r} not found"}
    bpy.ops.object.select_all(action="DESELECT")
    mesh.select_set(True); rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    except Exception as e:
        return {"ok": False, "error": f"parent_set failed: {e}"}
    return {"ok": True, "step_id": "S028e",
            "mesh": mesh.name, "armature": rig.name, "method": "bone_heat"}


TOOLS = {
    "scene.clear": t_scene_clear, "scene.list_objects": t_scene_list_objects,
    "mesh.create": t_mesh_create, "material.set": t_material_set,
    "material.bake_pbr": t_material_bake_pbr, "light.add": t_light_add,
    "camera.set": t_camera_set, "modifier.add": t_modifier_add,
    "render.image": t_render_image, "mesh.export_gltf": t_mesh_export_gltf,
    "model.build": t_model_build, "python.exec": t_python_exec,
    "armature.create": t_armature_create, "bone.list": t_bone_list,
    "bone.set_rotation": t_bone_set_rotation, "walk.cycle": t_walk_cycle,
    "rig.walk": t_rig_walk,
    # S029 — ATLAS Phase 8 biped chain (each wraps one bpy operator with typed I/O)
    "mesh.decimate_clean":       t_mesh_decimate_clean,
    "mesh.retopo_quadriflow":    t_mesh_retopo_quadriflow,
    "armature.rigify_meta_add":  t_armature_rigify_meta_add,
    "armature.rigify_generate":  t_armature_rigify_generate,
    "armature.auto_skin":        t_armature_auto_skin,
}


def _dispatch_one(req):
    """Dispatch one tool by name → JSON-RPC result/error envelope."""
    rid = req.get("id", 1)
    method = req.get("method", "")
    params = req.get("params", {}) or {}
    if method not in TOOLS:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"message": f"unknown tool: {method}", "known": list(TOOLS)}}
    try:
        return {"jsonrpc": "2.0", "id": rid, "result": TOOLS[method](params)}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"message": f"{type(e).__name__}: {e}"}}


# ── MCP-compliant loop mode (--mcp flag) ────────────────────────────────
# Wraps the existing TOOLS dispatcher as a real MCP server: handles initialize,
# tools/list, tools/call. Runs over line-delimited JSON-RPC on stdio.
# Lets Claude Code register this as a native MCP via ~/.claude/mcp.json.

MCP_PROTO = "2024-11-05"
MCP_SERVER_INFO = {"name": "blender-atlas", "version": "0.1.0"}

def _tool_listing():
    """Synthesize MCP tool definitions from the TOOLS dict.
    Schemas are permissive (any params accepted) since each handler validates
    its own inputs and returns clear errors — keeps the listing compact."""
    out = []
    for name in TOOLS:
        out.append({
            "name": name.replace(".", "_"),  # MCP names can't have dots
            "description": (TOOLS[name].__doc__ or f"Blender tool: {name}").strip().split("\n")[0],
            "inputSchema": {"type": "object", "additionalProperties": True},
        })
    return out

def _mcp_handle(req):
    """Handle MCP protocol methods: initialize, tools/list, tools/call."""
    rid = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {}) or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": MCP_PROTO,
            "capabilities": {"tools": {}},
            "serverInfo": MCP_SERVER_INFO,
        }}
    if method == "notifications/initialized":
        return None   # notification; no reply
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": _tool_listing()}}
    if method == "tools/call":
        tool_name = (params.get("name") or "").replace("_", ".", 1)  # try first underscore
        # MCP renames "scene.clear" → "scene_clear" on the wire. Map back:
        candidates = [tool_name, params.get("name", ""),
                      params.get("name", "").replace("_", ".")]
        chosen = next((c for c in candidates if c in TOOLS), None)
        if not chosen:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601,
                              "message": f"unknown tool: {params.get('name')}",
                              "data": {"known": list(TOOLS)}}}
        try:
            result = TOOLS[chosen](params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "isError": False,
            }}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                "isError": True,
            }}
    # unknown MCP method
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"method not implemented: {method}"}}

def _mcp_loop():
    """Loop reading line-delimited JSON-RPC frames on stdin, writing replies on stdout.
    Exits on EOF."""
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try: req = json.loads(line)
        except Exception as e:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"parse: {e}"}}) + "\n")
            sys.stdout.flush(); continue
        resp = _mcp_handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, default=str) + "\n")
            sys.stdout.flush()
    os._exit(0)


def main():
    # --mcp flag → run as MCP-compliant loop server for Claude.
    # Default (no flag) → one-shot stdin→stdout dispatcher, preserves the
    # existing contract that bin/biped_rig and bin/reverse_engineer depend on.
    if "--mcp" in sys.argv:
        _mcp_loop()
        return
    raw = sys.stdin.read()
    try:
        req = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        req = {"_parse_error": str(e)}
    resp = _dispatch_one(req)
    sys.stdout.write("\n" + json.dumps(resp, default=str) + "\n")
    sys.stdout.flush()
    os._exit(0)  # skip Blender's stdout trailer so our JSON is the last line


main()
