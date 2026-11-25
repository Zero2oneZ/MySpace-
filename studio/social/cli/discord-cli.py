#!/usr/bin/env python3
"""discord-cli.py — Discord bot CLI for MySpace++.

Uses keys from .env:
    DISCORD_BOT_TOKEN=...
    DISCORD_CLIENT_ID=...
    DISCORD_CLIENT_SECRET=...
    DISCORD_PUBLIC_KEY=...

Commands:
    send <channel_id> <message>     — send a message
    upload <channel_id> <file>      — upload a file with optional message
    me                              — show bot info
    guilds                          — list guilds the bot is in
    channels <guild_id>             — list channels in a guild
"""
from __future__ import annotations

import json
import mimetypes
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from _env import key  # noqa: E402
from _http import post, get  # noqa: E402

API = "https://discord.com/api/v10"
TOKEN = key("DISCORD_BOT_TOKEN") or key("discord_token", "")


def _headers() -> dict:
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)
    return {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}


def cmd_me() -> None:
    r = get(f"{API}/users/@me", headers=_headers(), timeout=15)
    if r.status_code == 200:
        print(json.dumps(r.json(), indent=2))
    else:
        print(f"Error {r.status_code}: {r.text[:200]}", file=sys.stderr)


def cmd_guilds() -> None:
    r = get(f"{API}/users/@me/guilds", headers=_headers(), timeout=15)
    if r.status_code == 200:
        for g in r.json():
            print(f"{g['id']:20s} {g['name']}")
    else:
        print(f"Error {r.status_code}: {r.text[:200]}", file=sys.stderr)


def cmd_channels(guild_id: str) -> None:
    r = get(f"{API}/guilds/{guild_id}/channels", headers=_headers(), timeout=15)
    if r.status_code == 200:
        for c in r.json():
            print(f"{c['id']:20s} #{c['name']:30s} ({c['type']})")
    else:
        print(f"Error {r.status_code}: {r.text[:200]}", file=sys.stderr)


def cmd_send(channel_id: str, message: str) -> None:
    payload = {"content": message}
    r = post(
        f"{API}/channels/{channel_id}/messages",
        headers=_headers(),
        content=json.dumps(payload).encode(),
        timeout=15,
    )
    if r.status_code in (200, 201):
        body = r.json()
        print(f"Sent message_id={body.get('id')}")
    else:
        print(f"Error {r.status_code}: {r.text[:200]}", file=sys.stderr)


def cmd_upload(channel_id: str, file_path: str, message: str = "") -> None:
    p = Path(file_path)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        sys.exit(1)
    boundary = "----DiscordCLIBoundary"
    parts = []
    if message:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="content"\r\n\r\n{message}\r\n'
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n'
    )
    body = (
        b"".join(part.encode() for part in parts)
        + p.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    headers = {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    r = post(f"{API}/channels/{channel_id}/messages", headers=headers, data=body, timeout=60)
    if r.status_code in (200, 201):
        body_json = r.json()
        print(f"Uploaded message_id={body_json.get('id')}")
    else:
        print(f"Error {r.status_code}: {r.text[:400]}", file=sys.stderr)


def _usage() -> None:
    print("Usage: discord-cli.py <command> [args...]")
    print("  me")
    print("  guilds")
    print("  channels <guild_id>")
    print("  send <channel_id> <message>")
    print("  upload <channel_id> <file> [message]")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "me":
        cmd_me()
    elif cmd == "guilds":
        cmd_guilds()
    elif cmd == "channels":
        if not args:
            _usage()
        cmd_channels(args[0])
    elif cmd == "send":
        if len(args) < 2:
            _usage()
        cmd_send(args[0], " ".join(args[1:]))
    elif cmd == "upload":
        if len(args) < 2:
            _usage()
        cmd_upload(args[0], args[1], " ".join(args[2:]) if len(args) > 2 else "")
    else:
        _usage()


if __name__ == "__main__":
    main()
