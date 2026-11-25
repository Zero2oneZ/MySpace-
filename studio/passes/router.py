"""passes/router.py — producer router for the pass decomposition pipeline.

The DECOMPOSE pipeline fans a single source image out across a fixed set of PASSES
(mask, depth, normal, mesh, ...). Each pass has one-or-more PRODUCERS — concrete
models or tools that can synthesize that pass. The router picks the cheapest
producer that fits the available VRAM budget at the requested quality tier.

Pattern: source image → fan-out → producer(pass) → output filed via bin/assets scan.
The PASS_TOKENS dict in /data/Projects/ATLAS/bin/assets auto-files the producer's
output under by-pass/<pass>/ by filename token — so producers MUST name outputs
like "<source_cid>_<pass-token>_<short>.<ext>" (e.g. "_mask_", "_depth_", "_normal_").

Quality tiers:
  fast     — pick producer with lowest gpu_sec_est
  default  — cheapest-that-fits
  hero     — prefer highest-VRAM (= usually highest-quality) producer

Authored for step S014 (matte producer wired end-to-end). S015/S016 will use the
same scaffold for depth + mesh.
"""

from __future__ import annotations
import os
from typing import Dict, List, Optional


def _birefnet_runtime_available() -> bool:
    """S014b: BiRefNet lives in /tmp/birefnet-venv (torch + transformers).

    Replaces CorridorKey as the default matte producer for stills — CorridorKey
    silently failed on photographic stills with already-near-white backgrounds
    (cyber-rabbit mask 472b017130b715c5 was nearly all-transparent). Attestation
    pattern mirrors depthpro/sf3d/yolopose/marigold: venv python + runner +
    weights all on disk."""
    return all(os.path.exists(p) for p in (
        "/tmp/birefnet-venv/bin/python",
        "/data/Projects/ATLAS/bin/_decompose_mask_runner.py",
        "/home/tom/models/ZhengPeng7_BiRefNet/model.safetensors",
    ))


def _depthpro_runtime_available() -> bool:
    """S015: depthpro lives in /tmp/depthpro-venv (torch+CUDA wheels). The parent
    process never imports torch — we attest availability by checking the venv
    interpreter, the runner script, and the .pt weights are all on disk."""
    return all(os.path.exists(p) for p in (
        "/tmp/depthpro-venv/bin/python",
        "/data/Projects/ATLAS/bin/_decompose_depth_runner.py",
        "/home/tom/models/apple_DepthPro/depth_pro.pt",
    ))


def _sf3d_runtime_available() -> bool:
    """S016: stable-fast-3d lives in /tmp/sf3d-venv (torch+sf3d source tree).
    Same attestation pattern as depthpro: venv python + runner + weights + the
    cloned source dir with its built C++ extensions must all be on disk."""
    return all(os.path.exists(p) for p in (
        "/tmp/sf3d-venv/bin/python",
        "/data/Projects/ATLAS/bin/_decompose_mesh_runner.py",
        "/home/tom/models/stable-fast-3d/model.safetensors",
        "/tmp/sf3d-src/sf3d/system.py",
        "/tmp/sf3d-src/texture_baker/texture_baker/_C.cpython-313-x86_64-linux-gnu.so",
        "/tmp/sf3d-src/uv_unwrapper/uv_unwrapper/_C.cpython-313-x86_64-linux-gnu.so",
    ))


def _trellis_runtime_available() -> bool:
    """S016b: Pixal3D (TRELLIS hero) reuses its OWN bundled venv at
    /home/tom/models/Pixal3D/env (the model author pre-built torch + sdpa +
    natten + trellis2 + o_voxel — no /tmp/* venv). Attestation: that python,
    the ATLAS runner, the Pixal3D source tree, and the Pixal3D-T weights ckpts
    dir must all be on disk. The LD_LIBRARY_PATH dance happens inside the
    wrapper at call time, so we don't subprocess-probe import here."""
    return all(os.path.exists(p) for p in (
        "/home/tom/models/Pixal3D/env/bin/python",
        "/data/Projects/ATLAS/bin/_decompose_mesh_trellis_runner.py",
        "/home/tom/models/Pixal3D/trellis2/pipelines/pixal3d_image_to_3d.py",
        "/home/tom/models/TencentARC_Pixal3D/pipeline.json",
        "/home/tom/models/TencentARC_Pixal3D/ckpts",
    ))


def _yolopose_runtime_available() -> bool:
    """S018: yolov8-pose lives in /tmp/yolopose-venv (ultralytics + torch).
    Attestation: venv python + runner + weights all on disk. The runner emits
    a skeleton-overlay PNG and sidecar COCO17 keypoints JSON."""
    return all(os.path.exists(p) for p in (
        "/tmp/yolopose-venv/bin/python",
        "/data/Projects/ATLAS/bin/_decompose_pose_runner.py",
        "/home/tom/models/ultralytics-yolov8-pose/yolov8n-pose.pt",
    ))


def _sapiens_pretrain_available() -> bool:
    """S018: Sapiens-1b pretrain backbone exists on disk but ships no pose
    head — needs the Sapiens-pose checkpoint from facebookresearch/sapiens.
    Until that's wired we declare it not-available so the router falls through
    to yolov8-pose. Path A scaffold is preserved for future S018b wiring."""
    return False  # not wired — needs sapiens-pose head + source repo


def _marigold_runtime_available() -> bool:
    """S017: prs-eth Marigold-Normals lives in /tmp/marigold-venv (torch +
    diffusers). Attestation: venv python + runner + diffusers checkpoint
    (model_index.json) on disk + MarigoldNormalsPipeline importable inside
    the venv. Mirrors the depthpro/sf3d pattern."""
    import subprocess
    paths_ok = all(os.path.exists(p) for p in (
        "/tmp/marigold-venv/bin/python",
        "/data/Projects/ATLAS/bin/_decompose_normal_runner.py",
        "/home/tom/models/prs-eth_marigold-normals-v0-1/model_index.json",
    ))
    if not paths_ok:
        return False
    # Final probe: can the venv import the pipeline class? Cheap subprocess.
    try:
        r = subprocess.run(
            ["/tmp/marigold-venv/bin/python", "-c",
             "import diffusers; from diffusers import MarigoldNormalsPipeline"],
            capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


PASS_PRODUCERS: Dict[str, List[dict]] = {
    "mask": [
        # S014b: BiRefNet replaces CorridorKey as the default (priority 0).
        # Cheapest-fits selection picks the smallest gpu_sec_est, so we set
        # birefnet's estimate BELOW corridorkey's so router.route() prefers it.
        # CorridorKey is demoted to a fallback for non-still / batch use cases.
        {"name": "birefnet",
         "path": "/home/tom/models/ZhengPeng7_BiRefNet",
         "tier": "mid", "vram_gb": 2.0, "gpu_sec_est": 0.4,
         "input_format": "rgb_1024", "output_format": "alpha_grayscale_png",
         "quality": "default", "runtime": "hf_transformers",
         "runtime_available": _birefnet_runtime_available()},
        {"name": "corridorkey",
         "path": "/home/tom/models/CorridorKey/models/corridorkey_1024-fp32.onnx",
         "tier": "tiny", "vram_gb": 0.5, "gpu_sec_est": 0.8,
         "input_format": "rgba_1024", "output_format": "alpha_mask_png",
         "quality": "fast", "runtime": "onnxruntime"},
        {"name": "finegrain",
         "path": "/home/tom/models/finegrain_box_segmenter",
         "tier": "tiny", "vram_gb": 0.3, "gpu_sec_est": 0.5,
         "input_format": "rgb", "output_format": "alpha_mask_png",
         "quality": "fast", "runtime": "hf_transformers"},
    ],
    "depth": [
        {"name": "depthpro",
         "path": "/home/tom/models/apple_DepthPro",
         "tier": "mid", "vram_gb": 2.0, "gpu_sec_est": 1.5,
         "input_format": "rgb", "output_format": "depth_png16",
         "quality": "default", "runtime": "torch",
         # S015: flipped True when the depthpro venv + weights + runner are on disk.
         "runtime_available": _depthpro_runtime_available()},
    ],
    "normal": [
        {"name": "marigold-normals",
         "path": "/home/tom/models/prs-eth_marigold-normals-v0-1",
         "tier": "heavy", "vram_gb": 15, "gpu_sec_est": 2.0,
         "input_format": "rgb", "output_format": "normal_png",
         "quality": "default", "runtime": "diffusers",
         # S017: flipped True when the marigold venv + weights + runner are on disk
         # AND the diffusers pipeline can be imported inside the venv.
         "runtime_available": _marigold_runtime_available()},
    ],
    "mesh": [
        {"name": "stable-fast-3d",
         "path": "/home/tom/models/stable-fast-3d",
         "tier": "mid", "vram_gb": 4, "gpu_sec_est": 4.0,
         "input_format": "rgba", "output_format": "glb",
         "quality": "fast", "runtime": "torch",
         # S016: flipped True when the sf3d venv + weights + extensions + runner are on disk.
         "runtime_available": _sf3d_runtime_available()},
        {"name": "trellis",
         "path": "/home/tom/models/TencentARC_Pixal3D",
         "tier": "heavy", "vram_gb": 24, "gpu_sec_est": 120,
         "input_format": "rgba", "output_format": "glb",
         "quality": "hero", "runtime": "torch",
         # S016b: flipped True when the Pixal3D venv + source + weights + runner are on disk.
         "runtime_available": _trellis_runtime_available()},
    ],
    # S018: pose producer. Sapiens-1b is the long-term hero (Facebook's
    # human-centric backbone) but the local checkpoint is pretrain-only — no
    # pose head ships with it. yolov8-pose is the wired fallback today: 6 MB
    # COCO-17 keypoints producer. Both emit skeleton-overlay PNG + sidecar
    # JSON; bin/assets routes _pose_ to by-pass/pose/ automatically.
    "pose": [
        {"name": "yolov8-pose",
         "path": "/home/tom/models/ultralytics-yolov8-pose/yolov8n-pose.pt",
         "tier": "tiny", "vram_gb": 0.5, "gpu_sec_est": 0.5,
         "input_format": "rgb", "output_format": "skeleton_overlay_png+coco17_json",
         "quality": "fast", "runtime": "torch",
         "runtime_available": _yolopose_runtime_available()},
        {"name": "sapiens-1b",
         "path": "/home/tom/models/facebook_sapiens-pretrain-1b",
         "tier": "heavy", "vram_gb": 18, "gpu_sec_est": 4.0,
         "input_format": "rgb", "output_format": "skeleton_overlay_png+coco17_json",
         "quality": "hero", "runtime": "torch",
         "runtime_available": _sapiens_pretrain_available()},
    ],
}


def route(pass_name: str,
          quality: str = "default",
          available_vram_gb: float = 20.0,
          runtimes_available: Optional[List[str]] = None) -> Optional[dict]:
    """Pick the cheapest producer that fits the VRAM budget at the requested quality.

    Args:
        pass_name: one of PASS_PRODUCERS keys (mask|depth|normal|mesh|...)
        quality: 'fast' | 'default' | 'hero'
        available_vram_gb: budget — producers above this are excluded
        runtimes_available: if given, only producers whose runtime is in this
            list are considered (e.g. ['onnxruntime','torch']). None = allow all.
            NOTE this is a filter on the runtime NAME, which several producers
            share; it can never mean "this producer is installed".

    Returns:
        Producer dict (a copy of the entry in PASS_PRODUCERS), or None if no
        producer fits the constraints.
    """
    candidates = PASS_PRODUCERS.get(pass_name, [])
    # A producer's own attestation comes first and is not negotiable. Filtering
    # only on the runtime NAME let one producer's liveness vouch for another's:
    # sf3d and trellis both declare runtime "torch", so Pixal3D being installed
    # put "torch" in the caller's list and `--quality hero` selected sf3d, whose
    # venv and source tree had been erased from /tmp. The name of a runtime is
    # not a statement about the producer that happens to use it.
    eligible = [c for c in candidates if c.get("runtime_available", True)]
    eligible = [c for c in eligible if c["vram_gb"] <= available_vram_gb]
    if runtimes_available is not None:
        rt = set(runtimes_available)
        eligible = [c for c in eligible if c["runtime"] in rt]
    if not eligible:
        return None
    if quality == "hero":
        chosen = max(eligible, key=lambda c: c["vram_gb"])
    elif quality == "fast":
        chosen = min(eligible, key=lambda c: c["gpu_sec_est"])
    else:  # default — cheapest-that-fits by gpu_sec_est
        chosen = min(eligible, key=lambda c: c["gpu_sec_est"])
    return dict(chosen)


def route_all(target_passes: List[str],
              quality: str = "default",
              available_vram_gb: float = 20.0,
              runtimes_available: Optional[List[str]] = None) -> Dict[str, Optional[dict]]:
    """Route a batch of passes in one call.

    Returns: {pass_name: producer_dict_or_None}
    """
    return {p: route(p, quality=quality, available_vram_gb=available_vram_gb,
                     runtimes_available=runtimes_available)
            for p in target_passes}


def list_passes() -> List[str]:
    """All declared passes."""
    return sorted(PASS_PRODUCERS.keys())


def list_producers(pass_name: str) -> List[dict]:
    """All declared producers for a pass (unfiltered)."""
    return [dict(c) for c in PASS_PRODUCERS.get(pass_name, [])]


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print(json.dumps({"passes": list_passes(),
                          "producers": {p: list_producers(p) for p in list_passes()}},
                         indent=2))
        sys.exit(0)
    target = sys.argv[1].split(",")
    quality = sys.argv[2] if len(sys.argv) > 2 else "default"
    vram = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
    print(json.dumps(route_all(target, quality=quality, available_vram_gb=vram), indent=2))
