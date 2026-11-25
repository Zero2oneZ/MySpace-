#!/usr/bin/env python3
"""snapchat-cli.py — Snapchat Marketing API CLI for MySpace++.

Uses keys from .env:
    SNAPCHAT_STAGE=...          # OAuth token (from .env)
    Or: snapchat_access_token=...

Commands:
    me                              — show organization info
    campaigns <org_id>               — list campaigns
    create_ad <org_id> <campaign_id> <name> <file> — upload creative + create ad
    upload_media <org_id> <file>    — upload media asset

Endpoint: https://adsapi.snapchat.com/v1/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from _env import key  # noqa: E402
from _http import post, get  # noqa: E402

API = "https://adsapi.snapchat.com/v1"
TOKEN = key("SNAPCHAT_STAGE") or key("snapchat_access_token", "")


def _headers() -> dict:
    if not TOKEN:
        print("Error: SNAPCHAT_STAGE (or snapchat_access_token) not set in .env", file=sys.stderr)
        sys.exit(1)
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def cmd_me() -> None:
    r = get(f"{API}/me", headers=_headers(), timeout=15)
    print(json.dumps(r.json() if r.text else {}, indent=2))


def cmd_campaigns(org_id: str) -> None:
    r = get(f"{API}/adaccounts?organization_id={org_id}", headers=_headers(), timeout=15)
    body = r.json() if r.text else {}
    for item in body.get("adaccounts", []):
        print(f"{item.get('id', '?'):20s} {item.get('name', '')}")


def cmd_upload_media(org_id: str, file_path: str) -> None:
    p = Path(file_path)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        sys.exit(1)
    # Snapchat media upload is a 2-step process: register then upload
    # This is a simplified flow
    boundary = "----SnapBoundary"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n'
    ]
    body = b"".join(part.encode() for part in parts) + p.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": f"multipart/form-data; boundary={boundary}"}
    r = post(f"{API}/media", headers=headers, data=body, timeout=120)
    print(json.dumps(r.json() if r.text else {}, indent=2))


def _usage() -> None:
    print("Usage: snapchat-cli.py <command> [args...]")
    print("  me")
    print("  campaigns <org_id>")
    print("  upload_media <org_id> <file>")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "me":
        cmd_me()
    elif cmd == "campaigns":
        if not args:
            _usage()
        cmd_campaigns(args[0])
    elif cmd == "upload_media":
        if len(args) < 2:
            _usage()
        cmd_upload_media(args[0], args[1])
    else:
        _usage()


if __name__ == "__main__":
    main()
