# Studio Layout — Single Source of Truth

Every path the studio touches is defined in **`studio/paths.py`**. Every
entrypoint calls **`bootstrap.ensure()`** before doing anything else, so the
tree below is guaranteed to exist on disk after the first launch.

If you ever need to move the studio, just set `$STUDIO_ROOT` — nothing else
changes.

---

## Top-level

```
studio/
├── paths.py             ← single source of truth for every directory
├── bootstrap.py         ← idempotent tree-creator (called by every entrypoint)
├── project_io.py        ← create / save / load / list user projects
├── app.py               ← DAG Studio (Streamlit)
├── wardrobe_studio.py   ← Wardrobe Studio (Streamlit)
├── pinterest_app.py     ← Pinterest search → media library (Streamlit)
├── yt_cutter.py         ← YouTube time-slider cutter (Streamlit)
├── download-seeds.sh    ← fetch the curated URL set from DOWNLOAD_INSYRUCTIONS.md
├── docs/                ← documentation (THIS file, DAG.md, DAG-GUI.md, …)
├── media/               ← global asset library (long-lived, shared)
├── projects/            ← per-project saved scenes (USER-FACING)
├── cache/               ← runtime cache (safe to delete)
├── logs/                ← app logs
└── saved/               ← legacy DAG-Studio .dag.json files
```

## `media/` — the global asset library

The asset library is **content-addressed by category**. The path tells you
what something is; the file name only has to be unique. Every downloaded
file gets a sibling `.json` **sidecar** (`media/.tools/sidecar.py`) that
records the source, label, tags, and "uses".

```
media/
├── Models/
│   ├── Females/{HeadShots,Solo,Group,Sex}
│   ├── Males/
│   └── Babies/
├── Cloths/
│   ├── Female/{Tops,Bottoms,Dresses,Outerwear,Footwear,Accessories,
│   │           Swimwear,Underwear,Sleepwear,Templets}
│   └── Male/{Tops,Bottoms,Outerwear,Footwear,Accessories,
│             Swimwear,Underwear,Sleepwear}
├── Furniture/RoomsType/{Bedroom,LivingRoom,Kitchen,Bathroom,
│                        DiningRoom,Office,Outdoor,Hallway,Studio}
├── House_Blueprints/        ← floor plans (drive the blueprint→blockout pass)
├── HEAD_TEMPLET/            ← bust references for the Makeup Designer
├── Media/
│   ├── Image/               ← misc images (Screenshots/ subdir)
│   ├── Video/               ← cut videos from yt_cutter
│   ├── Sounds/{Vocals,Music,Noise}
│   ├── Mask/                ← binary masks produced by rembg
│   └── 3d/
│       ├── mesh/  rigs/  textures/  normal_maps/  ground_truth/
│       ├── bed/  dresser/  nightstand/  sofa/  chair/  table/  lamp/
│       ├── desk/  wardrobe/  bookshelf/  ottoman/  stool/        ← per-furniture mesh buckets
│       └── assets/{shaders,bitmap,hdri_images,environment,
│                   composite,layer_style}
├── wardrobe_out/            ← wardrobe-studio renders
├── .staging/                ← incoming, pre-classification (transient)
├── .logs/                   ← fetch + classify logs
└── .tools/
    ├── fetch-url.sh         ← wget + classify + bg-remove + sidecar
    ├── process.py           ← keyword + cc-tiny classifier
    ├── separate.py          ← demucs / ffmpeg vocal+music+noise split
    └── sidecar.py           ← read/write/merge the per-asset .json sidecars
```

### How the auto-organizer works

1. **Drop or fetch** a file. `fetch-url.sh` writes into `media/.staging/`.
2. **Classify**. `process.py classify <file>` returns a category path
   (e.g. `Cloths/Female/Tops`) using filename keywords first, then the
   local `cc tiny` model on ambiguous cases.
3. **Move**. The file is moved to `media/<category>/<basename>`.
4. **Background-remove + mask**. For images, `rembg` writes `_nobg.png`
   to `media/Media/Image/` and a binary mask to `media/Media/Mask/`.
5. **Sidecar**. A `.json` next to the base asset records `sha`,
   `source_url`, `category`, `label`, `tags`, `uses`, and any `variants`.

Anything classified as a clothing item gets the gender from a hint flag
(`-gender Male`) or from filename keywords.

## `projects/` — user-facing scenes

A project is the unit of work — one 3-D scene, makeup design, or
wardrobe pose, plus everything that goes with it.

```
projects/<slug>/
├── scene.json     ← single load-bearing file (3-D scene + DAG graph + asset list)
├── assets/        ← project-local copies / overrides
├── exports/       ← rendered exports (PNG, MP4, GLB, …)
├── makeup/        ← makeup-designer JSONL layer stacks
├── renders/       ← raster snapshots
└── layers/        ← SVG layer drops
```

`scene.json` schema (versioned, additive):

```json
{
  "schema":  1,
  "name":    "kitchen-makeover",
  "slug":    "kitchen-makeover",
  "kind":    "scene|wardrobe|makeup|dag",
  "created": "2026-05-26T13:40:00Z",
  "updated": "2026-05-26T13:40:00Z",
  "scene":   { "camera": {...}, "lights": [...], "axis": {...},
               "floor": {...}, "objects": [...] },
  "graph":   { "nodes": [], "edges": [] },
  "assets":  [ "assets/foo.png", ... ],
  "metadata": {}
}
```

### Project CLI

```bash
python3 project_io.py new "kitchen makeover"      # → projects/kitchen-makeover/
python3 project_io.py new "lip look 1" --kind makeup
python3 project_io.py list                        # → table
python3 project_io.py show kitchen-makeover       # → scene.json dump
python3 project_io.py import kitchen-makeover /path/to/some.png
python3 project_io.py delete kitchen-makeover
```

The makeup / wardrobe / DAG kinds start with sensible default `scene`
contents so you can open and render an empty project without crashing.

## Seeding from the curated URL set

`DOWNLOAD_INSYRUCTIONS.md` at the studio root holds the curated Pinterest
URL set (alpha bust, head templates, blueprints, textures, cloths
templates, makeup model references, …). Pulling them down:

```bash
./download-seeds.sh           # fetch all search-page URLs into the right buckets
./download-seeds.sh TEXTURES  # only the TEXTURES bucket
./download-seeds.sh -n        # dry-run plan
```

Search-page URLs are scraped automatically. Single-pin URLs are listed
with their destination bucket but **must be saved manually** (Pinterest
JS-renders pin pages so wget can't grab the image).

## Permanence

The tree is rebuilt on every `run.sh` / `run-wardrobe.sh` /
`run-pinterest.sh` / `run_yt_cutter.sh` launch. Adding a new
classification bucket is a one-liner in `paths.py`:

```python
CLOTHS_SUBCATS = [
    "Tops", "Bottoms", ..., "Sleepwear",
    "NewBucket",   # ← just add it; bootstrap will create the dirs next launch
]
```

If you add a new bucket, also add a keyword pattern to `media/.tools/process.py`
so the classifier knows how to route into it.

## What lives where, at a glance

| You want to … | Look in |
|---|---|
| Add a new clothing class | `paths.CLOTHS_SUBCATS` + `process.py KEYWORDS` |
| Move studio to a new disk | `export STUDIO_ROOT=...` and re-run anything |
| Find a saved project | `studio/projects/<slug>/scene.json` |
| Find a downloaded asset | `studio/media/<category>/<file>` |
| Find a fetch log | `studio/media/.logs/fetch-YYYYMMDD-HHMMSS.log` |
| Wipe runtime cache | `rm -rf studio/cache/ && python3 bootstrap.py` |
| Re-seed the canonical tree | `python3 bootstrap.py --report` then `python3 bootstrap.py` |
