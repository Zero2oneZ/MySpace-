# GENERATED from workflow_card: realestate_walkthrough_full
# card_crystal: 4b5b9c4a5d3b5600c71da2e80b4346997284960d3202f11cb32ed05db348219fca89e0b61a08a18550d9d8db72d2ea8297d367804789e33bf0c239f88b3ef835
# target: blender
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate realestate_walkthrough_full

"""Blender headless script. Usage:
    blender --background --python realestate_walkthrough_full_bake.py
"""
import bpy
import json
import sys
from pathlib import Path

CARD_CRYSTAL = "4b5b9c4a5d3b5600c71da2e80b4346997284960d3202f11cb32ed05db348219fca89e0b61a08a18550d9d8db72d2ea8297d367804789e33bf0c239f88b3ef835"
CARD_NAME    = "realestate_walkthrough_full"

LAYER_STACK = [
  {
    "name": "albedo",
    "source": "pass:embed_local_svgs",
    "blend": "base",
    "target_uniform": "u_albedo"
  },
  {
    "name": "normal",
    "source": "pass:blender_assemble",
    "blend": "normal_map",
    "target_uniform": "u_normal"
  },
  {
    "name": "ao",
    "source": "pass:blender_assemble",
    "blend": "multiply",
    "target_uniform": "u_ao"
  },
  {
    "name": "depth",
    "source": "pass:spatial_anchor_room",
    "blend": "depth_uniform",
    "target_uniform": "u_depth"
  },
  {
    "name": "alpha",
    "source": "literal:1.0",
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
    "source": "pass:extract_lights_from_shapes",
    "blend": "additive",
    "target_uniform": "u_emission"
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
    print(f"[realestate_walkthrough_full] blender headless start — crystal={CARD_CRYSTAL[:16]}…")
    ensure_clean_scene()
    mat = add_pbr_material(f"mat_{CARD_NAME}")
    # Wire layer_stack channels onto Principled BSDF inputs:
    for layer in LAYER_STACK:
        ch = layer["name"]; src = layer["source"]; blend = layer["blend"]
        print(f"  layer {ch} - {src} ({blend})")
    # bake passes were declared by the card — wire actual bake nodes per layer here
    print(f"[{CARD_NAME}] blender headless done")

if __name__ == "__main__":
    main()
