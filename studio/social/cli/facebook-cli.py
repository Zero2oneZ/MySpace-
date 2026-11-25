#!/usr/bin/env python3
"""facebook-cli.py — Facebook Graph API CLI for MySpace++.

Uses keys from .env:
    facebook_page_token=...
    facebook_page_id=...

Commands:
    me                              — show page info
    post <message> [file]           — post text or photo/video to page
    photos                          — list recent photos
    videos                          — list recent videos
    insights                        — page insights (engagement)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from _env import key  # noqa: E402
from _http import post, get  # noqa: E402

GRAPH = "https://graph.facebook.com/v18.0"
TOKEN = key("facebook_page_token", "")
PAGE_ID = key("facebook_page_id", "")


def _token() -> str:
    if not TOKEN:
        print("Error: facebook_page_token not set in .env", file=sys.stderr)
        sys.exit(1)
    return TOKEN


def _page() -> str:
    if not PAGE_ID:
        print("Error: facebook_page_id not set in .env", file=sys.stderr)
        sys.exit(1)
    return PAGE_ID


def cmd_me() -> None:
    r = get(f"{GRAPH}/{_page()}?access_token={_token()}", timeout=15)
    print(json.dumps(r.json() if r.text else {}, indent=2))


def cmd_post(message: str, file_path: str | None = None) -> None:
    if file_path:
        p = Path(file_path)
        if not p.exists():
            print(f"File not found: {p}", file=sys.stderr)
            sys.exit(1)
        is_video = p.suffix.lower() in {".mp4", ".mov", ".avi", ".webm"}
        edge = "videos" if is_video else "photos"
        url = f"{GRAPH}/{_page()}/{edge}"
        data = {"access_token": _token(), "description" if is_video else "caption": message}
        boundary = "----FBCLIBoundary"
        parts = []
        for k, v in data.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n'
        )
        body = (
            b"".join(part.encode() for part in parts)
            + p.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        r = post(url, headers=headers, data=body, timeout=120)
    else:
        url = f"{GRAPH}/{_page()}/feed"
        payload = {"message": message, "access_token": _token()}
        r = post(url, content=json.dumps(payload).encode(), timeout=15)
    body = r.json() if r.text else {}
    if "id" in body:
        print(f"Posted id={body['id']}")
    else:
        print(f"Error: {body}", file=sys.stderr)


def cmd_photos() -> None:
    r = get(f"{GRAPH}/{_page()}/photos?access_token={_token()}", timeout=15)
    body = r.json() if r.text else {}
    for item in body.get("data", []):
        print(f"{item.get('id', '?'):20s} {item.get('created_time', '')}")


def cmd_videos() -> None:
    r = get(f"{GRAPH}/{_page()}/videos?access_token={_token()}", timeout=15)
    body = r.json() if r.text else {}
    for item in body.get("data", []):
        print(f"{item.get('id', '?'):20s} {item.get('created_time', '')} {item.get('title', '')}")


def cmd_insights() -> None:
    r = get(
        f"{GRAPH}/{_page()}/insights?access_token={_token()}&metric=page_impressions,page_engaged_users",
        timeout=15,
    )
    print(json.dumps(r.json() if r.text else {}, indent=2))


def _usage() -> None:
    print("Usage: facebook-cli.py <command> [args...]")
    print("  me")
    print("  post <message> [file]")
    print("  photos")
    print("  videos")
    print("  insights")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "me":
        cmd_me()
    elif cmd == "post":
        if not args:
            _usage()
        cmd_post(args[0], args[1] if len(args) > 1 else None)
    elif cmd == "photos":
        cmd_photos()
    elif cmd == "videos":
        cmd_videos()
    elif cmd == "insights":
        cmd_insights()
    else:
        _usage()


if __name__ == "__main__":
    main()
