"""registry.py — declarative pass catalogue.

A Pass is a typed inference operation: takes one or more named inputs,
produces one named output, has a default callable + a cost class.

The registry below is the source of truth for:
  - passes.filetype_dag (which passes can run on which file types)
  - passes.svg_layers   (how each pass's output gets labeled inside SVG)
  - passes.import_pipeline (which passes run at import vs. lazy)

To extend: add a Pass to REGISTRY at the bottom of this file. No code
changes required elsewhere; the dispatcher resolves callables by id.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

# Cost classes drive scheduling — heavier passes run at IMPORT (user
# explicitly waiting), lighter ones run LAZY (on render-time demand).
COST_LIGHT  = "LIGHT"
COST_MEDIUM = "MEDIUM"
COST_HEAVY  = "HEAVY"

# Kind = the semantic category of a pass's input/output payload.
# These map onto the canonical port types in studio/types_meta.py
# (IMG, VID, AUD, TXT, MASK, DEPTH, KPTS, EMB, …) but are kept as plain
# strings here so the registry stays usable without dag_studio deps.


@dataclass
class Pass:
    id: str                                # short, unique slug — `mask`, `depth`, `caption`
    label: str                             # human-friendly name
    input_kinds: list[str]                 # e.g. ["IMG"] or ["VID","AUD"]
    output_kind: str                       # e.g. "MASK"
    cost_class: str = COST_MEDIUM          # LIGHT|MEDIUM|HEAVY (initial seed)
    import_time: bool = False              # run at import vs. lazy
    fn: Optional[Callable] = None          # default inference callable (set at module load)
    description: str = ""
    instruction: str = ""                  # text written to SVG layer's data-instruction
    file_extensions: list[str] = field(default_factory=list)   # which file types it applies to
    tags: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)             # dependencies (rembg, ffmpeg, demucs)

    def cli_name(self) -> str:
        return self.id.replace("_", "-")


# ─── Registry contents ───────────────────────────────────────────────────────
#
# Heuristic for HEAVY/import_time=True: any ML inference that produces a new
# image/mask/depth/keypoints. These benefit from being computed at import.
#
# Heuristic for LIGHT/import_time=False: pure-PIL/ffmpeg transforms that
# only take ~ms (thumbnail, resize, format-convert).
# ─────────────────────────────────────────────────────────────────────────────

IMG_EXT  = ["jpg", "jpeg", "png", "webp", "bmp", "tiff", "avif"]
VID_EXT  = ["mp4", "mov", "mkv", "webm", "avi", "m4v"]
AUD_EXT  = ["wav", "mp3", "ogg", "flac", "m4a"]
MESH_EXT = ["obj", "stl", "gltf", "glb", "fbx", "ply"]
DOC_EXT  = ["pdf"]
TEX_EXT  = ["jpg", "jpeg", "png", "webp", "tga", "bmp", "exr"]   # texture-bound images


REGISTRY: list[Pass] = [

    # ── Images ─────────────────────────────────────────────────────────────
    Pass(
        id="thumb",
        label="Thumbnail",
        input_kinds=["IMG"], output_kind="IMG",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT,
        instruction="resize to 256px on the long edge for grid display",
        description="Generates a 256-px thumb via PIL LANCZOS resize.",
        tags=["thumb", "ui"],
    ),
    Pass(
        id="content_hash",
        label="Content hash",
        input_kinds=["IMG"], output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + VID_EXT + AUD_EXT + MESH_EXT + DOC_EXT,
        instruction="sha256 of the file content, first 16 hex chars",
        description="Identity fingerprint — drives dedup + index lookups.",
        tags=["identity"],
    ),
    # ── Hex hash passes ────────────────────────────────────────────────────
    Pass(
        id="hex_md5",
        label="MD5 hex",
        input_kinds=["IMG", "VID", "AUD", "3D", "PDF"],
        output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + VID_EXT + AUD_EXT + MESH_EXT + DOC_EXT,
        instruction="MD5 hash of file content as 32-char hex string",
        description="MD5 digest of entire file content.",
        tags=["hash", "identity", "md5"],
    ),
    Pass(
        id="hex_sha256",
        label="SHA256 hex",
        input_kinds=["IMG", "VID", "AUD", "3D", "PDF"],
        output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + VID_EXT + AUD_EXT + MESH_EXT + DOC_EXT,
        instruction="SHA256 hash of file content as 64-char hex string",
        description="SHA256 digest of entire file content.",
        tags=["hash", "identity", "sha256"],
    ),
    Pass(
        id="hex_sha512",
        label="SHA512 hex",
        input_kinds=["IMG", "VID", "AUD", "3D", "PDF"],
        output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + VID_EXT + AUD_EXT + MESH_EXT + DOC_EXT,
        instruction="SHA512 hash of file content as 128-char hex string",
        description="SHA512 digest of entire file content.",
        tags=["hash", "identity", "sha512"],
    ),
    Pass(
        id="hex_blake2b",
        label="BLAKE2b hex",
        input_kinds=["IMG", "VID", "AUD", "3D", "PDF"],
        output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + VID_EXT + AUD_EXT + MESH_EXT + DOC_EXT,
        instruction="BLAKE2b hash of file content as 128-char hex string",
        description="BLAKE2b digest of entire file content.",
        tags=["hash", "identity", "blake2"],
    ),
    Pass(
        id="hex_blake2s",
        label="BLAKE2s hex",
        input_kinds=["IMG", "VID", "AUD", "3D", "PDF"],
        output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + VID_EXT + AUD_EXT + MESH_EXT + DOC_EXT,
        instruction="BLAKE2s hash of file content as 64-char hex string",
        description="BLAKE2s digest of entire file content.",
        tags=["hash", "identity", "blake2"],
    ),
    Pass(
        id="hex_blake3",
        label="BLAKE3 hex",
        input_kinds=["IMG", "VID", "AUD", "3D", "PDF"],
        output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + VID_EXT + AUD_EXT + MESH_EXT + DOC_EXT,
        instruction="BLAKE3 hash of file content as 64-char hex string",
        description="BLAKE3 digest of entire file content (fastest).",
        tags=["hash", "identity", "blake3"],
    ),
    Pass(
        id="hex_sha3_256",
        label="SHA3-256 hex",
        input_kinds=["IMG", "VID", "AUD", "3D", "PDF"],
        output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + VID_EXT + AUD_EXT + MESH_EXT + DOC_EXT,
        instruction="SHA3-256 hash of file content as 64-char hex string",
        description="SHA3-256 (Keccak) digest of entire file content.",
        tags=["hash", "identity", "sha3"],
    ),
    Pass(
        id="hex_sha3_512",
        label="SHA3-512 hex",
        input_kinds=["IMG", "VID", "AUD", "3D", "PDF"],
        output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + VID_EXT + AUD_EXT + MESH_EXT + DOC_EXT,
        instruction="SHA3-512 hash of file content as 128-char hex string",
        description="SHA3-512 (Keccak) digest of entire file content.",
        tags=["hash", "identity", "sha3"],
    ),
    Pass(
        id="mask",
        label="Background mask",
        input_kinds=["IMG"], output_kind="MASK",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=IMG_EXT,
        instruction="alpha matte separating foreground subject from background",
        description="rembg (U²-Net / BiRefNet) with GrabCut fallback.",
        tags=["mask", "subject"],
        needs=["rembg|opencv"],
    ),
    Pass(
        id="nobg",
        label="Background-removed",
        input_kinds=["IMG"], output_kind="IMG",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=IMG_EXT,
        instruction="apply mask to source image — output is RGBA with transparent bg",
        description="Source image × mask = subject-only RGBA image.",
        tags=["mask", "composite"],
        needs=["rembg|opencv"],
    ),
    Pass(
        id="depth",
        label="Depth map",
        input_kinds=["IMG"], output_kind="DEPTH",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=IMG_EXT,
        instruction="single-channel depth estimation, 0=close 255=far",
        description="Pseudo-depth via edge+luminance gradient (PIL); "
                    "stub for DepthPro / Depth-Anything-v2.",
        tags=["depth", "3d-prep"],
    ),
    Pass(
        id="caption",
        label="Caption",
        input_kinds=["IMG"], output_kind="TXT",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=IMG_EXT,
        instruction="natural-language description of the image content",
        description="CLIP-Interrogator wrapper, with cc-tiny fallback.",
        tags=["text", "label"],
        needs=["cc tiny|clip-interrogator"],
    ),
    Pass(
        id="tags",
        label="Tags",
        input_kinds=["IMG"], output_kind="TXT",
        cost_class=COST_MEDIUM, import_time=True,
        file_extensions=IMG_EXT,
        instruction="keyword tags inferred from the filename heuristics",
        description="Uses process.py's KEYWORDS list; falls back to cc-tiny.",
        tags=["text", "label"],
    ),
    Pass(
        id="keypoints",
        label="Pose keypoints",
        input_kinds=["IMG"], output_kind="KPTS",
        cost_class=COST_HEAVY, import_time=False,
        file_extensions=IMG_EXT,
        instruction="2D human keypoints (17-pt COCO format) for rigs/anim",
        description="MediaPipe Pose wrapper (stub — install mediapipe).",
        tags=["pose", "3d-prep"],
        needs=["mediapipe"],
    ),
    Pass(
        id="embedding",
        label="Embedding",
        input_kinds=["IMG"], output_kind="EMB",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=IMG_EXT,
        instruction="CLIP-style float vector for semantic search + dedup",
        description="metaclip-2-mt5 wrapper (stub — install transformers).",
        tags=["search", "dedup"],
        needs=["transformers"],
    ),

    # ── Fused depth (physics + ML) ─────────────────────────────────────────
    Pass(
        id="fused_depth",
        label="Fused depth map",
        input_kinds=["IMG", "AUD"], output_kind="DEPTH",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=IMG_EXT,
        instruction="fused depth from vision + audio + priors (meters, not relative)",
        description="5-channel depth fusion: visual (Marigold/DepthPro) + acoustic "
                    "(echo time, RT60, room modes) + semantic (scene prior) + "
                    "anthropometric (body proportions) + clip-geometry (framing) → "
                    "per-pixel depth in meters with confidence σ per pixel. "
                    "Output: fused_depth.npz (depth, confidence, room_dims, camera_intrinsics).",
        tags=["depth", "3d-prep", "physics"],
        needs=["marigold|depthpro", "audio-crosscorr", "clip-classifier", "mediapipe"],
    ),
    Pass(
        id="depth_to_frustum",
        label="Depth → 3D frustum",
        input_kinds=["DEPTH", "SVG"], output_kind="3D",
        cost_class=COST_MEDIUM, import_time=False,
        file_extensions=["npz"],
        instruction="unproject SVG bbox corners through fused depth + camera → 3D frustum",
        description="Given SVG drawing (rect/polygon) + fused_depth.npz, unproject "
                    "corners through camera intrinsics → 3D frustum (8 corners: 4 near + 4 far). "
                    "Output: frustum.json (8 verts, near_z, far_z, extrinsic).",
        tags=["3d", "geom", "svg"],
        needs=["numpy", "scipy"],
    ),
    Pass(
        id="extrude_polygon",
        label="Polygon extrusion",
        input_kinds=["SVG", "DEPTH"], output_kind="3D",
        cost_class=COST_MEDIUM, import_time=False,
        file_extensions=["svg", "npz"],
        instruction="extrude SVG path by depth to create 3D mesh",
        description="Given SVG contour (closed path) + fused depth region, extrude "
                    "by depth in meters → 3D mesh. Uses trimesh.creation.extrude_polygon. "
                    "Output: mesh.glb (vertices, normals, UV, material).",
        tags=["3d", "extrude", "mesh"],
        needs=["trimesh", "numpy"],
    ),
    Pass(
        id="normal_map_from_depth",
        label="Normal map from depth",
        input_kinds=["DEPTH"], output_kind="IMG",
        cost_class=COST_LIGHT, import_time=False,
        file_extensions=["npz"],
        instruction="compute tangent-space normal map from depth map",
        description="Pseudo-normal: ∇depth → surface normal direction. "
                    "For region-specific: run on fused_depth subset. "
                    "Output: normal_map.png (RGB normal encoding).",
        tags=["3d", "normal", "texture"],
        needs=["numpy"],
    ),
    Pass(
        id="particles_from_depth",
        label="Particles from depth",
        input_kinds=["DEPTH", "IMG"], output_kind="3D",
        cost_class=COST_MEDIUM, import_time=False,
        file_extensions=["npz", "png", "jpg"],
        instruction="convert depth+RGB to 3D point cloud particles",
        description="Every pixel with d>0 and confidence>0.5 → 3D point (x,y,z,rgb,size). "
                    "Output: particles.glb (instanced points with size).",
        tags=["3d", "particle", "pointcloud"],
        needs=["numpy", "gltf"],
    ),

    # ── Textures + layered assets ──────────────────────────────────────────
    Pass(
        id="normal_map",
        label="Normal map",
        input_kinds=["IMG"], output_kind="IMG",
        cost_class=COST_MEDIUM, import_time=False,
        file_extensions=TEX_EXT,
        instruction="height-from-grayscale → tangent-space normal map",
        description="PIL gradient → normal-space conversion. For PBR shading.",
        tags=["3d", "texture"],
    ),
    Pass(
        id="albedo",
        label="Albedo extract",
        input_kinds=["IMG"], output_kind="IMG",
        cost_class=COST_MEDIUM, import_time=False,
        file_extensions=TEX_EXT,
        instruction="estimate diffuse albedo by removing shading variance",
        description="Stub for Intrinsic decomposition.",
        tags=["3d", "texture"],
    ),
    Pass(
        id="layered_svg",
        label="Layered SVG",
        input_kinds=["IMG"], output_kind="SVG",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=IMG_EXT + TEX_EXT,
        instruction="bundle the source + all imported-time pass outputs "
                    "into one SVG; each pass is a <g> layer with metadata",
        description="The main self-describing output. See passes.svg_layers.",
        tags=["composite", "exchange"],
    ),

    # ── Video ──────────────────────────────────────────────────────────────
    Pass(
        id="vid_thumb",
        label="Video thumbnail",
        input_kinds=["VID"], output_kind="IMG",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=VID_EXT,
        instruction="grab middle-frame as a still",
        description="ffmpeg -ss <dur/2> -frames:v 1 → png.",
        tags=["thumb", "ui"],
        needs=["ffmpeg"],
    ),
    Pass(
        id="waveform",
        label="Waveform",
        input_kinds=["VID", "AUD"], output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=VID_EXT + AUD_EXT,
        instruction="bucketed peak-envelope as JSON for plotting",
        description="Reuses yt_cutter.extract_waveform; no numpy needed.",
        tags=["audio", "ui"],
        needs=["ffmpeg"],
    ),
    Pass(
        id="video_caption",
        label="Video caption",
        input_kinds=["VID"], output_kind="TXT",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=VID_EXT,
        instruction="short caption of the video's content",
        description="SpaceTimeGPT wrapper (stub).",
        tags=["text", "label"],
        needs=["spacetime-gpt"],
    ),

    # ── Audio ──────────────────────────────────────────────────────────────
    Pass(
        id="stems",
        label="Stem separation",
        input_kinds=["AUD"], output_kind="AUD",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=AUD_EXT + VID_EXT,
        instruction="split into vocals / music / noise stems",
        description="demucs if installed, else ffmpeg karaoke fallback. "
                    "Existing utility lives at media/.tools/separate.py.",
        tags=["audio", "stems"],
        needs=["ffmpeg", "demucs?"],
    ),
    Pass(
        id="speech_to_text",
        label="Speech → text",
        input_kinds=["AUD"], output_kind="TXT",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=AUD_EXT,
        instruction="transcribe speech in the audio file",
        description="ultravox wrapper (stub).",
        tags=["text", "transcript"],
        needs=["ultravox"],
    ),

    # ── 3D / mesh ──────────────────────────────────────────────────────────
    Pass(
        id="mesh_thumb",
        label="Mesh preview",
        input_kinds=["3D"], output_kind="IMG",
        cost_class=COST_MEDIUM, import_time=True,
        file_extensions=MESH_EXT,
        instruction="single-camera render preview of the mesh",
        description="Blender / Open3D headless render (stub).",
        tags=["3d", "thumb"],
        needs=["blender|open3d"],
    ),
    Pass(
        id="bbox_volume",
        label="Bounding volume",
        input_kinds=["3D"], output_kind="TXT",
        cost_class=COST_LIGHT, import_time=True,
        file_extensions=MESH_EXT,
        instruction="axis-aligned bounding box (min/max + extent)",
        description="trimesh.load + .bounds.",
        tags=["3d", "geom"],
        needs=["trimesh"],
    ),

    # ── Documents ──────────────────────────────────────────────────────────
    Pass(
        id="pdf_extract_text",
        label="PDF → markdown",
        input_kinds=["PDF"], output_kind="MD",
        cost_class=COST_HEAVY, import_time=True,
        file_extensions=DOC_EXT,
        instruction="extract structured markdown (headers + paragraphs)",
        description="MinerU wrapper (stub).",
        tags=["doc", "text"],
        needs=["mineru|pdftotext"],
    ),
]


# ─── Lookup helpers ──────────────────────────────────────────────────────────
def by_id(pass_id: str) -> Pass:
    for p in REGISTRY:
        if p.id == pass_id:
            return p
    raise KeyError(pass_id)


def for_filetype(extension: str) -> list[Pass]:
    """Return all passes that apply to the given file extension."""
    ext = extension.lower().lstrip(".")
    return [p for p in REGISTRY if ext in p.file_extensions]


def for_kind(input_kind: str) -> list[Pass]:
    return [p for p in REGISTRY if input_kind in p.input_kinds]


def import_time_passes(extension: str) -> list[Pass]:
    return [p for p in for_filetype(extension) if p.import_time]


def lazy_passes(extension: str) -> list[Pass]:
    return [p for p in for_filetype(extension) if not p.import_time]


if __name__ == "__main__":
    # Quick `python registry.py` sanity dump.
    print(f"{len(REGISTRY)} passes registered\n")
    for p in REGISTRY:
        ext = ",".join(p.file_extensions[:4])
        flag = "IMPORT" if p.import_time else "LAZY"
        print(f"  {p.id:<18} {p.cost_class:<7} {flag:<7} "
              f"in={'+'.join(p.input_kinds):<10} out={p.output_kind:<5}  ext=[{ext}]")
