"""telegram.py — Telegram Bot API media uploader.

Reads from .env:
    telegram_bot_token=123456:ABC-DEF...   # from @BotFather
    telegram_chat_id=@mychannel or -100... # target channel / group / user

Supports photos, videos, documents, audio. Picks send method by MIME type.
Endpoint: https://api.telegram.org/bot<token>/<method>
"""
from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from social import _http as httpx

API_BASE = "https://api.telegram.org/bot{token}"


@dataclass
class UploadResult:
    platform: str = "telegram"
    success: bool = False
    message_id: Optional[int] = None
    url: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _token() -> str:
    t = os.environ.get("telegram_bot_token", "").strip() or os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not t:
        raise RuntimeError("Missing .env key: telegram_bot_token or TELEGRAM_BOT_TOKEN")
    return t


def _chat_id() -> str:
    c = os.environ.get("telegram_chat_id", "").strip() or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not c:
        raise RuntimeError("Missing .env key: telegram_chat_id or TELEGRAM_CHAT_ID")
    return c


def _method_by_mime(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    if not mt:
        return "sendDocument"
    main, sub = mt.split("/", 1)
    if main == "image":
        return "sendPhoto"
    if main == "video":
        return "sendVideo"
    if main == "audio":
        return "sendAudio"
    return "sendDocument"


def upload(
    file_path: Path,
    caption: str = "",
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> UploadResult:
    """Upload a file to Telegram. Returns UploadResult."""
    tok = token or _token()
    cid = chat_id or _chat_id()
    file_path = Path(file_path)
    if not file_path.exists():
        return UploadResult(error=f"File not found: {file_path}")

    method = _method_by_mime(file_path)
    url = f"{API_BASE.format(token=tok)}/{method}"

    # Telegram expects multipart form data
    data = {"chat_id": cid, "caption": caption}
    files = {method.replace("send", "").lower(): (file_path.name, file_path.read_bytes())}

    try:
        if hasattr(httpx, "post"):
            # requests
            r = httpx.post(url, data=data, files=files, timeout=120)
        else:
            # httpx (we need to build multipart manually)
            boundary = "----MySpaceBoundary"
            body_parts = []
            for k, v in data.items():
                body_parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
            file_field = method.replace("send", "").lower()
            body_parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n'
            )
            body = b"".join(p.encode() for p in body_parts) + file_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
            with httpx.Client(timeout=120) as c:
                r = c.post(url, headers=headers, content=body)
    except Exception as e:
        return UploadResult(error=f"Telegram upload failed: {e}")

    if r.status_code != 200:
        return UploadResult(error=f"Telegram HTTP {r.status_code}: {r.text[:400]}")

    body = r.json() if r.text else {}
    if not body.get("ok"):
        return UploadResult(error=f"Telegram API error: {body.get('description')}")

    msg = body.get("result", {})
    mid = msg.get("message_id")
    return UploadResult(
        success=True,
        message_id=mid,
        url=None,  # Telegram messages don't have public URLs unless in a public channel
        raw=body,
    )


def send_message(
    text: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> UploadResult:
    """Send a plain text message to Telegram. Returns UploadResult."""
    tok = token or _token()
    cid = chat_id or _chat_id()
    url = f"{API_BASE.format(token=tok)}/sendMessage"
    payload = json.dumps({"chat_id": cid, "text": text, "parse_mode": "Markdown"}).encode()
    try:
        r = httpx.post(url, headers={"Content-Type": "application/json"}, content=payload, timeout=30)
    except Exception as e:
        return UploadResult(error=f"Telegram send failed: {e}")
    if r.status_code != 200:
        return UploadResult(error=f"Telegram HTTP {r.status_code}: {r.text[:400]}")
    body = r.json() if r.text else {}
    if not body.get("ok"):
        return UploadResult(error=f"Telegram API error: {body.get('description')}")
    msg = body.get("result", {})
    return UploadResult(success=True, message_id=msg.get("message_id"), raw=body)
