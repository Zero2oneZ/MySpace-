"""twitch.py — Twitch Helix API tools (chat + clips, not direct video upload).

Twitch does not offer a simple public video upload API for arbitrary content.
The practical "free traffic" uses are:
  1. Post a chat message (requires broadcaster/mod scope)
  2. Create a stream clip (requires clips:edit scope)
  3. Update stream title/category

Reads from .env:
    twitch_client_id=...
    twitch_access_token=...      # OAuth token with chat:edit + clips:edit scopes
    twitch_broadcaster_id=...    # numeric broadcaster user ID
    twitch_channel_name=...      # for chat login

Endpoints:
  Chat: POST https://api.twitch.tv/helix/chat/messages
  Clips: POST https://api.twitch.tv/helix/clips
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from social import _http

HELIX = "https://api.twitch.tv/helix"


@dataclass
class UploadResult:
    platform: str = "twitch"
    success: bool = False
    message_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _client_id() -> str:
    v = os.environ.get("twitch_client_id", "").strip()
    if not v:
        raise RuntimeError("Missing .env key: twitch_client_id")
    return v


def _token() -> str:
    v = os.environ.get("twitch_access_token", "").strip()
    if not v:
        raise RuntimeError("Missing .env key: twitch_access_token")
    return v


def _broadcaster_id() -> str:
    return os.environ.get("twitch_broadcaster_id", "").strip()


def _headers() -> dict:
    return {
        "Client-Id": _client_id(),
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


def send_chat_message(
    message: str,
    broadcaster_id: Optional[str] = None,
    sender_id: Optional[str] = None,
) -> UploadResult:
    """Send a chat message to a Twitch channel. Requires chat:edit scope."""
    bid = broadcaster_id or _broadcaster_id()
    if not bid:
        return UploadResult(error="No twitch_broadcaster_id configured")
    sid = sender_id or bid

    payload = {
        "broadcaster_id": bid,
        "sender_id": sid,
        "message": message,
    }
    r = _http.post(
        f"{HELIX}/chat/messages",
        headers=_headers(),
        content=json.dumps(payload).encode(),
        timeout=30,
    )
    if r.status_code in (200, 201):
        body = r.json() or {}
        return UploadResult(
            success=True,
            message_id=body.get("data", [{}])[0].get("message_id") if body.get("data") else None,
            raw=body,
        )
    return UploadResult(error=f"Twitch chat HTTP {r.status_code}: {r.text[:400]}")


def create_clip(
    broadcaster_id: Optional[str] = None,
    delay_seconds: int = 0,
) -> UploadResult:
    """Create a clip from the current live stream. Requires clips:edit scope."""
    bid = broadcaster_id or _broadcaster_id()
    if not bid:
        return UploadResult(error="No twitch_broadcaster_id configured")

    url = f"{HELIX}/clips?broadcaster_id={bid}&has_delay={str(delay_seconds > 0).lower()}"
    r = _http.post(url, headers=_headers(), timeout=30)
    if r.status_code in (200, 201, 202):
        body = r.json() or {}
        data = body.get("data", [{}])[0] if body.get("data") else {}
        edit_url = data.get("edit_url")
        return UploadResult(
            success=True,
            url=edit_url,
            raw=body,
        )
    return UploadResult(error=f"Twitch clip HTTP {r.status_code}: {r.text[:400]}")


def upload(
    file_path: Path,
    message: str = "",
    **kwargs,
) -> UploadResult:
    """Twitch "upload" — since there is no public video upload, we send a chat
    message with a link to the file (if message contains a URL) or create a clip.
    """
    file_path = Path(file_path)
    if message:
        return send_chat_message(message)
    return create_clip()
