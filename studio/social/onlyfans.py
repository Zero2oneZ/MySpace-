"""onlyfans.py — OnlyFans Creator API (placeholder).

OnlyFans does not offer a public developer API for uploading content.
Access is restricted to approved partners. This module documents the
requirements and returns a guided error.

If you have approved API access, you would implement:
  - OAuth 2.0 login flow
  - POST /api2/v2/posts/{post_id}/media  to attach media
  - POST /api2/v2/posts  to create a post

Reads from .env (for when API access is granted):
    onlyfans_access_token=...
    onlyfans_user_id=...
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class UploadResult:
    platform: str = "onlyfans"
    success: bool = False
    post_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


def upload(
    file_path: Path,
    title: str = "",
    description: str = "",
    **kwargs,
) -> UploadResult:
    """OnlyFans upload — not available via public API.

    Returns a result with instructions on how to get API access.
    """
    token = os.environ.get("onlyfans_access_token", "").strip()
    if not token:
        return UploadResult(
            error=(
                "OnlyFans does not have a public upload API. "
                "To upload programmatically: (1) Apply for OnlyFans Creator API access "
                "at https://onlyfans.com/apiclient, (2) Once approved, set onlyfans_access_token "
                "and onlyfans_user_id in .env, (3) Re-run this upload."
            )
        )
    # If token exists, we would call the private API here.
    # Since the API spec is not public, this is a stub.
    return UploadResult(
        error="OnlyFans API client exists but upload endpoint is not publicly documented. "
              "Implement the POST /api2/v2/posts flow once you have the spec."
    )
