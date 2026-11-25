# GENERATED from workflow_card: pump_surf_pipeline
# card_crystal: 0dbb685dc6f60af4ac9c1026124cb36d2ceddf16ca55fb6f34301cbd8199177c31a77cdb7bad5e9a5f30551866ddf1cf7869112f262e75c966e2d8cbae9931e1
# target: blender
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate pump_surf_pipeline

"""Blender headless script. Usage:
    blender --background --python pump_surf_pipeline_bake.py
"""
import bpy
import json
import sys
from pathlib import Path

CARD_CRYSTAL = "0dbb685dc6f60af4ac9c1026124cb36d2ceddf16ca55fb6f34301cbd8199177c31a77cdb7bad5e9a5f30551866ddf1cf7869112f262e75c966e2d8cbae9931e1"
CARD_NAME    = "pump_surf_pipeline"

LAYER_STACK = [
  {
    "name": "albedo",
    "source": "pass:gmm_classify",
    "blend": "base",
    "target_uniform": "u_albedo"
  },
  {
    "name": "normal",
    "source": "pass:extract_features",
    "blend": "normal_map",
    "target_uniform": "u_normal"
  },
  {
    "name": "ao",
    "source": "pass:gmm_classify",
    "blend": "multiply",
    "target_uniform": "u_ao"
  },
  {
    "name": "depth",
    "source": "pass:xgb_gate",
    "blend": "depth_uniform",
    "target_uniform": "u_depth"
  },
  {
    "name": "alpha",
    "source": "pass:xgb_gate",
    "blend": "alpha",
    "target_uniform": "u_alpha"
  },
  {
    "name": "opacity",
    "source": "literal:1.0",
    "blend": "opacity",
    "target_uniform": "u_opacity"
  },
  {
    "name": "emission",
    "source": "pass:xgb_gate",
    "blend": "additive",
    "target_uniform": "u_emission",
    "sub_layers": [
      {
        "name": "bot_density",
        "source": "pass:gmm_classify",
        "blend": "additive"
      },
      {
        "name": "human_inflow",
        "source": "pass:xgb_gate",
        "blend": "additive"
      }
    ]
  }
]

def ensure_clean_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

def add_pbr_material(name: str) -> bpy.types.Material:
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    return mat

def main():
    print(f"[pump_surf_pipeline] blender headless start — crystal={CARD_CRYSTAL[:16]}…")
    ensure_clean_scene()
    mat = add_pbr_material(f"mat_{CARD_NAME}")
    # Wire layer_stack channels onto Principled BSDF inputs:
    for layer in LAYER_STACK:
        ch = layer["name"]; src = layer["source"]; blend = layer["blend"]
        print(f"  layer {ch} - {src} ({blend})")
    print(f"[{CARD_NAME}] blender headless done")

if __name__ == "__main__":
    main()
