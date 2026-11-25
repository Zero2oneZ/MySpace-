"""discord.py — Discord webhook / bot media uploader.

Reads from .env:
    discord_webhook_url=https://discord.com/api/webhooks/...
    discord_token=...          # bot token (optional, for bot API upload)
    discord_channel_id=...      # target channel ID (for bot API)

Two modes:
  1. Webhook — simplest, just POST multipart to webhook URL with file attachment.
  2. Bot API — POST /channels/{id}/messages with multipart file.

Endpoint: https://discord.com/api/v10/
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from social import _http


@dataclass
class UploadResult:
    platform: str = "discord"
    success: bool = False
    message_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _webhook_url() -> Optional[str]:
    return os.environ.get("discord_webhook_url", "").strip() or None


def _bot_token() -> Optional[str]:
    return os.environ.get("discord_token", "").strip() or None


def _channel_id() -> Optional[str]:
    return os.environ.get("discord_channel_id", "").strip() or None


def upload(
    file_path: Path,
    message: str = "",
    webhook_url: Optional[str] = None,
    token: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> UploadResult:
    """Upload a file to Discord via webhook or bot API. Returns UploadResult."""
    file_path = Path(file_path)
    if not file_path.exists():
        return UploadResult(error=f"File not found: {file_path}")

    url = webhook_url or _webhook_url()
    tok = token or _bot_token()
    cid = channel_id or _channel_id()

    # Prefer webhook if available
    if url:
        boundary = "----DiscordBoundary"
        parts = []
        if message:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="content"\r\n\r\n{message}\r\n'
            )
        # Discord webhook file field name must be "file"
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n'
        )
        body = (
            b"".join(p.encode() for p in parts)
            + file_path.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}

        r = _http.post(f"{url}?wait=true", headers=headers, data=body, timeout=60)
        if r.status_code in (200, 201, 204):
            body_json = r.json()
            mid = body_json.get("id") if body_json else None
            return UploadResult(
                success=True,
                message_id=mid,
                url=body_json.get("attachments", [{}])[0].get("url") if body_json else None,
                raw=body_json or {},
            )
        return UploadResult(error=f"Discord webhook HTTP {r.status_code}: {r.text[:400]}")

    # Fallback to bot API
    if not tok:
        return UploadResult(error="No discord_webhook_url or discord_token configured")
    if not cid:
        return UploadResult(error="No discord_channel_id configured (required for bot API)")

    boundary = "----DiscordBoundary"
    parts = []
    if message:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="content"\r\n\r\n{message}\r\n'
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n'
    )
    body = (
        b"".join(p.encode() for p in parts)
        + file_path.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    headers = {
        "Authorization": f"Bot {tok}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    api_url = f"https://discord.com/api/v10/channels/{cid}/messages"
    r = _http.post(api_url, headers=headers, data=body, timeout=60)
    if r.status_code in (200, 201):
        body_json = r.json()
        mid = body_json.get("id")
        return UploadResult(
            success=True,
            message_id=mid,
            url=body_json.get("attachments", [{}])[0].get("url") if body_json else None,
            raw=body_json,
        )
    return UploadResult(error=f"Discord bot API HTTP {r.status_code}: {r.text[:400]}")
