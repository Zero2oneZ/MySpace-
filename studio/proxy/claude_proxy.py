"""claude_proxy.py — FastAPI proxy that fronts Anthropic's Messages API.

Friends use Tom's Claude guest pass via salted tokens. They never see the
upstream key.

Flow:
    Friend POSTs to  http://<droplet>:8520/v1/messages
      Headers:  X-Mspc-Token: mspc_claude_<id>_<hmac>
                Content-Type: application/json
      Body:     standard Anthropic Messages request

    Proxy:
      1. verify_token() — reject non-claude / inactive / tampered tokens
      2. Rate-limit (60 req / 60 sec / token, in-memory bucket)
      3. Forward to https://api.anthropic.com/v1/messages with the real
         claude_guest from .env
      4. Read upstream `usage.input_tokens` / `usage.output_tokens` and
         log_usage(...)
      5. Stream the upstream response back (preserves status code +
         headers minus the auth ones)

Run:
    python -m uvicorn studio.proxy.claude_proxy:app \\
      --host 0.0.0.0 --port 8520

…or via `cc -proxy-start`.

Endpoints exposed:
    GET  /health            → simple liveness + counts
    POST /v1/messages       → proxied to Anthropic
    POST /v1/messages/count_tokens → proxied (for token counting)
    GET  /me                → echo the caller's TokenRow (for debugging)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from collections import defaultdict, deque
from typing import Optional

# Make sibling modules importable when run via uvicorn from a different cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth import keys  # noqa: E402

# Lazy import so static checks pass even without fastapi/httpx installed.
try:
    import httpx
    from fastapi import FastAPI, Request, HTTPException, Header
    from fastapi.responses import JSONResponse, Response
except ImportError as e:  # pragma: no cover
    httpx = None  # type: ignore
    FastAPI = None  # type: ignore
    raise ImportError(
        "claude_proxy needs fastapi + httpx + uvicorn — install with:\n"
        "    pip install fastapi httpx uvicorn[standard]"
    ) from e


UPSTREAM_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = os.environ.get("CLAUDE_ANTHROPIC_VERSION", "2023-06-01")
RATE_LIMIT_PER_MIN = int(os.environ.get("MYSPACE_RATE_LIMIT", "60"))
MAX_ACTIVE_TOKENS = int(os.environ.get("MYSPACE_MAX_CLAUDE_TOKENS", "2"))


# ----------------------------------------------------------------------------
# Rate limiting (in-memory; resets on proxy restart)
# ----------------------------------------------------------------------------
_buckets: dict[str, deque] = defaultdict(deque)

def _rate_limit(token_id: str) -> bool:
    """Return True iff allowed. 60s sliding window."""
    now = time.time()
    bk = _buckets[token_id]
    while bk and bk[0] < now - 60:
        bk.popleft()
    if len(bk) >= RATE_LIMIT_PER_MIN:
        return False
    bk.append(now)
    return True


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
app = FastAPI(title="MySpace++ Claude Guest-Pass Proxy",
              description="Tom's Claude guest key, brokered to friends via "
                          "salted tokens. Usage logged + rate limited.")


@app.get("/health")
def health():
    s = keys.status_summary()
    return {
        "ok": True,
        "tokens_active": s["tokens_active"],
        "tokens_total":  s["tokens_total"],
        "calls_today":   s["calls_today"],
        "cost_today":    round(s["cost_today"], 4),
        "rate_limit":    f"{RATE_LIMIT_PER_MIN}/min/token",
        "upstream":      UPSTREAM_URL,
    }


def _require_token(x_mspc_token: Optional[str]) -> keys.TokenRow:
    if not x_mspc_token:
        raise HTTPException(401, "missing X-Mspc-Token header")
    row = keys.verify_token(x_mspc_token)
    if row is None:
        raise HTTPException(401, "invalid or revoked token")
    if row.kind != "claude":
        raise HTTPException(403, f"token is for kind={row.kind}, not claude")
    if not _rate_limit(row.token_id):
        raise HTTPException(429, f"rate limit ({RATE_LIMIT_PER_MIN}/min) exceeded")
    return row


@app.get("/me")
def me(x_mspc_token: Optional[str] = Header(default=None, alias="X-Mspc-Token")):
    row = _require_token(x_mspc_token)
    return row.__dict__


@app.post("/v1/messages")
async def messages(
    request: Request,
    x_mspc_token: Optional[str] = Header(default=None, alias="X-Mspc-Token"),
):
    row = _require_token(x_mspc_token)
    upstream_key = keys.upstream_key("claude")
    if not upstream_key:
        raise HTTPException(500, "claude_guest not set in .env")

    body = await request.body()
    headers = {
        "x-api-key": upstream_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": request.headers.get("content-type", "application/json"),
    }

    # Forward
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{UPSTREAM_URL}/v1/messages",
                headers=headers, content=body,
            )
    except httpx.HTTPError as e:
        keys.log_usage(row.token_id, 0, 0, endpoint="/v1/messages", status=502)
        raise HTTPException(502, f"upstream error: {e}")

    # Parse upstream's usage block (if 2xx)
    tokens_in = tokens_out = 0
    if r.status_code == 200:
        try:
            data = r.json()
            usage = data.get("usage", {}) or {}
            tokens_in  = int(usage.get("input_tokens", 0))
            tokens_out = int(usage.get("output_tokens", 0))
        except (json.JSONDecodeError, ValueError):
            pass

    cost = keys.log_usage(
        row.token_id, tokens_in, tokens_out,
        endpoint="/v1/messages", status=r.status_code,
    )

    # Mirror status + body. Don't leak upstream auth headers downstream.
    out_headers = {
        "x-mspc-tokens-in":  str(tokens_in),
        "x-mspc-tokens-out": str(tokens_out),
        "x-mspc-cost-usd":   f"{cost:.6f}",
        "content-type":      r.headers.get("content-type", "application/json"),
    }
    return Response(content=r.content, status_code=r.status_code, headers=out_headers)


@app.post("/v1/messages/count_tokens")
async def count_tokens(
    request: Request,
    x_mspc_token: Optional[str] = Header(default=None, alias="X-Mspc-Token"),
):
    row = _require_token(x_mspc_token)
    upstream_key = keys.upstream_key("claude")
    if not upstream_key:
        raise HTTPException(500, "claude_guest not set in .env")
    body = await request.body()
    headers = {
        "x-api-key": upstream_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": request.headers.get("content-type", "application/json"),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{UPSTREAM_URL}/v1/messages/count_tokens",
            headers=headers, content=body,
        )
    keys.log_usage(row.token_id, 0, 0,
                   endpoint="/v1/messages/count_tokens", status=r.status_code)
    return Response(content=r.content, status_code=r.status_code,
                    headers={"content-type": r.headers.get("content-type",
                                                            "application/json")})


# ----------------------------------------------------------------------------
# Cap distribution to MAX_ACTIVE_TOKENS so Tom can't accidentally hand out
# more guest passes than he meant to.
# ----------------------------------------------------------------------------
def assert_distribute_within_cap(user: str) -> None:
    """Raise RuntimeError if Tom is about to issue more than MAX_ACTIVE_TOKENS
    distinct active claude tokens. Call this from `cc -keys-distribute` BEFORE
    calling keys.distribute_token().
    """
    active = [t for t in keys.list_tokens(include_inactive=False)
              if t.kind == "claude"]
    if len(active) >= MAX_ACTIVE_TOKENS:
        raise RuntimeError(
            f"Already {len(active)} active claude tokens — cap is "
            f"{MAX_ACTIVE_TOKENS}. Revoke one first: "
            f"`cc -keys-revoke <token-id>`. "
            f"(Cap configurable via $MYSPACE_MAX_CLAUDE_TOKENS.)"
        )


if __name__ == "__main__":
    # Direct run convenience; prefer `cc -proxy-start` or uvicorn explicitly.
    import uvicorn
    uvicorn.run("studio.proxy.claude_proxy:app",
                host="0.0.0.0", port=int(os.environ.get("PORT", 8520)),
                reload=False)
