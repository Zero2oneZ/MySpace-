#!/usr/bin/env python3
"""stage — build an interior-design DIGITAL STAGE as a scene spine: a room shell (floor + walls) +
placed furniture + a recorded walkthrough camera path. Pure data (no GPU) — ready to render in
Godot/Blender via scene_to_*. Furniture leaves are placeholder GLBs now; Pixal3D image→3D swaps in
real generated pieces post-reboot. MetaXR frame (Y-up, meters).

  stage.py [out.json]   ·   W,D,H below = room footprint+height in meters
"""
import json, sys

W, D, H = 6.0, 5.0, 2.6                                   # room: 6m × 5m × 2.6m
CUBE = "/tmp/e2e_proof.glb"; SPHERE = "/tmp/wrap_proof.glb"; PANEL = "/tmp/texnorm.glb"
DUCK = "/data/Projects/MySpace++/studio/.venv/lib/python3.13/site-packages/gradio/media_assets/models3d/Duck.glb"

def box(id, glb, pos, scale, rot=(0,0,0)):
    return {"id": id, "glb": glb, "pos": [round(x,3) for x in pos], "rot_euler_deg": list(rot),
            "scale": [round(s,3) for s in scale], "edit_mode": "link"}

nodes = [
    # ── room shell (floor + 4 walls; cube primitive is ~2m, scale = half-extent) ──
    box("floor",  PANEL, (0, 0, 0),       (W/2, 0.05, D/2)),
    box("wall_n", CUBE,  (0, H/2, -D/2),  (W/2, H/2, 0.05)),
    box("wall_s", CUBE,  (0, H/2,  D/2),  (W/2, H/2, 0.05)),
    box("wall_e", CUBE,  (W/2, H/2, 0),   (0.05, H/2, D/2)),
    box("wall_w", CUBE,  (-W/2, H/2, 0),  (0.05, H/2, D/2)),
    # ── furniture (placeholder leaves; Pixal3D image→3D replaces with real pieces) ──
    box("sofa",   CUBE,   (-1.5, 0.4, -1.5), (0.9, 0.4, 0.45)),
    box("table",  CUBE,   (0, 0.25, 0),      (0.6, 0.25, 0.4)),
    box("lamp",   SPHERE, (1.8, 0.6, -1.8),  (0.2, 0.6, 0.2)),
    box("rug",    PANEL,  (0, 0.02, 0),      (1.4, 0.02, 1.0)),
    box("prop",   DUCK,   (1.5, 0.0, 1.5),   (0.01, 0.01, 0.01), (0, 200, 0)),
]
# ── recorded walkthrough: enter at the door, sweep the room, face center, exit ──
camera_path = [
    [0, 1.5,  D/2-0.3],   # at the south door
    [-1.5, 1.5, 0],       # past the sofa
    [0, 1.5, -D/2+0.5],   # north wall, looking back
    [1.5, 1.5, 0],        # past the lamp
    [0, 1.5,  D/2-0.3],   # back to the door
]
stage = {"_doc": f"DIGITAL STAGE — interior room {W}×{D}×{H}m: shell + furniture + recorded walkthrough. "
                 f"MetaXR. Furniture = placeholder GLBs (Pixal3D image→3D swaps real pieces).",
         "frame": "MetaXR", "nodes": nodes, "camera_path": camera_path}
out = sys.argv[1] if len(sys.argv) > 1 else "/data/Projects/MySpace++/studio/scene_spine.stage.json"
json.dump(stage, open(out, "w"), indent=1)
shell = [n["id"] for n in nodes if n["id"] in ("floor","wall_n","wall_s","wall_e","wall_w")]
furn  = [n["id"] for n in nodes if n["id"] not in shell]
print(f"DIGITAL STAGE → {out}")
print(f"  room shell: {shell}")
print(f"  furniture:  {furn}")
print(f"  walkthrough: {len(camera_path)} waypoints (eye 1.5m), closed loop")
