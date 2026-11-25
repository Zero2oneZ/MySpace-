#!/usr/bin/env python3
"""x-cli.py — X (Twitter) API v2 CLI for MySpace++.

Uses keys from .env ( OAuth 1.0a for writes, Bearer for reads ):
    X_CONSUMER_KEY=...
    X_CONSUMER_SECRET_KEY=...
    X_ACCESS_TOKEN=...
    X_ACCESS_SECRET_TOKEN=...
    X_BEARER_TOKEN=...          # optional, for read-only calls
    X_CLIENT_ID=...             # OAuth 2.0 app-only (alternative)
    X_CLIENT_SECRET=...

Commands:
    me                              — show authenticated user info
    tweet <text> [file]             — post a tweet, optionally with media
    media <file>                   — upload media, return media_id
    delete <tweet_id>              — delete a tweet
    timeline [count]                — fetch home timeline
    search <query> [count]          — search recent tweets
    user <handle>                   — show user profile
    tweets <handle> [count]          — list user's recent tweets

Endpoints:
    Write: https://api.twitter.com/2/            (OAuth 1.0a)
    Media: https://upload.twitter.com/1.1/       (OAuth 1.0a, chunked for video)
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request
import ssl
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from _env import key  # noqa: E402
from _http import get as _http_get, post as _http_post  # noqa: E402

# ── OAuth 1.0a helpers (no external lib needed for simple signing) ────────

API_V2 = "https://api.twitter.com/2"
UPLOAD_V1 = "https://upload.twitter.com/1.1/media/upload.json"


def _oauth1_sign(method: str, url: str, params: dict, consumer_secret: str, token_secret: str) -> str:
    """Return the OAuth 1.0a signature base string + signing key."""
    import hmac, hashlib, random, time
    nonce = "".join(random.choices("0123456789abcdef", k=32))
    ts = str(int(time.time()))
    base_params = {
        "oauth_consumer_key": key("X_CONSUMER_KEY", ""),
        "oauth_token": key("X_ACCESS_TOKEN", ""),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": ts,
        "oauth_nonce": nonce,
        "oauth_version": "1.0",
    }
    base_params.update(params)
    sorted_params = sorted((k, urllib.parse.quote(str(v), safe="")) for k, v in base_params.items())
    param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
    base_str = f"{method.upper()}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(param_str, safe='')}"
    signing_key = f"{urllib.parse.quote(consumer_secret)}&{urllib.parse.quote(token_secret)}"
    sig = base64.b64encode(hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha1).digest()).decode()
    base_params["oauth_signature"] = sig
    auth_parts = sorted((k, v) for k, v in base_params.items() if k.startswith("oauth_"))
    auth_header = ", ".join(f'{k}="{urllib.parse.quote(str(v))}"' for k, v in auth_parts)
    return f"OAuth {auth_header}"


def _auth_headers(method: str, url: str, extra_params: dict | None = None) -> dict:
    consumer_key = key("X_CONSUMER_KEY", "")
    consumer_secret = key("X_CONSUMER_SECRET_KEY", "")
    token = key("X_ACCESS_TOKEN", "")
    token_secret = key("X_ACCESS_SECRET_TOKEN", "")
    if not all([consumer_key, consumer_secret, token, token_secret]):
        print("Error: X OAuth 1.0a keys missing. Need X_CONSUMER_KEY, X_CONSUMER_SECRET_KEY, X_ACCESS_TOKEN, X_ACCESS_SECRET_TOKEN", file=sys.stderr)
        sys.exit(1)
    auth = _oauth1_sign(method, url, extra_params or {}, consumer_secret, token_secret)
    return {"Authorization": auth}


def _bearer_headers() -> dict:
    tok = key("X_BEARER_TOKEN", "")
    if not tok:
        # Try OAuth 2.0 app-only token
        client_id = key("X_CLIENT_ID", "")
        client_secret = key("X_CLIENT_SECRET", "")
        if client_id and client_secret:
            tok = _get_app_only_token(client_id, client_secret)
        if not tok:
            print("Error: X_BEARER_TOKEN not set and no client_id/client_secret", file=sys.stderr)
            sys.exit(1)
    return {"Authorization": f"Bearer {tok}"}


def _get_app_only_token(client_id: str, client_secret: str) -> str:
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        "https://api.twitter.com/oauth2/token",
        data=b"grant_type=client_credentials",
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        body = json.loads(resp.read().decode())
        return body.get("access_token", "")


# ── Commands ────────────────────────────────────────────────────────────────

def cmd_me() -> None:
    r = _http_get(f"{API_V2}/users/me", headers=_auth_headers("GET", f"{API_V2}/users/me"), timeout=15)
    print(json.dumps(r.json() if r.text else {}, indent=2))


def cmd_tweet(text: str, media_id: str = "") -> None:
    url = f"{API_V2}/tweets"
    payload: dict = {"text": text}
    if media_id:
        payload["media"] = {"media_ids": [media_id]}
    headers = _auth_headers("POST", url)
    headers["Content-Type"] = "application/json"
    r = _http_post(url, headers=headers, content=json.dumps(payload).encode(), timeout=15)
    body = r.json() if r.text else {}
    data = body.get("data", {})
    if "id" in data:
        print(f"Tweeted id={data['id']}")
    else:
        print(f"Error: {body}", file=sys.stderr)


def cmd_media(file_path: str) -> None:
    p = Path(file_path)
    if not p.exists():
        print(f"File not found: {p}", file=sys.stderr)
        sys.exit(1)

    # Use urllib directly for multipart upload to upload.twitter.com
    consumer_key = key("X_CONSUMER_KEY", "")
    consumer_secret = key("X_CONSUMER_SECRET_KEY", "")
    token = key("X_ACCESS_TOKEN", "")
    token_secret = key("X_ACCESS_SECRET_TOKEN", "")
    if not all([consumer_key, consumer_secret, token, token_secret]):
        print("Error: X OAuth 1.0a keys missing", file=sys.stderr)
        sys.exit(1)

    boundary = "----XMediaBoundary"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="{p.name}"\r\n'
        f'Content-Type: application/octet-stream\r\n\r\n'
    ]
    body = b"".join(part.encode() for part in parts) + p.read_bytes() + f"\r\n--{boundary}--\r\n".encode()

    auth = _oauth1_sign("POST", UPLOAD_V1, {}, consumer_secret, token_secret)
    req = urllib.request.Request(
        UPLOAD_V1,
        data=body,
        headers={
            "Authorization": auth,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            result = json.loads(resp.read().decode())
            mid = result.get("media_id_string")
            if mid:
                print(f"media_id={mid}")
            else:
                print(f"Error: {result}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:400]}", file=sys.stderr)


def cmd_delete(tweet_id: str) -> None:
    url = f"{API_V2}/tweets/{tweet_id}"
    headers = _auth_headers("DELETE", url)
    # _http doesn't expose DELETE; use urllib
    import urllib.request
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            print(f"Deleted {tweet_id} (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        print(f"Error HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)


def cmd_timeline(count: int = 10) -> None:
    # Home timeline: use /2/users/{id}/timelines/reverse_chronological
    # First get me to know user_id
    me_r = _http_get(f"{API_V2}/users/me", headers=_auth_headers("GET", f"{API_V2}/users/me"), timeout=15)
    me = me_r.json() if me_r.text else {}
    user_id = me.get("data", {}).get("id")
    if not user_id:
        print("Could not get user id", file=sys.stderr)
        sys.exit(1)
    url = f"{API_V2}/users/{user_id}/timelines/reverse_chronological?max_results={min(count, 100)}"
    r = _http_get(url, headers=_bearer_headers(), timeout=15)
    body = r.json() if r.text else {}
    for t in body.get("data", []):
        print(f"{t.get('id')}: {t.get('text', '')[:100]}")


def cmd_search(query: str, count: int = 10) -> None:
    q = urllib.parse.quote(query)
    url = f"{API_V2}/tweets/search/recent?query={q}&max_results={min(count, 100)}"
    r = _http_get(url, headers=_bearer_headers(), timeout=15)
    body = r.json() if r.text else {}
    for t in body.get("data", []):
        print(f"{t.get('id')}: {t.get('text', '')[:100]}")


def cmd_user(handle: str) -> None:
    h = handle.lstrip("@")
    url = f"{API_V2}/users/by/username/{h}?user.fields=description,public_metrics,created_at"
    r = _http_get(url, headers=_bearer_headers(), timeout=15)
    print(json.dumps(r.json() if r.text else {}, indent=2))


def cmd_tweets(handle: str, count: int = 10) -> None:
    h = handle.lstrip("@")
    # Resolve user id
    url = f"{API_V2}/users/by/username/{h}"
    r = _http_get(url, headers=_bearer_headers(), timeout=15)
    body = r.json() if r.text else {}
    uid = body.get("data", {}).get("id")
    if not uid:
        print(f"User not found: {h}", file=sys.stderr)
        sys.exit(1)
    url2 = f"{API_V2}/users/{uid}/tweets?max_results={min(count, 100)}"
    r2 = _http_get(url2, headers=_bearer_headers(), timeout=15)
    body2 = r2.json() if r2.text else {}
    for t in body2.get("data", []):
        print(f"{t.get('id')}: {t.get('text', '')[:120]}")


def _usage() -> None:
    print("Usage: x-cli.py <command> [args...]")
    print("  me")
    print("  tweet <text> [file]")
    print("  media <file>                  — upload media, print media_id")
    print("  delete <tweet_id>")
    print("  timeline [count]")
    print("  search <query> [count]")
    print("  user <handle>")
    print("  tweets <handle> [count]")
    sys.exit(2)


def main() -> None:
    if len(sys.argv) < 2:
        _usage()
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "me":
        cmd_me()
    elif cmd == "tweet":
        if not args:
            _usage()
        text = args[0]
        media_file = args[1] if len(args) > 1 else ""
        media_id = ""
        if media_file:
            # Upload media first and capture media_id
            import io, subprocess
            p = subprocess.run(
                [sys.executable, str(Path(__file__)), "media", media_file],
                capture_output=True, text=True,
            )
            out = p.stdout.strip()
            if out.startswith("media_id="):
                media_id = out.split("=", 1)[1]
            else:
                print(f"Media upload failed: {out} {p.stderr}", file=sys.stderr)
                sys.exit(1)
        cmd_tweet(text, media_id)
    elif cmd == "media":
        if not args:
            _usage()
        cmd_media(args[0])
    elif cmd == "delete":
        if not args:
            _usage()
        cmd_delete(args[0])
    elif cmd == "timeline":
        cmd_timeline(int(args[0]) if args else 10)
    elif cmd == "search":
        if not args:
            _usage()
        cmd_search(args[0], int(args[1]) if len(args) > 1 else 10)
    elif cmd == "user":
        if not args:
            _usage()
        cmd_user(args[0])
    elif cmd == "tweets":
        if not args:
            _usage()
        cmd_tweets(args[0], int(args[1]) if len(args) > 1 else 10)
    else:
        _usage()


if __name__ == "__main__":
    main()
