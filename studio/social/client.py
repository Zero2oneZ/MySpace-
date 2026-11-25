"""client.py — unified social upload dispatcher.

Reads sidecar metadata, picks the right uploader per platform, logs results.

Usage:
    from social import UploadClient
    c = UploadClient()
    c.upload("media/Media/Video/clip.mp4", platforms=["youtube", "telegram", "facebook"])

Platforms:
    youtube     → social.youtube.upload_video
    telegram    → social.telegram.upload
    facebook    → social.facebook.upload
    whatsapp    → social.whatsapp.upload_media (returns media_id; send separately)
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Resolve paths
HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent
sys.path.insert(0, str(STUDIO))

import paths  # noqa: E402

LOG_PATH = paths.LOGS_ROOT / "social_uploads.jsonl"


try:
    from social import youtube, telegram, facebook, whatsapp, discord, twitch, onlyfans, twilio, tiktok
except ImportError:
    import youtube, telegram, facebook, whatsapp, discord, twitch, onlyfans, twilio, tiktok  # type: ignore


@dataclass
class UploadResult:
    platform: str
    success: bool
    url: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


class UploadClient:
    """Dispatch uploads to one or more social platforms."""

    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or LOG_PATH
        self._ensure_log()

    def _ensure_log(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.write_text("")

    def _read_sidecar(self, media_path: Path) -> dict:
        """Read sidecar JSON next to the media file if it exists."""
        sidecar_path = media_path.with_suffix(media_path.suffix + ".json")
        if not sidecar_path.exists():
            sidecar_path = media_path.parent / (media_path.stem + ".json")
        if sidecar_path.exists():
            try:
                return json.loads(sidecar_path.read_text())
            except Exception:
                pass
        return {}

    def _write_log(self, entry: dict) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def upload(
        self,
        file_path: str | Path,
        platforms: list[str],
        title: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> list[UploadResult]:
        """Upload a single file to every named platform.

        Args:
            file_path: path to media file
            platforms: list of platform names (youtube, telegram, facebook, whatsapp)
            title: override title; falls back to sidecar label or filename stem
            description: override description; falls back to sidecar description
            tags: override tags; falls back to sidecar tags

        Returns:
            list of UploadResult, one per platform (same order as input).
        """
        file_path = Path(file_path)
        sidecar = self._read_sidecar(file_path)

        resolved_title = title or sidecar.get("label") or sidecar.get("title") or file_path.stem
        resolved_desc = description or sidecar.get("description", "")
        resolved_tags = tags or sidecar.get("tags", [])

        results: list[UploadResult] = []
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        _dispatch = {
            "youtube": lambda: youtube.upload_video(
                file_path, title=resolved_title, description=resolved_desc, tags=resolved_tags
            ),
            "telegram": lambda: telegram.upload(
                file_path, caption=f"{resolved_title}\n{resolved_desc}".strip()
            ),
            "facebook": lambda: facebook.upload(
                file_path, message=f"{resolved_title}\n{resolved_desc}".strip()
            ),
            "whatsapp": lambda: whatsapp.upload_media(file_path),
            "discord": lambda: discord.upload(
                file_path, message=f"{resolved_title}\n{resolved_desc}".strip()
            ),
            "twitch": lambda: twitch.upload(
                file_path, message=f"{resolved_title}\n{resolved_desc}".strip()
            ),
            "onlyfans": lambda: onlyfans.upload(
                file_path, title=resolved_title, description=resolved_desc
            ),
            "twilio": lambda: twilio.send_mms(
                file_path,
                to_phone=os.environ.get("twilio_to_phone", "").strip(),
                message=f"{resolved_title}\n{resolved_desc}".strip(),
            ),
            "tiktok": lambda: tiktok.upload(
                file_path, title=resolved_title, description=resolved_desc
            ),
        }

        for plat in platforms:
            plat = plat.lower().strip()
            result = UploadResult(platform=plat, success=False)
            try:
                fn = _dispatch.get(plat)
                if fn is None:
                    result.error = f"Unknown platform: {plat}"
                else:
                    r = fn()
                    result.success = r.success
                    result.url = r.url
                    result.error = r.error
                    result.raw = r.raw
                    if plat == "whatsapp" and r.success and getattr(r, "media_id", None):
                        result.url = f"media_id:{r.media_id}"
            except Exception as e:
                result.error = str(e)

            self._write_log({
                "ts": ts,
                "platform": plat,
                "file": str(file_path),
                "title": resolved_title,
                "success": result.success,
                "url": result.url,
                "error": result.error,
            })
            results.append(result)

        return results
