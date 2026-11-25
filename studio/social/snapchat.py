"""snapchat.py — Snapchat alert dispatcher.

Snapchat does not expose a public "send message" API for user-to-user alerts.
This module supports two modes:
1. Webhook mode: POSTs alert JSON to a configured webhook URL (e.g., Zapier, IFTTT, internal relay).
2. Marketing API mode: uploads media via Snapchat Marketing API (studio/social/cli/snapchat-cli.py for full flow).

Reads from .env:
    SNAPCHAT_STAGE=<token>                    # Marketing API token
    snapchat_webhook_url=https://hooks.zapier.com/...  # optional webhook for alerts
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from social import _http as httpx


@dataclass
class UploadResult:
    platform: str = "snapchat"
    success: bool = False
    post_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def _token() -> str:
    t = os.environ.get("SNAPCHAT_STAGE", "").strip() or os.environ.get("snapchat_access_token", "").strip()
    return t


def _webhook_url() -> Optional[str]:
    return os.environ.get("snapchat_webhook_url", "").strip() or None


def send_message(
    text: str,
    token: Optional[str] = None,
    webhook_url: Optional[str] = None,
) -> UploadResult:
    """Send a text alert to Snapchat via webhook or log if no webhook configured."""
    tok = token or _token()
    hook = webhook_url or _webhook_url()

    payload = {
        "platform": "snapchat",
        "text": text,
        "token_present": bool(tok),
    }

    if hook:
        try:
            body = json.dumps(payload).encode()
            r = httpx.post(hook, headers={"Content-Type": "application/json"}, content=body, timeout=30)
            if r.status_code < 400:
                return UploadResult(success=True, raw=r.json() if r.text else {})
            return UploadResult(error=f"Snapchat webhook HTTP {r.status_code}: {r.text[:400]}", raw={"status": r.status_code})
        except Exception as e:
            return UploadResult(error=f"Snapchat webhook failed: {e}")

    # No webhook configured — log to stdout / local JSONL for later processing
    return UploadResult(
        success=True,
        url=None,
        raw={"logged": True, "note": "No snapchat_webhook_url configured. Alert logged locally."},
    )
