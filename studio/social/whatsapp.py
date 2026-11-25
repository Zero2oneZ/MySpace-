"""whatsapp.py — WhatsApp Business Cloud API media uploader.

Reads from .env:
    whatsapp_business_token=EAAG...       # Meta Business token (same as FB)
    whatsapp_phone_number_id=1234567890   # Registered WhatsApp Business phone number ID
    whatsapp_business_account_id=...      # Optional, for analytics

This uses ONLY the official Meta Cloud API — no unofficial scrapers,
no web-clients, no automation that violates WhatsApp ToS.

Prerequisites:
  1. Meta Business account at https://business.facebook.com/
  2. WhatsApp Business account linked
  3. Phone number verified for WhatsApp Cloud API
  4. Recipient phone number opted in to receive messages

Media upload (2-step):
  Step 1: POST media to https://graph.facebook.com/v18.0/<phone_number_id>/media
  Step 2: POST message with the media ID to /messages

We only implement Step 1 here (upload media to Meta's CDN) and return
the media_id. The actual message send is left to the caller because
recipient opt-in + message templating is business-specific.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from social import _http as httpx

GRAPH = "https://graph.facebook.com/v18.0"


@dataclass
class UploadResult:
    platform: str = "whatsapp"
    success: bool = False
    media_id: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _token() -> str:
    t = os.environ.get("whatsapp_business_token", "").strip()
    if not t:
        raise RuntimeError("Missing .env key: whatsapp_business_token")
    return t


def _phone_number_id() -> str:
    p = os.environ.get("whatsapp_phone_number_id", "").strip()
    if not p:
        raise RuntimeError("Missing .env key: whatsapp_phone_number_id")
    return p


def upload_media(
    file_path: Path,
    token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> UploadResult:
    """Upload media to WhatsApp Business CDN. Returns UploadResult with media_id.

    To actually send the media to a recipient, use the returned media_id in a
    POST /messages call with type="image"|"video"|"audio"|"document".
    """
    tok = token or _token()
    pid = phone_number_id or _phone_number_id()
    file_path = Path(file_path)
    if not file_path.exists():
        return UploadResult(error=f"File not found: {file_path}")

    url = f"{GRAPH}/{pid}/media"

    # Determine messaging_type from extension
    ext = file_path.suffix.lower()
    messaging_type = {
        ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image",
        ".mp4": "video", ".3gp": "video",
        ".mp3": "audio", ".ogg": "audio", ".wav": "audio", ".aac": "audio",
        ".pdf": "document", ".doc": "document", ".docx": "document",
        ".txt": "document",
    }.get(ext, "document")

    data = {"messaging_product": "whatsapp", "type": messaging_type}

    try:
        if hasattr(httpx, "post"):
            files = {"file": (file_path.name, file_path.read_bytes())}
            r = httpx.post(url, data=data, files=files, timeout=120)
        else:
            boundary = "----MySpaceBoundary"
            parts = []
            for k, v in data.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n'
            )
            body = b"".join(p.encode() for p in parts) + file_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
            with httpx.Client(timeout=120) as c:
                r = c.post(url, headers=headers, content=body)
    except Exception as e:
        return UploadResult(error=f"WhatsApp media upload failed: {e}")

    if r.status_code != 200:
        return UploadResult(error=f"WhatsApp HTTP {r.status_code}: {r.text[:400]}")

    body = r.json() if r.text else {}
    if "error" in body:
        return UploadResult(error=f"WhatsApp API error: {body['error']}")

    mid = body.get("id")
    return UploadResult(
        success=bool(mid),
        media_id=mid,
        raw=body,
    )


def send_media_message(
    recipient_phone: str,
    media_id: str,
    media_type: str = "image",
    caption: str = "",
    token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> dict:
    """Send a media message to a specific recipient using a previously-uploaded media_id.

    recipient_phone must include country code, e.g. +14155551234.
    media_type is one of: image, video, audio, document.
    """
    tok = token or _token()
    pid = phone_number_id or _phone_number_id()
    url = f"{GRAPH}/{pid}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient_phone,
        "type": media_type,
        media_type: {"id": media_id, "caption": caption} if caption else {"id": media_id},
    }

    headers = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    try:
        if hasattr(httpx, "post"):
            r = httpx.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        else:
            with httpx.Client(timeout=30) as c:
                r = c.post(url, headers=headers, content=json.dumps(payload).encode())
    except Exception as e:
        return {"error": str(e)}

    return r.json() if r.text else {"http_status": r.status_code}
