"""_http.py — minimal HTTP client wrapper.

Prefers httpx, then requests, then urllib (stdlib) for zero-dependency operation.
All social uploaders import from here instead of importing httpx/requests directly.
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from pathlib import Path
from typing import Optional

try:
    import httpx as _httpx  # type: ignore
    _HAS_HTTPX = True
except ImportError:
    _httpx = None  # type: ignore
    _HAS_HTTPX = False

try:
    import requests as _requests  # type: ignore
    _HAS_REQUESTS = True
except ImportError:
    _requests = None  # type: ignore
    _HAS_REQUESTS = False


class Response:
    """Unified response object."""

    def __init__(self, status_code: int, text: str, headers: dict):
        self.status_code = status_code
        self.text = text
        self.headers = headers

    def json(self) -> dict:
        return json.loads(self.text) if self.text else {}


def post(
    url: str,
    *,
    headers: Optional[dict] = None,
    data: Optional[bytes] = None,
    content: Optional[bytes] = None,
    files: Optional[dict] = None,
    timeout: float = 30,
) -> Response:
    """POST to url. Returns Response."""
    payload = data or content
    hdrs = headers or {}

    if _HAS_REQUESTS and files:
        # requests handles multipart natively
        r = _requests.post(url, headers=hdrs, data=files if isinstance(files, dict) else None, files=files, timeout=timeout)
        return Response(r.status_code, r.text, dict(r.headers))

    if _HAS_HTTPX and files is None:
        with _httpx.Client(timeout=timeout) as c:
            r = c.post(url, headers=hdrs, content=payload)
        return Response(r.status_code, r.text, dict(r.headers))

    if _HAS_REQUESTS:
        r = _requests.post(url, headers=hdrs, data=payload, timeout=timeout)
        return Response(r.status_code, r.text, dict(r.headers))

    # urllib fallback — no multipart file upload, but fine for JSON/bytes POSTs
    req = urllib.request.Request(url, data=payload, headers=hdrs, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return Response(resp.status, body, dict(resp.headers))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.read else ""
        return Response(e.code, body, dict(e.headers))


def put(
    url: str,
    *,
    headers: Optional[dict] = None,
    data: Optional[bytes] = None,
    content: Optional[bytes] = None,
    timeout: float = 30,
) -> Response:
    """PUT to url. Returns Response."""
    payload = data or content
    hdrs = headers or {}

    if _HAS_HTTPX:
        with _httpx.Client(timeout=timeout) as c:
            r = c.put(url, headers=hdrs, content=payload)
        return Response(r.status_code, r.text, dict(r.headers))

    if _HAS_REQUESTS:
        r = _requests.put(url, headers=hdrs, data=payload, timeout=timeout)
        return Response(r.status_code, r.text, dict(r.headers))

    req = urllib.request.Request(url, data=payload, headers=hdrs, method="PUT")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return Response(resp.status, body, dict(resp.headers))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.read else ""
        return Response(e.code, body, dict(e.headers))


def get(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: float = 30,
) -> Response:
    """GET url. Returns Response."""
    hdrs = headers or {}

    if _HAS_HTTPX:
        with _httpx.Client(timeout=timeout) as c:
            r = c.get(url, headers=hdrs)
        return Response(r.status_code, r.text, dict(r.headers))

    if _HAS_REQUESTS:
        r = _requests.get(url, headers=hdrs, timeout=timeout)
        return Response(r.status_code, r.text, dict(r.headers))

    req = urllib.request.Request(url, headers=hdrs, method="GET")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return Response(resp.status, body, dict(resp.headers))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.read else ""
        return Response(e.code, body, dict(e.headers))


def delete(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: float = 30,
) -> Response:
    """DELETE url. Returns Response."""
    hdrs = headers or {}

    if _HAS_HTTPX:
        with _httpx.Client(timeout=timeout) as c:
            r = c.delete(url, headers=hdrs)
        return Response(r.status_code, r.text, dict(r.headers))

    if _HAS_REQUESTS:
        r = _requests.delete(url, headers=hdrs, timeout=timeout)
        return Response(r.status_code, r.text, dict(r.headers))

    req = urllib.request.Request(url, headers=hdrs, method="DELETE")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return Response(resp.status, body, dict(resp.headers))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.read else ""
        return Response(e.code, body, dict(e.headers))
