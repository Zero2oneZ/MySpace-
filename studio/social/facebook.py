"""facebook.py — Facebook Graph API page poster (videos + photos).

Reads from .env:
    facebook_page_token=EAAG...          # Page access token
    facebook_page_id=1234567890          # Numeric page ID

To get a page token:
  1. Create an app at https://developers.facebook.com/
  2. Get a User access token with `pages_manage_posts`, `pages_read_engagement`
  3. Exchange for Page token: GET /me/accounts?access_token=<user_token>
  4. Pick the token for the target page

Video endpoint: POST https://graph.facebook.com/v18.0/<page_id>/videos
Photo endpoint: POST https://graph.facebook.com/v18.0/<page_id>/photos
"""
from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from social import _http as httpx

GRAPH = "https://graph.facebook.com/v18.0"


@dataclass
class UploadResult:
    platform: str = "facebook"
    success: bool = False
    post_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _token() -> str:
    t = os.environ.get("facebook_page_token", "").strip()
    if not t:
        raise RuntimeError("Missing .env key: facebook_page_token")
    return t


def _page_id() -> str:
    p = os.environ.get("facebook_page_id", "").strip()
    if not p:
        raise RuntimeError("Missing .env key: facebook_page_id")
    return p


def _is_video(path: Path) -> bool:
    mt, _ = mimetypes.guess_type(str(path))
    return bool(mt and mt.startswith("video/"))


def upload(
    file_path: Path,
    message: str = "",
    token: Optional[str] = None,
    page_id: Optional[str] = None,
) -> UploadResult:
    """Upload a photo or video to a Facebook page. Returns UploadResult."""
    tok = token or _token()
    pid = page_id or _page_id()
    file_path = Path(file_path)
    if not file_path.exists():
        return UploadResult(error=f"File not found: {file_path}")

    is_video = _is_video(file_path)
    edge = "videos" if is_video else "photos"
    url = f"{GRAPH}/{pid}/{edge}"

    data = {"access_token": tok, "published": "true"}
    if message:
        data["description" if is_video else "caption"] = message

    try:
        if hasattr(httpx, "post"):
            files = {"file": (file_path.name, file_path.read_bytes())}
            r = httpx.post(url, data=data, files=files, timeout=120)
        else:
            # httpx multipart manual
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
        return UploadResult(error=f"Facebook upload failed: {e}")

    if r.status_code != 200:
        return UploadResult(error=f"Facebook HTTP {r.status_code}: {r.text[:400]}")

    body = r.json() if r.text else {}
    if "error" in body:
        return UploadResult(error=f"Facebook API error: {body['error']}")

    post_id = body.get("id")
    return UploadResult(
        success=True,
        post_id=post_id,
        url=f"https://facebook.com/{post_id}" if post_id else None,
        raw=body,
    )


def send_message(
    message: str,
    token: Optional[str] = None,
    page_id: Optional[str] = None,
) -> UploadResult:
    """Post a plain text message to a Facebook page feed. Returns UploadResult."""
    tok = token or _token()
    pid = page_id or _page_id()
    url = f"{GRAPH}/{pid}/feed"
    payload = json.dumps({"message": message, "access_token": tok}).encode()
    try:
        r = httpx.post(url, headers={"Content-Type": "application/json"}, content=payload, timeout=30)
    except Exception as e:
        return UploadResult(error=f"Facebook send failed: {e}")
    if r.status_code != 200:
        return UploadResult(error=f"Facebook HTTP {r.status_code}: {r.text[:400]}")
    body = r.json() if r.text else {}
    if "error" in body:
        return UploadResult(error=f"Facebook API error: {body['error']}")
    post_id = body.get("id")
    return UploadResult(success=True, post_id=post_id, url=f"https://facebook.com/{post_id}" if post_id else None, raw=body)
