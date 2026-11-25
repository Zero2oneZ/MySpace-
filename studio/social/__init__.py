"""social — cross-platform media distribution for MySpace++.

Uploads assets from studio/media/ to YouTube, Telegram, Facebook, and
WhatsApp Business (official Cloud API only).

All uploaders read keys from the shared .env (mirrored to gently/).
Usage is logged to studio/logs/social_uploads.jsonl for audit + cost tracking.

Example:
    from social import UploadClient
    c = UploadClient()
    c.upload("studio/media/Media/Video/clip.mp4", platforms=["youtube", "telegram"])
"""
from __future__ import annotations

from .client import UploadClient, UploadResult

__all__ = ["UploadClient", "UploadResult"]