# GENERATED from workflow_card: photo_to_avatar_rigged
# card_crystal: 04c7865e2553a0eed117aa75dd95ec7e45eec7ef8ee024d7a61612aa3891e673daa68368ec54a7fcdbac34ec605c746c076c0d90cddc5cc2dab7361b0074fb6b
# target: blender
# schema: workflow_card_v0
# DO NOT EDIT BY HAND — regenerate via: cc workflow generate photo_to_avatar_rigged

"""Blender headless script. Usage:
    blender --background --python avatar_rigged_bake.py
"""
import bpy
import json
import sys
from pathlib import Path

CARD_CRYSTAL = "04c7865e2553a0eed117aa75dd95ec7e45eec7ef8ee024d7a61612aa3891e673daa68368ec54a7fcdbac34ec605c746c076c0d90cddc5cc2dab7361b0074fb6b"
CARD_NAME    = "photo_to_avatar_rigged"

LAYER_STACK = [
  {
    "name": "albedo",
    "source": "pass:bake_pbr",
    "blend": "base",
    "target_uniform": "u_albedo"
  },
  {
    "name": "normal",
    "source": "pass:bake_pbr",
    "blend": "normal_map",
    "target_uniform": "u_normal"
  },
  {
    "name": "ao",
    "source": "pass:bake_pbr",
    "blend": "multiply",
    "target_uniform": "u_ao"
  },
  {
    "name": "depth",
    "source": "pass:depth",
    "blend": "depth_uniform",
    "target_uniform": "u_depth"
  },
  {
    "name": "alpha",
    "source": "pass:faceswap_lock",
    "blend": "alpha",
    "target_uniform": "u_alpha"
  },
  {
    "name": "opacity",
    "source": "literal:1.0",
    "blend": "opacity",
    "target_uniform": "u_opacity"
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
    print(f"[photo_to_avatar_rigged] blender headless start — crystal={CARD_CRYSTAL[:16]}…")
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
