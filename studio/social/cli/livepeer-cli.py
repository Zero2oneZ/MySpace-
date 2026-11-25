#!/usr/bin/env python3
"""livepeer-cli.py — Livepeer Studio API CLI for MySpace++.

Uses keys from .env:
    LIVEPEER_API_KEY=...

Commands:
    streams                         — list all streams
    create <name>                  — create a new stream
    get <stream_id>                — get stream details
    delete <stream_id>             — delete a stream
    assets                          — list uploaded assets
    upload <file> [name]            — upload a video asset
    transcode <asset_id>           — request transcoding

Endpoint: https://livepeer.studio/api/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from _env import key  # noqa: E402
from _http import post, get  # noqa: E402

API = "https://livepeer.studio/api"
TOKEN = key("LIVEPEER_API_KEY", "")


def _headers() -> dict:
    if not TOKEN:
        print("Error: LIVEPEER_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def cmd_streams() -> None:
    r = get(f"{API}/stream", headers=_headers(), timeout=15)
    body = r.json() if r.text else {}
    for s in body:
        print(f"{s.get('id', '?'):30s} {s.get('name', ''):20s} active={s.get('isActive', False)}")


def cmd_create(name: str) -> None:
    payload = {"name": name}
    r = post(f"{API}/stream", headers=_headers(), content=json.dumps(payload).encode(), timeout=15)
    body = r.json() if r.text else {}
    print(json.dumps(body, indent=2))


def cmd_get(stream_id: str) -> None:
    r = get(f"{API}/stream/{stream_id}", headers=_headers(), timeout=15)
    print(json.dumps(r.json() if r.text else {}, indent=2))


def cmd_delete(stream_id: str) -> None:
    import urllib.request
    import ssl
    req = urllib.request.Request(
        f"{API}/stream/{stream_id}",
        headers=_headers(),
        method="DELETE",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            print(f"Deleted {stream_id} (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        print(f"Error HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)


def cmd_assets() -> None:
    r = get(f"{API}/asset", headers=_headers(), timeout=15)
    body = r.json() if r.text else {}
    for a in body:
        print(f"{a.get('id', '?'):30s} {a.get('name', ''):20s} {a.get('status', '')}")


def cmd_upload(file_path: str, name: str = "") -> None:
    p = Path(file_path)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        sys.exit(1)
    # Step 1: Request upload URL
    payload = {"name": name or p.stem}
    r = post(f"{API}/asset/request-upload", headers=_headers(), content=json.dumps(payload).encode(), timeout=15)
    body = r.json() if r.text else {}
    upload_url = body.get("url")
    asset_id = body.get("asset", {}).get("id")
    if not upload_url:
        print(f"Failed to get upload URL: {body}", file=sys.stderr)
        sys.exit(1)
    # Step 2: PUT file to upload_url
    import urllib.request
    import ssl
    req = urllib.request.Request(upload_url, data=p.read_bytes(), method="PUT")
    req.add_header("Content-Type", "application/octet-stream")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
            print(f"Uploaded asset_id={asset_id} (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        print(f"Upload failed HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)


def _usage() -> None:
    print("Usage: livepeer-cli.py <command> [args...]")
    print("  streams")
    print("  create <name>")
    print("  get <stream_id>")
    print("  delete <stream_id>")
    print("  assets")
    print("  upload <file> [name]")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "streams":
        cmd_streams()
    elif cmd == "create":
        if not args:
            _usage()
        cmd_create(args[0])
    elif cmd == "get":
        if not args:
            _usage()
        cmd_get(args[0])
    elif cmd == "delete":
        if not args:
            _usage()
        cmd_delete(args[0])
    elif cmd == "assets":
        cmd_assets()
    elif cmd == "upload":
        if not args:
            _usage()
        cmd_upload(args[0], args[1] if len(args) > 1 else "")
    else:
        _usage()


if __name__ == "__main__":
    main()
