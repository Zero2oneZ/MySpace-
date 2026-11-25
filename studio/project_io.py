"""project_io.py — create, save, load, list projects.

A "project" is the user-facing unit of work: one 3-D scene (or wardrobe pose,
or makeup design) plus all of the assets/exports/layers that go with it. They
live under `studio/projects/<slug>/` as ordinary files so users can copy,
zip, rsync, or git them without our help.

Anatomy:
    projects/<slug>/
      scene.json     # the single load-bearing file — nodes, edges, scene tree
      assets/        # local copies / overrides of media (drag-drops land here)
      exports/       # rendered exports
      makeup/        # makeup-designer JSONL layer dumps
      renders/       # raster snapshots
      layers/        # SVG layer drops

scene.json schema (versioned, additive):
    {
      "schema":  1,
      "name":    "kitchen-makeover",
      "kind":    "scene|wardrobe|makeup|dag",
      "created": "2026-05-26T13:40:00Z",
      "updated": "2026-05-26T13:40:00Z",
      "scene": { ... three.js-ish scene tree ... },
      "graph": { "nodes": [...], "edges": [...] },   # optional DAG graph
      "assets":   [ "assets/foo.png", ... ],          # paths relative to project dir
      "metadata": { ... freeform ... }
    }
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Iterable

import paths

SCHEMA_VERSION = 1


# ── slug helpers ─────────────────────────────────────────────────────────────
_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.strip()).strip("-._")
    return s.lower() or f"project-{int(time.time())}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── lifecycle ────────────────────────────────────────────────────────────────
def new(name: str, kind: str = "scene", *, overwrite: bool = False) -> Path:
    """Create a new project directory with empty subfolders and a starter
    scene.json. Returns the project path. Raises FileExistsError unless
    overwrite=True."""
    slug = slugify(name)
    pdir = paths.project_dir(slug)
    if pdir.exists():
        if not overwrite:
            raise FileExistsError(f"project already exists: {pdir}")
        shutil.rmtree(pdir)
    pdir.mkdir(parents=True)
    for sub in paths.PROJECT_SUBDIRS:
        (pdir / sub).mkdir(parents=True, exist_ok=True)

    starter = {
        "schema":  SCHEMA_VERSION,
        "name":    name,
        "slug":    slug,
        "kind":    kind,
        "created": _now(),
        "updated": _now(),
        "scene":   _starter_scene(kind),
        "graph":   {"nodes": [], "edges": []},
        "assets":  [],
        "metadata": {},
    }
    save_scene(pdir, starter)
    return pdir


def _starter_scene(kind: str) -> dict:
    """A minimal scene the 3-D viewer can render without import errors."""
    if kind == "scene":
        return {
            "camera":  {"pos": [4, 3, 4], "look": [0, 1, 0], "fov": 50},
            "lights":  [{"type": "ambient", "intensity": 0.6},
                        {"type": "directional", "pos": [5, 10, 5], "intensity": 0.8}],
            "axis":    {"show": True, "scale": 1.0, "rotate": [0, 0, 0]},
            "floor":   {"size": 8, "checker": True},
            "objects": [],
        }
    if kind == "makeup":
        return {"template": None, "brush_stack": [],
                "layers": ["foundation", "blush", "eyeshadow", "mascara", "lipstick"]}
    if kind == "wardrobe":
        return {"model": None, "garments": [], "merge": False}
    return {}


def project_path(slug_or_name: str) -> Path:
    """Resolve a slug-ish or name-ish string to its project dir."""
    p = paths.project_dir(slugify(slug_or_name))
    if not p.exists():
        # also try the literal slug (no resluging) in case the user passed
        # the exact directory name.
        alt = paths.PROJECTS_ROOT / slug_or_name
        if alt.is_dir():
            return alt
    return p


def list_projects() -> list[dict]:
    """Return [{slug, name, kind, updated, path}] for every project, newest first."""
    if not paths.PROJECTS_ROOT.is_dir():
        return []
    out: list[dict] = []
    for d in paths.PROJECTS_ROOT.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        scene = d / paths.PROJECT_SCENE_FILE
        if not scene.exists():
            continue
        try:
            data = json.loads(scene.read_text())
        except Exception:
            data = {}
        out.append({
            "slug":    d.name,
            "name":    data.get("name") or d.name,
            "kind":    data.get("kind") or "scene",
            "updated": data.get("updated") or "",
            "path":    str(d),
        })
    out.sort(key=lambda r: r.get("updated") or "", reverse=True)
    return out


def load_scene(slug_or_dir: str | Path) -> dict:
    """Read scene.json. Accepts a slug, a name, or a Path."""
    pdir = Path(slug_or_dir) if isinstance(slug_or_dir, Path) else project_path(str(slug_or_dir))
    f = pdir / paths.PROJECT_SCENE_FILE
    if not f.exists():
        raise FileNotFoundError(f"no scene.json in {pdir}")
    return json.loads(f.read_text())


def save_scene(project_dir: str | Path, scene: dict) -> Path:
    """Write scene.json. Stamps `updated`, ensures `schema`."""
    pdir = Path(project_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    scene["schema"] = SCHEMA_VERSION
    scene["updated"] = _now()
    scene.setdefault("created", scene["updated"])
    f = pdir / paths.PROJECT_SCENE_FILE
    f.write_text(json.dumps(scene, indent=2, sort_keys=True))
    return f


def import_asset(project_dir: str | Path, src: str | Path,
                 *, into: str = "assets") -> Path:
    """Copy a file into <project>/<into>/, return its new path. Also appends
    the relative path to scene.json's `assets` list for traceability."""
    pdir = Path(project_dir)
    sub = pdir / into
    sub.mkdir(parents=True, exist_ok=True)
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(src)
    dst = sub / src.name
    if dst.exists():
        dst = sub / f"{int(time.time())}_{src.name}"
    shutil.copy2(src, dst)
    # Update scene.json bookkeeping (silently ignore if scene missing).
    try:
        scene = load_scene(pdir)
        rel = str(dst.relative_to(pdir))
        if rel not in scene.get("assets", []):
            scene.setdefault("assets", []).append(rel)
            save_scene(pdir, scene)
    except FileNotFoundError:
        pass
    return dst


def delete(slug: str) -> bool:
    """Delete a project tree. Returns True if removed, False if not found."""
    pdir = paths.project_dir(slugify(slug))
    if not pdir.exists():
        return False
    shutil.rmtree(pdir)
    return True


# ── CLI ──────────────────────────────────────────────────────────────────────
def _cli(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="project_io.py")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p_new = sp.add_parser("new")
    p_new.add_argument("name")
    p_new.add_argument("--kind", default="scene",
                       choices=["scene", "makeup", "wardrobe", "dag"])
    p_new.add_argument("--overwrite", action="store_true")

    sp.add_parser("list")

    p_load = sp.add_parser("show"); p_load.add_argument("slug")
    p_imp = sp.add_parser("import"); p_imp.add_argument("slug"); p_imp.add_argument("src")
    p_imp.add_argument("--into", default="assets")
    p_del = sp.add_parser("delete"); p_del.add_argument("slug")

    args = ap.parse_args(argv)

    if args.cmd == "new":
        pdir = new(args.name, kind=args.kind, overwrite=args.overwrite)
        print(pdir); return 0
    if args.cmd == "list":
        rows = list_projects()
        if not rows:
            print("(no projects)"); return 0
        w = max(len(r["slug"]) for r in rows)
        for r in rows:
            print(f"  {r['slug']:<{w}}  {r['kind']:<8}  {r['updated']}  {r['name']}")
        return 0
    if args.cmd == "show":
        print(json.dumps(load_scene(args.slug), indent=2)); return 0
    if args.cmd == "import":
        pdir = project_path(args.slug)
        dst = import_asset(pdir, args.src, into=args.into)
        print(dst); return 0
    if args.cmd == "delete":
        ok = delete(args.slug)
        print("deleted" if ok else "not found"); return 0 if ok else 1
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
