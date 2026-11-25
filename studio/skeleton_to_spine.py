#!/usr/bin/env python3
"""skeleton_to_spine — SECOND PRODUCER: gently-probe BIND_POSE skeleton → canonical scene_spine.json.

Proves the producer pattern GENERALIZES beyond floorplan: a totally different pillar output
(a 25-joint humanoid skeleton from gently-probe walk_cycle.rs:14 BIND, MetaXR frame Y-up/meters)
becomes a scene the engines already consume. Each joint = a small marker node at its 3D position.
Source of truth: /data/Projects/gently/crates/gently-probe/src/walk_cycle.rs BIND[25].
"""
import json, sys

# BIND_POSE — 25 named joints, MetaXR frame (Y-up, -Z forward, meters), from walk_cycle.rs:14-39
JOINTS = [
    ("hips",[0.00,0.00,0.00]),("spine",[0.00,0.10,0.00]),("spine1",[0.00,0.20,0.00]),
    ("spine2",[0.00,0.30,0.00]),("neck",[0.00,0.45,0.00]),("head",[0.00,0.58,0.00]),
    ("leftShoulder",[-0.18,0.40,0.00]),("leftArm",[-0.45,0.40,0.00]),("leftForeArm",[-0.65,0.20,0.00]),
    ("leftHand",[-0.80,0.05,0.00]),("rightShoulder",[0.18,0.40,0.00]),("rightArm",[0.45,0.40,0.00]),
    ("rightForeArm",[0.65,0.20,0.00]),("rightHand",[0.80,0.05,0.00]),("leftUpLeg",[-0.10,0.00,0.00]),
    ("leftLeg",[-0.12,-0.45,0.00]),("leftFoot",[-0.13,-0.85,0.05]),("leftToeBase",[-0.13,-0.90,0.18]),
    ("rightUpLeg",[0.10,0.00,0.00]),("rightLeg",[0.12,-0.45,0.00]),("rightFoot",[0.13,-0.85,0.05]),
    ("rightToeBase",[0.13,-0.90,0.18]),("leftEye",[-0.02,0.20,0.05]),("rightEye",[0.02,0.20,0.05]),
    ("jaw",[0.00,0.18,0.05]),
]
out = sys.argv[1] if len(sys.argv) > 1 else "/data/Projects/MySpace++/studio/scene_spine.skeleton.json"
GLB = sys.argv[2] if len(sys.argv) > 2 else "/tmp/wrap_proof.glb"

nodes = [{"id": f"joint_{i}_{name}", "glb": GLB, "pos": pos, "rot_euler_deg": [0,0,0],
          "scale": [0.04,0.04,0.04], "edit_mode": "link"} for i,(name,pos) in enumerate(JOINTS)]
spine = {"_doc": "GENERATED from gently-probe walk_cycle.rs BIND_POSE (25-joint humanoid, MetaXR frame). "
                 "Second producer — proves producer→spine generalizes (skeleton, not floorplan).",
         "frame": "MetaXR", "nodes": nodes}
json.dump(spine, open(out, "w"), indent=1)
print(f"gently-probe skeleton → spine: {len(nodes)} joints → {out}")
