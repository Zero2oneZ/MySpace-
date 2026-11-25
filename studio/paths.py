"""paths.py — single source of truth for every directory the studio touches.

Every entrypoint (app.py, wardrobe_studio.py, yt_cutter.py, pinterest_app.py,
media/.tools/*) imports from here so the layout can be moved or re-rooted in
one place. Override the root with $STUDIO_ROOT.

Layout (created by bootstrap.py — see ALL_DIRS at the bottom):

    studio/
    ├── media/                       # global asset library (long-lived, shared)
    │   ├── Models/{Females,Males,Babies}/...
    │   ├── Cloths/{Female,Male}/{Tops,Bottoms,...}
    │   ├── Furniture/RoomsType/{Bedroom,Kitchen,...}
    │   ├── House_Blueprints/
    │   ├── HEAD_TEMPLET/
    │   ├── Media/
    │   │   ├── Image/{Screenshots}
    │   │   ├── Video/
    │   │   ├── Sounds/{Vocals,Music,Noise}
    │   │   ├── Mask/
    │   │   └── 3d/
    │   │       ├── assets/{shaders,bitmap,hdri_images,environment,composite,layer_style}
    │   │       ├── textures/  normal_maps/  rigs/  mesh/  ground_truth/
    │   │       ├── bed/  dresser/  ...  (per-furniture mesh buckets)
    │   ├── .staging/                # incoming, pre-classification
    │   ├── .logs/                   # fetch + classify logs
    │   └── .tools/                  # fetch-url.sh, process.py, sidecar.py, separate.py
    ├── projects/                    # per-project saved scenes (USER-FACING)
    │   └── <slug>/
    │       ├── scene.json           # 3-D scene + flow graph
    │       ├── assets/              # project-local copies / overrides
    │       ├── exports/             # rendered exports
    │       └── makeup/              # makeup-designer JSONL layers
    ├── cache/                       # runtime cache (safe to delete)
    └── logs/                        # app logs

`paths.py` itself does NOT create directories — call `bootstrap.ensure()` first.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Root ─────────────────────────────────────────────────────────────────────
STUDIO_ROOT: Path = Path(
    os.environ.get("STUDIO_ROOT") or Path(__file__).resolve().parent
)

# ── Top-level dirs ───────────────────────────────────────────────────────────
MEDIA_ROOT:    Path = STUDIO_ROOT / "media"
PROJECTS_ROOT: Path = STUDIO_ROOT / "projects"
CACHE_ROOT:    Path = STUDIO_ROOT / "cache"
LOGS_ROOT:     Path = STUDIO_ROOT / "logs"
DOCS_ROOT:     Path = STUDIO_ROOT / "docs"
SAVED_ROOT:    Path = STUDIO_ROOT / "saved"   # legacy DAG-Studio saves; kept

# ── Media library taxonomy ───────────────────────────────────────────────────
MODELS_DIR        = MEDIA_ROOT / "Models"
MODELS_FEMALES    = MODELS_DIR / "Females"
MODELS_MALES      = MODELS_DIR / "Males"
MODELS_BABIES     = MODELS_DIR / "Babies"
MODELS_HEADSHOTS  = MODELS_FEMALES / "HeadShots"

CLOTHS_DIR        = MEDIA_ROOT / "Cloths"
CLOTHS_FEMALE     = CLOTHS_DIR / "Female"
CLOTHS_MALE       = CLOTHS_DIR / "Male"
CLOTHS_TEMPLETS_F = CLOTHS_FEMALE / "Templets"

FURNITURE_DIR     = MEDIA_ROOT / "Furniture"
ROOMS_DIR         = FURNITURE_DIR / "RoomsType"

BLUEPRINTS_DIR    = MEDIA_ROOT / "House_Blueprints"
HEAD_TEMPLET_DIR  = MEDIA_ROOT / "HEAD_TEMPLET"

MEDIA_SUB         = MEDIA_ROOT / "Media"   # the "miscellaneous media" bucket
IMAGE_DIR         = MEDIA_SUB / "Image"
SCREENSHOTS_DIR   = IMAGE_DIR / "Screenshots"
VIDEO_DIR         = MEDIA_SUB / "Video"
MASK_DIR          = MEDIA_SUB / "Mask"
SOUNDS_DIR        = MEDIA_SUB / "Sounds"
VOCALS_DIR        = SOUNDS_DIR / "Vocals"
MUSIC_DIR         = SOUNDS_DIR / "Music"
NOISE_DIR         = SOUNDS_DIR / "Noise"

THREED_DIR        = MEDIA_SUB / "3d"
MESH_DIR          = THREED_DIR / "mesh"
RIGS_DIR          = THREED_DIR / "rigs"
TEXTURES_DIR      = THREED_DIR / "textures"
NORMALMAPS_DIR    = THREED_DIR / "normal_maps"
GROUND_TRUTH_DIR  = THREED_DIR / "ground_truth"
ASSETS3D_DIR      = THREED_DIR / "assets"
SHADERS_DIR       = ASSETS3D_DIR / "shaders"
BITMAP_DIR        = ASSETS3D_DIR / "bitmap"
HDRI_DIR          = ASSETS3D_DIR / "hdri_images"
ENVIRONMENT_DIR   = ASSETS3D_DIR / "environment"
COMPOSITE_DIR     = ASSETS3D_DIR / "composite"
LAYER_STYLE_DIR   = ASSETS3D_DIR / "layer_style"

# Per-furniture mesh buckets (extend freely — bootstrap will create them).
FURNITURE_MESH_BUCKETS = [
    "bed", "dresser", "nightstand", "sofa", "chair", "table",
    "lamp", "desk", "wardrobe", "bookshelf", "ottoman", "stool",
]

# ── Hidden / runtime dirs inside media ───────────────────────────────────────
STAGING_DIR       = MEDIA_ROOT / ".staging"
MEDIA_LOGS_DIR    = MEDIA_ROOT / ".logs"
TOOLS_DIR         = MEDIA_ROOT / ".tools"

# ── Wardrobe / DAG runtime outputs ───────────────────────────────────────────
WARDROBE_OUT_DIR  = MEDIA_ROOT / "wardrobe_out"
DAG_CACHE_DIR     = CACHE_ROOT / "dag"
YTDLP_CACHE_DIR   = CACHE_ROOT / "yt"

# ── Per-room subdirs ─────────────────────────────────────────────────────────
ROOM_TYPES = [
    "Bedroom", "LivingRoom", "Kitchen", "Bathroom", "DiningRoom",
    "Office", "Outdoor", "Hallway", "Studio",
]

# ── Cloths sub-categories (must match process.py classifier) ─────────────────
CLOTHS_SUBCATS = [
    "Tops", "Bottoms", "Dresses", "Outerwear", "Footwear",
    "Accessories", "Swimwear", "Underwear", "Sleepwear",
]

# ── Project-internal layout (under PROJECTS_ROOT/<slug>/) ────────────────────
PROJECT_SUBDIRS = ("assets", "exports", "makeup", "renders", "layers")
PROJECT_SCENE_FILE = "scene.json"


def project_dir(slug: str) -> Path:
    """Return the canonical path to a project by slug. Does NOT create it."""
    safe = "".join(c for c in slug if c.isalnum() or c in "-_.").strip("-_.")
    if not safe:
        raise ValueError(f"invalid project slug: {slug!r}")
    return PROJECTS_ROOT / safe


# ── Master directory list (consumed by bootstrap.py) ─────────────────────────
def all_dirs() -> list[Path]:
    """All directories the studio expects to exist on disk."""
    fixed = [
        STUDIO_ROOT, MEDIA_ROOT, PROJECTS_ROOT, CACHE_ROOT, LOGS_ROOT, DOCS_ROOT,
        SAVED_ROOT,
        MODELS_DIR, MODELS_FEMALES, MODELS_MALES, MODELS_BABIES, MODELS_HEADSHOTS,
        MODELS_FEMALES / "Solo", MODELS_FEMALES / "Group", MODELS_FEMALES / "Sex",
        CLOTHS_DIR, CLOTHS_FEMALE, CLOTHS_MALE, CLOTHS_TEMPLETS_F,
        FURNITURE_DIR, ROOMS_DIR,
        BLUEPRINTS_DIR, HEAD_TEMPLET_DIR,
        MEDIA_SUB, IMAGE_DIR, SCREENSHOTS_DIR, VIDEO_DIR, MASK_DIR,
        SOUNDS_DIR, VOCALS_DIR, MUSIC_DIR, NOISE_DIR,
        THREED_DIR, MESH_DIR, RIGS_DIR, TEXTURES_DIR, NORMALMAPS_DIR,
        GROUND_TRUTH_DIR, ASSETS3D_DIR, SHADERS_DIR, BITMAP_DIR, HDRI_DIR,
        ENVIRONMENT_DIR, COMPOSITE_DIR, LAYER_STYLE_DIR,
        STAGING_DIR, MEDIA_LOGS_DIR, TOOLS_DIR,
        WARDROBE_OUT_DIR, DAG_CACHE_DIR, YTDLP_CACHE_DIR,
    ]
    fixed += [ROOMS_DIR / r for r in ROOM_TYPES]
    fixed += [CLOTHS_FEMALE / c for c in CLOTHS_SUBCATS]
    fixed += [CLOTHS_MALE   / c for c in CLOTHS_SUBCATS]
    fixed += [THREED_DIR    / b for b in FURNITURE_MESH_BUCKETS]
    return fixed


if __name__ == "__main__":
    # Quick sanity dump — `python3 paths.py` prints every canonical path.
    for p in all_dirs():
        marker = "✓" if p.is_dir() else "·"
        print(f"  {marker} {p}")
