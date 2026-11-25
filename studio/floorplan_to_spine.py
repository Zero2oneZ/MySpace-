#!/usr/bin/env python3
"""floorplan_to_spine — PRODUCER rung: real gently-floorplan output → canonical scene_spine.json.

Closes the utilization gap: a built spatial pillar (gently-floorplan: rooms + tour) becomes a scene
the engines ALREADY consume (scene_to_godot / scene_to_blender). Floor laid in the MetaXR X-Z plane
(Y-up); floorplan +Z (depth) → MetaXR -Z (forward). Rooms = thin floor slabs sized to their rect;
tour waypoints = small markers.

  floorplan_to_spine.py <floorplan.json> [out_spine.json] [room_glb] [tour_glb]
"""
import json, sys

fp  = json.load(open(sys.argv[1]))
out = sys.argv[2] if len(sys.argv) > 2 else "/data/Projects/MySpace++/studio/scene_spine.floorplan.json"
ROOM_GLB = sys.argv[3] if len(sys.argv) > 3 else "/tmp/e2e_proof.glb"
TOUR_GLB = sys.argv[4] if len(sys.argv) > 4 else "/tmp/wrap_proof.glb"

def rect_cs(r):
    if "x_min" in r:
        return ((r["x_min"]+r["x_max"])/2, (r["z_min"]+r["z_max"])/2,
                r["x_max"]-r["x_min"], r["z_max"]-r["z_min"])
    w = r.get("w", r.get("width", 2.0)); d = r.get("d", r.get("depth", 2.0))
    return (r.get("x", 0)+w/2, r.get("z", 0)+d/2, w, d)

nodes = []; centers = {}
for room in fp.get("rooms", []):
    cx, cz, w, d = rect_cs(room["rect"])
    centers[room["id"]] = (round(cx,3), round(-cz,3))      # MetaXR floor coords (X, -Z)
    nodes.append({"id": f'room_{room["id"]}_{room.get("kind","").lower()}', "glb": ROOM_GLB,
                  "pos": [round(cx,3), 0.0, round(-cz,3)], "rot_euler_deg": [0,0,0],
                  "scale": [round(w/2,3), 0.1, round(d/2,3)], "edit_mode": "link"})

# tour = list of ROOM IDs (visit order) → camera waypoints at room centers, eye height 1.5m
camera_path = []
for rid in fp.get("tour", []):
    if isinstance(rid, int) and rid in centers:
        cx, mz = centers[rid]; camera_path.append([cx, 1.5, mz])

spine = {"_doc": f"GENERATED from gently-floorplan {sys.argv[1]} (footprint {fp.get('footprint')}). "
                 f"Producer→spine: rooms as floor slabs + camera_path = tour room-id sequence. MetaXR frame.",
         "frame": "MetaXR", "nodes": nodes, "camera_path": camera_path}
json.dump(spine, open(out, "w"), indent=1)
print(f"gently-floorplan → spine: {len(nodes)} rooms + camera_path {len(camera_path)} waypoints → {out}")
