"""youtube.py — YouTube Data API v3 uploader (OAuth token required).

Reads from .env:
    youtube_access_token=ya29.a0AfH...   # OAuth 2.0 access token
    youtube_client_id=...               # optional, for refresh
    youtube_client_secret=...            # optional, for refresh

To get an access token:
  1. Go to https://console.cloud.google.com/ → APIs & Services → Credentials
  2. Create OAuth 2.0 client ID (Desktop app)
  3. Enable "YouTube Data API v3"
  4. Run: python -m social.youtube auth   # prints a URL to visit
  5. Paste the auth code back; token is stored in studio/auth/youtube_token.json

Upload endpoint: POST https://www.googleapis.com/upload/youtube/v3/videos
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Use httpx if available (already in project via pinterest), else requests.
from social import _http as httpx

HERE = Path(__file__).resolve().parent
AUTH_DIR = HERE.parent / "auth"
TOKEN_PATH = AUTH_DIR / "youtube_token.json"

YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


@dataclass
class UploadResult:
    platform: str = "youtube"
    success: bool = False
    video_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _load_token() -> Optional[str]:
    """Return access token from auth file or .env."""
    env = os.environ.get("youtube_access_token", "")
    if env:
        return env
    if TOKEN_PATH.exists():
        data = json.loads(TOKEN_PATH.read_text())
        return data.get("access_token")
    return None


def _save_token(data: dict) -> None:
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(data, indent=2))
    os.chmod(TOKEN_PATH, 0o600)


def _env_or_raise(key: str) -> str:
    v = os.environ.get(key, "").strip()
    if not v:
        raise RuntimeError(f"Missing .env key: {key}")
    return v


def _guess_mime(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"


def upload_video(
    file_path: Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "22",  # 22 = People & Blogs
    privacy: str = "private",
    token: Optional[str] = None,
) -> UploadResult:
    """Upload a video file to YouTube. Returns UploadResult."""
    tok = token or _load_token()
    if not tok:
        return UploadResult(
            error="No youtube_access_token in .env or studio/auth/youtube_token.json"
        )

    file_path = Path(file_path)
    if not file_path.exists():
        return UploadResult(error=f"File not found: {file_path}")

    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,  # private / unlisted / public
            "selfDeclaredMadeForKids": False,
        },
    }

    mime = _guess_mime(file_path)
    headers = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": mime,
        "X-Upload-Content-Type": mime,
    }

    # Initiate upload
    params = {"part": "snippet,status", "uploadType": "resumable"}
    try:
        if hasattr(httpx, "post"):
            # requests-like
            r = httpx.post(
                YOUTUBE_UPLOAD_URL,
                params=params,
                headers={**headers, "Content-Type": "application/json; charset=UTF-8"},
                data=json.dumps(metadata),
                timeout=30,
            )
        else:
            # httpx
            with httpx.Client(timeout=30) as c:
                r = c.post(
                    YOUTUBE_UPLOAD_URL,
                    params=params,
                    headers={**headers, "Content-Type": "application/json; charset=UTF-8"},
                    content=json.dumps(metadata).encode(),
                )
    except Exception as e:
        return UploadResult(error=f"Upload initiation failed: {e}")

    if r.status_code not in (200, 201):
        return UploadResult(error=f"YouTube init error {r.status_code}: {r.text[:400]}")

    upload_url = r.headers.get("Location")
    if not upload_url:
        return UploadResult(error="YouTube did not return upload URL")

    # Upload the actual file bytes
    data = file_path.read_bytes()
    try:
        if hasattr(httpx, "post"):
            r2 = httpx.put(upload_url, headers={"Authorization": f"Bearer {tok}"}, data=data, timeout=300)
        else:
            with httpx.Client(timeout=300) as c:
                r2 = c.put(upload_url, headers={"Authorization": f"Bearer {tok}"}, content=data)
    except Exception as e:
        return UploadResult(error=f"Upload PUT failed: {e}")

    if r2.status_code not in (200, 201):
        return UploadResult(error=f"YouTube PUT error {r2.status_code}: {r2.text[:400]}")

    body = r2.json() if r2.text else {}
    vid = body.get("id")
    return UploadResult(
        success=True,
        video_id=vid,
        url=f"https://youtube.com/watch?v={vid}" if vid else None,
        raw=body,
    )


def _auth_flow() -> None:
    """Interactive OAuth flow — prints URL, reads code, stores token."""
    client_id = _env_or_raise("youtube_client_id")
    client_secret = _env_or_raise("youtube_client_secret")
    redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    scope = "https://www.googleapis.com/auth/youtube.upload"

    auth_url = (
        "https://accounts.google.com/o/oauth2/auth"
        f"?client_id={client_id}"
        "&redirect_uri=urn:ietf:wg:oauth:2.0:oob"
        f"&scope={scope}"
        "&response_type=code"
        "&access_type=offline"
    )
    print("Visit this URL in a browser logged into your YouTube channel:")
    print(auth_url)
    code = input("Paste the auth code here: ").strip()

    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    if hasattr(httpx, "post"):
        r = httpx.post(token_url, data=payload, timeout=30)
    else:
        with httpx.Client(timeout=30) as c:
            r = c.post(token_url, data=payload)
    if r.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {r.status_code} {r.text}")
    data = r.json()
    _save_token(data)
    print(f"Token saved to {TOKEN_PATH}")
    print(f"Access token (first 20 chars): {data.get('access_token', '')[:20]}...")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        _auth_flow()
    else:
        print("Usage: python -m social.youtube auth")