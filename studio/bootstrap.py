"""bootstrap.py — make sure the canonical studio tree exists, idempotently.

Every entrypoint (run.sh, run-wardrobe.sh, run-pinterest.sh, run_yt_cutter.sh,
media/.tools/fetch-url.sh) calls `bootstrap.ensure()` before doing anything
else. Safe to run repeatedly; only creates missing dirs and only writes a
README sentinel into brand-new project dirs.

CLI:
    python3 bootstrap.py            # ensure all paths
    python3 bootstrap.py --check    # report missing, exit non-zero if any
    python3 bootstrap.py --report   # print full canonical tree (✓ / · marker)
"""
from __future__ import annotations

import sys
from pathlib import Path

import paths


_SENTINEL_TEXT = (
    "# This directory is managed by studio/bootstrap.py.\n"
    "# Don't rename — `paths.py` is the single source of truth.\n"
)


def ensure(verbose: bool = False) -> list[Path]:
    """Create every canonical directory. Returns the list of dirs *created*
    (i.e. newly made on this call). Existing dirs are left alone."""
    created: list[Path] = []
    for p in paths.all_dirs():
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(p)
            if verbose:
                print(f"  + {p}")
    # Drop a README sentinel into the projects root so users find it.
    readme = paths.PROJECTS_ROOT / "README.md"
    if not readme.exists():
        readme.write_text(
            "# studio/projects/\n\n"
            "Each subdirectory is one saved project. Layout:\n\n"
            "```\n"
            "<project-slug>/\n"
            "├── scene.json     # full scene + flow graph (single source of truth)\n"
            "├── assets/        # project-local asset copies / overrides\n"
            "├── exports/       # rendered exports (PNG, MP4, GLB, …)\n"
            "├── makeup/        # makeup-designer JSONL layer stacks\n"
            "├── renders/       # raster renders of the 3-D scene\n"
            "└── layers/        # SVG layer drops from the designer wizards\n"
            "```\n\n"
            "Use `project_io.new(name)` to create, `project_io.list_projects()` to enumerate.\n"
        )
    return created


def check() -> list[Path]:
    """Return the list of expected dirs that are MISSING."""
    return [p for p in paths.all_dirs() if not p.is_dir()]


def report() -> None:
    """Print every canonical path with a ✓ / · marker."""
    for p in paths.all_dirs():
        marker = "✓" if p.is_dir() else "·"
        print(f"  {marker} {p}")


def main(argv: list[str]) -> int:
    if "--check" in argv:
        missing = check()
        if missing:
            print(f"missing {len(missing)} dirs:", file=sys.stderr)
            for p in missing:
                print(f"  · {p}", file=sys.stderr)
            return 1
        print("all canonical dirs present")
        return 0
    if "--report" in argv:
        report()
        return 0
    created = ensure(verbose=True)
    print(f"bootstrap: {len(created)} dirs created, "
          f"{len(paths.all_dirs()) - len(created)} already present.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
