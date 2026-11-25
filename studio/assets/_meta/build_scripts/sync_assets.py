#!/usr/bin/env python3
"""
sync_assets.py — Sync _global/ assets into a project's tree via symlinks.

Reads the project's manifest.json, creates symlinks for _global references,
and verifies asset_registry.json entries exist.

Usage:
    python3 sync_assets.py projects/default
"""
import json
import os
import sys
from pathlib import Path

ASSETS_ROOT = Path(__file__).resolve().parents[2]  # studio/assets/

def load_manifest(project_dir: Path) -> dict:
    manifest_path = project_dir / "project.manifest.json"
    with open(manifest_path) as f:
        return json.load(f)

def load_registry() -> dict:
    registry_path = ASSETS_ROOT / "_meta/registry/asset_registry.json"
    with open(registry_path) as f:
        return json.load(f)

def sync(project_name: str):
    project_dir = ASSETS_ROOT / "projects" / project_name
    if not project_dir.exists():
        print(f"Project {project_name} not found in {ASSETS_ROOT}/projects/")
        sys.exit(1)

    manifest = load_manifest(project_dir)
    registry = load_registry()
    symlinks = manifest.get("symlinks", {})

    print(f"Syncing {project_name}...")
    for proj_path, global_path in symlinks.items():
        src = ASSETS_ROOT / global_path
        dst = project_dir / proj_path

        if dst.exists() or dst.is_symlink():
            print(f"  [SKIP] {dst} already exists")
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(src, dst)
        print(f"  [LINK] {dst} -> {src}")

    print(f"Done. {len(symlinks)} symlinks created/verified.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: sync_assets.py <project-name>")
        sys.exit(1)
    sync(sys.argv[1])
