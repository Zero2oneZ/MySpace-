"""oauth_registry.py — OAuth 2.0 configurations for all major social platforms.

Each platform entry defines:
- auth_url     — where to redirect the user
- token_url    — where to exchange code for token
- refresh_url  — where to refresh (usually same as token_url)
- scopes       — list of scopes to request
- client_id_env — env var name for the client ID
- client_secret_env — env var name for the client secret
- redirect_uri — callback URL (default: http://localhost:8765/oauth/callback/{platform})
- use_pkce     — whether to use PKCE (code_challenge)
- extra_params — platform-specific query params

All client secrets live in .env (never committed). This file is pure config.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Optional


@dataclass
class OAuthConfig:
    name: str
    auth_url: str
    token_url: str
    refresh_url: str
    scopes: list[str]
    client_id_env: str
    client_secret_env: str
    redirect_uri: str
    use_pkce: bool = True
    extra_auth_params: dict = None
    extra_token_params: dict = None


def _redirect(platform: str) -> str:
    base = os.environ.get("OAUTH_REDIRECT_BASE", "http://localhost:8765")
    return f"{base}/oauth/callback/{platform}"


OAUTH_CONFIGS: dict[str, OAuthConfig] = {
    "google": OAuthConfig(
        name="Google / YouTube",
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        refresh_url="https://oauth2.googleapis.com/token",
        scopes=[
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
        client_id_env="GOOGLE_CLIENT_ID",
        client_secret_env="GOOGLE_CLIENT_SECRET",
        redirect_uri=_redirect("google"),
        use_pkce=True,
        extra_auth_params={"access_type": "offline", "prompt": "consent"},
    ),
    "x": OAuthConfig(
        name="X (Twitter)",
        auth_url="https://twitter.com/i/oauth2/authorize",
        token_url="https://api.twitter.com/2/oauth2/token",
        refresh_url="https://api.twitter.com/2/oauth2/token",
        scopes=["tweet.read", "tweet.write", "users.read", "offline.access"],
        client_id_env="X_CLIENT_ID",
        client_secret_env="X_CLIENT_SECRET",
        redirect_uri=_redirect("x"),
        use_pkce=True,
    ),
    "facebook": OAuthConfig(
        name="Facebook",
        auth_url="https://www.facebook.com/v18.0/dialog/oauth",
        token_url="https://graph.facebook.com/v18.0/oauth/access_token",
        refresh_url="https://graph.facebook.com/v18.0/oauth/access_token",
        scopes=["pages_manage_posts", "pages_read_engagement", "email"],
        client_id_env="FACEBOOK_APP_ID",
        client_secret_env="FACEBOOK_APP_SECRET",
        redirect_uri=_redirect("facebook"),
        use_pkce=False,
    ),
    "discord": OAuthConfig(
        name="Discord",
        auth_url="https://discord.com/oauth2/authorize",
        token_url="https://discord.com/api/v10/oauth2/token",
        refresh_url="https://discord.com/api/v10/oauth2/token",
        scopes=["identify", "email", "bot"],
        client_id_env="DISCORD_CLIENT_ID",
        client_secret_env="DISCORD_CLIENT_SECRET",
        redirect_uri=_redirect("discord"),
        use_pkce=False,
    ),
    "twitch": OAuthConfig(
        name="Twitch",
        auth_url="https://id.twitch.tv/oauth2/authorize",
        token_url="https://id.twitch.tv/oauth2/token",
        refresh_url="https://id.twitch.tv/oauth2/token",
        scopes=["channel:manage:broadcast", "user:read:email"],
        client_id_env="TWITCH_CLIENT_ID",
        client_secret_env="TWITCH_CLIENT_SECRET",
        redirect_uri=_redirect("twitch"),
        use_pkce=True,
    ),
    "tiktok": OAuthConfig(
        name="TikTok",
        auth_url="https://www.tiktok.com/v2/auth/authorize/",
        token_url="https://open.tiktokapis.com/v2/oauth/token/",
        refresh_url="https://open.tiktokapis.com/v2/oauth/token/",
        scopes=["video.upload", "video.list", "user.info.basic"],
        client_id_env="TIKTOK_CLIENT_KEY",
        client_secret_env="TIKTOK_CLIENT_SECRET",
        redirect_uri=_redirect("tiktok"),
        use_pkce=True,
    ),
}


def get_config(platform: str) -> Optional[OAuthConfig]:
    return OAUTH_CONFIGS.get(platform)


def list_platforms() -> list[str]:
    return list(OAUTH_CONFIGS.keys())


def generate_state() -> str:
    """Random CSRF state token."""
    return secrets.token_urlsafe(32)


def generate_code_verifier() -> str:
    """PKCE code verifier."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """PKCE S256 code challenge."""
    import hashlib
    import base64
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")
