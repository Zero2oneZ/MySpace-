#!/usr/bin/env python3
"""telegram-cli.py — Telegram Bot CLI for MySpace++.

Uses keys from .env:
    TELEGRAM_BOT_TOKEN=...    (or telegram_bot_token)
    TELEGRAM_CHAT_ID=...      (or telegram_chat_id)

Commands:
    me                              — show bot info
    send <chat> <message>           — send a text message
    upload <chat> <file> [caption]  — upload a file
    polls <chat> <question> <option1> <option2> ... — send a poll
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from _env import key  # noqa: E402
from _http import post, get  # noqa: E402

API = "https://api.telegram.org/bot{token}"
TOKEN = key("TELEGRAM_BOT_TOKEN") or key("telegram_bot_token", "")
DEFAULT_CHAT = key("TELEGRAM_CHAT_ID") or key("telegram_chat_id", "")


def _api(method: str) -> str:
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)
    return API.format(token=TOKEN) + "/" + method


def cmd_me() -> None:
    r = get(_api("getMe"), timeout=15)
    print(json.dumps(r.json() if r.text else {}, indent=2))


def cmd_send(chat_id: str, message: str) -> None:
    payload = {"chat_id": chat_id, "text": message}
    r = post(_api("sendMessage"), content=json.dumps(payload).encode(), timeout=15)
    body = r.json() if r.text else {}
    if body.get("ok"):
        print(f"Sent message_id={body['result'].get('message_id')}")
    else:
        print(f"Error: {body.get('description')}", file=sys.stderr)


def cmd_upload(chat_id: str, file_path: str, caption: str = "") -> None:
    p = Path(file_path)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        sys.exit(1)
    # Determine method by MIME type
    import mimetypes
    mt, _ = mimetypes.guess_type(str(p))
    main = mt.split("/")[0] if mt else "document"
    method = {
        "image": "sendPhoto",
        "video": "sendVideo",
        "audio": "sendAudio",
    }.get(main, "sendDocument")

    boundary = "----TelegramCLIBoundary"
    parts = []
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
    )
    if caption:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
        )
    field = method.replace("send", "").lower()
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{p.name}"\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n'
    )
    body = (
        b"".join(part.encode() for part in parts)
        + p.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    r = post(_api(method), headers=headers, data=body, timeout=120)
    body_json = r.json() if r.text else {}
    if body_json.get("ok"):
        print(f"Uploaded message_id={body_json['result'].get('message_id')}")
    else:
        print(f"Error: {body_json.get('description')}", file=sys.stderr)


def cmd_poll(chat_id: str, question: str, *options: str) -> None:
    if len(options) < 2:
        print("Need at least 2 options for a poll", file=sys.stderr)
        sys.exit(1)
    payload = {"chat_id": chat_id, "question": question, "options": [{"text": o} for o in options]}
    r = post(_api("sendPoll"), content=json.dumps(payload).encode(), timeout=15)
    body = r.json() if r.text else {}
    if body.get("ok"):
        print(f"Poll sent message_id={body['result'].get('message_id')}")
    else:
        print(f"Error: {body.get('description')}", file=sys.stderr)


def _usage() -> None:
    print("Usage: telegram-cli.py <command> [args...]")
    print("  me")
    print("  send <chat_id> <message>")
    print("  upload <chat_id> <file> [caption]")
    print("  poll <chat_id> <question> <option1> <option2> ...")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "me":
        cmd_me()
    elif cmd == "send":
        if len(args) < 2:
            _usage()
        cmd_send(args[0], " ".join(args[1:]))
    elif cmd == "upload":
        if len(args) < 2:
            _usage()
        cmd_upload(args[0], args[1], " ".join(args[2:]) if len(args) > 2 else "")
    elif cmd == "poll":
        if len(args) < 4:
            _usage()
        cmd_poll(args[0], args[1], *args[2:])
    else:
        _usage()


if __name__ == "__main__":
    main()
