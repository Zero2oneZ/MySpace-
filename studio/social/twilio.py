"""twilio.py — Twilio SMS / MMS sender.

Reads from .env:
    twilio_account_sid=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    twilio_auth_token=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    twilio_from_phone=+1234567890       # Twilio phone number
    twilio_to_phone=+0987654321          # default recipient (optional)

Endpoint: POST https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json

For MMS (media), include MediaUrl pointing to a publicly accessible URL,
or use the Twilio helper library. Since we work with local files, we
first upload the file to a temporary public URL (or base64 data URI) and
reference it in MediaUrl.

Simpler approach: use Twilio's direct media upload capability by sending
multipart form data with the file.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from social import _http

API_BASE = "https://api.twilio.com/2010-04-01/Accounts"


@dataclass
class UploadResult:
    platform: str = "twilio"
    success: bool = False
    message_sid: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _sid() -> str:
    v = os.environ.get("twilio_account_sid", "").strip()
    if not v:
        raise RuntimeError("Missing .env key: twilio_account_sid")
    return v


def _token() -> str:
    v = os.environ.get("twilio_auth_token", "").strip()
    if not v:
        raise RuntimeError("Missing .env key: twilio_auth_token")
    return v


def _from_phone() -> str:
    v = os.environ.get("twilio_from_phone", "").strip()
    if not v:
        raise RuntimeError("Missing .env key: twilio_from_phone")
    return v


def send_mms(
    file_path: Path,
    to_phone: str,
    message: str = "",
    from_phone: Optional[str] = None,
    account_sid: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> UploadResult:
    """Send an MMS with a local file attachment via Twilio.

    Twilio accepts MediaUrl (public URL) or we can use a data URI.
    For local files, we base64-encode and use a data URI.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return UploadResult(error=f"File not found: {file_path}")

    sid = account_sid or _sid()
    tok = auth_token or _token()
    from_ = from_phone or _from_phone()

    # Build data URI for the media
    b64 = base64.b64encode(file_path.read_bytes()).decode()
    # Determine MIME type from extension
    ext = file_path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".mp4": "video/mp4", ".webm": "video/webm",
    }.get(ext, "application/octet-stream")
    media_url = f"data:{mime};base64,{b64}"

    url = f"{API_BASE}/{sid}/Messages.json"
    # Twilio uses basic auth
    import urllib.request
    import ssl

    payload = {
        "To": to_phone,
        "From": from_,
        "Body": message or " ",
        "MediaUrl": media_url,
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    credentials = base64.b64encode(f"{sid}:{tok}".encode()).decode()
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            body_json = json.loads(body) if body else {}
            return UploadResult(
                success=True,
                message_sid=body_json.get("sid"),
                url=body_json.get("uri"),
                raw=body_json,
            )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.read else ""
        return UploadResult(error=f"Twilio HTTP {e.code}: {body[:400]}")
    except Exception as e:
        return UploadResult(error=f"Twilio send failed: {e}")
