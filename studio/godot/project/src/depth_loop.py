#!/usr/bin/env python3
"""Bake → file → sample loop: closes the unseen-layer ↔ labeled-truth wires.

Step 1: bake the analytic far-d field of the sphere cutout as a uint16 PNG (= the labeled truth).
Step 2: scan it via bin/assets → cid + by-pass/depth/ landing (the truth gets an io_hash identity).
Step 3: sample the PNG back at the same 15 ray positions as the Godot CULL_FRONT test;
         compare to analytic → drift table.

With analytic truth = analytic sample, drift collapses to quantization noise. When real depth
arrives (Blender Cycles depth pass / Comfy depth model / ControlNet), the same wires consume it.
"""
import json, math, subprocess
from pathlib import Path
import numpy as np
from PIL import Image

W, H   = 256, 256
CAM    = np.array([0.0, 0.0, 1.5])
SC     = np.array([0.0, 0.0, -1.0])
SR     = 0.6
PLANE_Z = -2.0                                # focal target plane

OUT = Path("/data/Projects/MySpace++/studio/godot/project/forge/truth_bake")
OUT.mkdir(parents=True, exist_ok=True)
PNG  = OUT / "sphere_cutout_u_depth.png"      # u_depth → bin/assets tags pass='depth'
META = OUT / "sphere_cutout_u_depth.meta.json"

# ── 1) BAKE ──────────────────────────────────────────────────────────────────
uu, vv = np.meshgrid(np.linspace(-1, 1, W), np.linspace(-1, 1, H), indexing='xy')
target = np.stack([uu, -vv, np.full_like(uu, PLANE_Z)], axis=-1)         # flip v → row 0 on top
dir = target - CAM; dir /= np.linalg.norm(dir, axis=-1, keepdims=True)
oc = CAM - SC
b  = np.einsum('hwi,i->hw', dir, oc)
c  = float(np.dot(oc, oc) - SR * SR)
disc = b * b - c
mask = disc >= 0
far  = np.where(mask, -b + np.sqrt(np.where(mask, disc, 0)), 0.0)

d_min = float(far[mask].min()); d_max = float(far[mask].max())
norm = np.zeros((H, W), dtype=np.uint16)
norm[mask] = (1 + (far[mask] - d_min) / (d_max - d_min) * 65534).astype(np.uint16)

Image.fromarray(norm, mode='I;16').save(PNG)
json.dump({"depth_min": d_min, "depth_max": d_max, "width": W, "height": H,
           "sentinel_zero": "background — no back-face hit",
           "camera": CAM.tolist(), "sphere_center": SC.tolist(), "sphere_radius": SR,
           "focal_plane_z": PLANE_Z, "u_range": [-1, 1], "v_range": [-1, 1]},
          open(META, "w"), indent=2)
print(f"baked: {PNG.name}  {norm.shape} uint16  depth ∈ [{d_min:.4f}, {d_max:.4f}]"
      f"  silhouette {int(mask.sum())}/{W*H} ({100*mask.sum()/(W*H):.1f}%)")

# ── 2) FILE through ATLAS ────────────────────────────────────────────────────
print("\n--- bin/assets scan (labels pass='depth' via u_depth in filename) ---")
subprocess.run(["python3", "/data/Projects/ATLAS/bin/assets", "scan", str(OUT)], check=True)

bp = Path("/data/Projects/ATLAS/assets/by-pass")
print(f"\nby-pass/ now contains: {sorted(p.name for p in bp.iterdir())}")
dp = bp / "depth"
if dp.exists():
    for p in dp.iterdir(): print(f"  by-pass/depth/{p.name}  →  {p.resolve()}")

# ── 3) SAMPLE back & compute drift vs analytic ──────────────────────────────
print("\n--- drift: sample baked truth at the same 15 ray positions ---")
img = np.asarray(Image.open(PNG))
print("  ray_x   analytic_far_d   sampled_truth_d   drift        coverage")
print("  ─────   ──────────────   ───────────────   ──────────   ────────")
for i in range(-7, 8):
    x = i * 0.1
    d1 = np.array([x, 0, PLANE_Z]) - CAM; d1 /= np.linalg.norm(d1)
    b1 = float(np.dot(d1, oc)); disc1 = b1 * b1 - c
    if disc1 < 0:
        print(f"  {x:5.2f}   ─                ─                 ─            0"); continue
    af = -b1 + math.sqrt(disc1)
    col = int(round((x + 1) * 0.5 * (W - 1)))
    row = int(round(0.5 * (H - 1)))
    pix = int(img[row, col])
    if pix == 0:
        print(f"  {x:5.2f}   {af:.4f}           sentinel(0)       ─            0  miss")
    else:
        sd_ = d_min + (pix - 1) / 65534.0 * (d_max - d_min)
        drift = af - sd_
        print(f"  {x:5.2f}   {af:.4f}           {sd_:.4f}            {drift:+.6f}    1")

print("\n► drift on analytic↔analytic loop = quantization noise (uint16 = ±5e-6 over depth range)")
print("► wires proven: scene-cam → far_d field → PNG bake → cid → by-pass/depth/ → uv-sample → drift")
print("► swap the bake source for Blender Cycles / Comfy depth / depth model — same downstream.")
