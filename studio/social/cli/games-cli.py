#!/usr/bin/env python3
"""games-cli.py — Game publishing CLI for itch.io + Steam + local dev.

Uses keys from .env:
    # itch.io — Butler (https://itch.io/docs/butler/)
    # No API key needed; butler uses web login
    # Steam — requires steamcmd + app credentials

Commands:
    butler status <project>          — check itch.io build status
    butler push <dir> <user/game>   — push build to itch.io
    butler login                     — authenticate butler
    steam build <app_id> <depot_id> <dir> — build Steam depot (requires steamcmd)
    godot export <project> <preset>   — export with Godot headless
    zip <dir> <out>                   — zip a directory for upload

Binaries expected in studio/.bin/ or PATH:
    butler, steamcmd, godot
"""
from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent.parent.parent
BIN_DIR = STUDIO / ".bin"


def _which(name: str) -> str | None:
    for d in (BIN_DIR,):
        p = d / name
        if p.exists():
            return str(p)
    from shutil import which
    return which(name)


def cmd_butler_status(project: str) -> None:
    butler = _which("butler")
    if not butler:
        print("butler not found. Run: cc -social-dev install", file=sys.stderr)
        sys.exit(1)
    subprocess.run([butler, "status", project])


def cmd_butler_push(dir_path: str, target: str) -> None:
    butler = _which("butler")
    if not butler:
        print("butler not found. Run: cc -social-dev install", file=sys.stderr)
        sys.exit(1)
    subprocess.run([butler, "push", dir_path, target])


def cmd_butler_login() -> None:
    butler = _which("butler")
    if not butler:
        print("butler not found. Run: cc -social-dev install", file=sys.stderr)
        sys.exit(1)
    subprocess.run([butler, "login"])


def cmd_steam_build(app_id: str, depot_id: str, dir_path: str) -> None:
    steamcmd = _which("steamcmd")
    if not steamcmd:
        print("steamcmd not found. Run: cc -social-dev install", file=sys.stderr)
        sys.exit(1)
    print("Steam build requires a vdf script. Generate one with:")
    print(f"  app_build {app_id}")
    print(f"  depot {depot_id} from {dir_path}")
    print("This is a stub — implement vdf generation if needed.")


def cmd_godot_export(project: str, preset: str) -> None:
    godot = _which("godot") or _which("Godot_v4.6.3-stable_linux.x86_64")
    if not godot:
        # Check for the downloaded zip in project root
        zips = list(Path("/data/Projects/MySpace++").glob("Godot_*_linux*.zip"))
        if zips:
            print(f"Godot zip found at {zips[0]}. Extract to studio/.bin/ first.")
        else:
            print("godot not found. Download from godotengine.org and extract to studio/.bin/", file=sys.stderr)
        sys.exit(1)
    subprocess.run([godot, "--headless", "--path", project, "--export-release", preset])


def cmd_zip(dir_path: str, out_path: str) -> None:
    src = Path(dir_path)
    out = Path(out_path)
    if not src.exists():
        print(f"Source not found: {src}", file=sys.stderr)
        sys.exit(1)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src))
    print(f"Zipped {src} → {out} ({out.stat().st_size / 1e6:.1f} MB)")


def _usage() -> None:
    print("Usage: games-cli.py <command> [args...]")
    print("  butler status <user/game>")
    print("  butler push <dir> <user/game>")
    print("  butler login")
    print("  steam build <app_id> <depot_id> <dir>")
    print("  godot export <project_dir> <export_preset>")
    print("  zip <dir> <out.zip>")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
    top = sys.argv[1]
    args = sys.argv[2:]
    if top == "butler":
        if len(args) < 1:
            _usage()
        sub = args[0]
        if sub == "status" and len(args) >= 2:
            cmd_butler_status(args[1])
        elif sub == "push" and len(args) >= 3:
            cmd_butler_push(args[1], args[2])
        elif sub == "login":
            cmd_butler_login()
        else:
            _usage()
    elif top == "steam":
        if len(args) >= 4 and args[0] == "build":
            cmd_steam_build(args[1], args[2], args[3])
        else:
            _usage()
    elif top == "godot":
        if len(args) >= 3 and args[0] == "export":
            cmd_godot_export(args[1], args[2])
        else:
            _usage()
    elif top == "zip":
        if len(args) >= 2:
            cmd_zip(args[0], args[1])
        else:
            _usage()
    else:
        _usage()


if __name__ == "__main__":
    main()
