"""client.py — minimal Pinterest search client with API + scrape fallback.

Two modes, tried in order:

1. Official API (v5/pins/search) — needs OAuth bearer token. The
   `pintrest_api` value in .env is treated as a bearer token. If the
   first call returns 401, we fall back to scrape mode automatically.

2. Scrape mode — `studio/media/.tools/fetch-url.sh -dir <search-url>`
   already does recursive image fetch from a Pinterest search page. The
   client constructs the search URL and returns the resulting image
   paths from staging.

Both modes return a uniform list[PinResult].
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# Import the auth.keys module to read .env consistently with the rest of
# the studio.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from auth import keys  # noqa: E402
import paths  # noqa: E402

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


PINTEREST_API_BASE = "https://api.pinterest.com/v5"
FETCH_URL_SH = paths.TOOLS_DIR / "fetch-url.sh"


@dataclass
class PinResult:
    pin_id: str
    image_url: str
    title: str
    description: str
    source_url: str            # the pin's own page URL
    tags: list[str]            # best-effort

    def to_dict(self) -> dict:
        return asdict(self)


class PinterestClient:
    """Search Pinterest. Tries the v5 API first; falls back to scraping."""

    def __init__(self, bearer: Optional[str] = None):
        self.bearer = bearer or keys.upstream_key("pinterest")
        self._api_works: Optional[bool] = None   # None=unknown, True/False=cached

    # ------------------------------------------------------------------
    # API mode
    # ------------------------------------------------------------------
    def _api_search(self, query: str, limit: int = 25) -> list[PinResult]:
        if httpx is None:
            raise ImportError("httpx is required for Pinterest API mode")
        if not self.bearer:
            raise RuntimeError("no Pinterest bearer token in .env (pintrest_api)")
        headers = {
            "Authorization": f"Bearer {self.bearer}",
            "Accept": "application/json",
        }
        # /v5/pins/search?query=<>&page_size=<>
        params = {"query": query, "page_size": min(limit, 100)}
        url = f"{PINTEREST_API_BASE}/pins/search"
        with httpx.Client(timeout=30.0) as c:
            r = c.get(url, headers=headers, params=params)
        if r.status_code == 401:
            self._api_works = False
            raise PermissionError("Pinterest API: 401 unauthorized")
        if r.status_code != 200:
            raise RuntimeError(
                f"Pinterest API: HTTP {r.status_code} — {r.text[:200]}"
            )
        self._api_works = True
        data = r.json()
        items = data.get("items") or data.get("data") or []
        out = []
        for it in items:
            media = it.get("media", {}) or {}
            imgs = media.get("images", {}) or {}
            # Pick the largest available image URL.
            url_best = None
            for size in ("1200x", "originals", "600x", "474x"):
                if size in imgs and isinstance(imgs[size], dict):
                    url_best = imgs[size].get("url")
                    if url_best: break
            if not url_best and imgs:
                # Fallback: first image dict we find.
                for v in imgs.values():
                    if isinstance(v, dict) and v.get("url"):
                        url_best = v["url"]; break
            if not url_best:
                continue
            pid = str(it.get("id", ""))
            out.append(PinResult(
                pin_id=pid,
                image_url=url_best,
                title=str(it.get("title") or ""),
                description=str(it.get("description") or it.get("alt_text") or ""),
                source_url=f"https://www.pinterest.com/pin/{pid}/" if pid else "",
                tags=[],
            ))
        return out

    # ------------------------------------------------------------------
    # Scrape mode — uses the existing fetch-url.sh
    # ------------------------------------------------------------------
    def _scrape_search(self, query: str, limit: int = 25,
                       dest_dir: Optional[Path] = None) -> list[PinResult]:
        """Synthesizes a search URL + downloads via fetch-url.sh, then walks
        the staging dir for results."""
        q = urllib.parse.quote_plus(query)
        search_url = f"https://www.pinterest.com/search/pins/?q={q}"
        if not FETCH_URL_SH.exists():
            raise FileNotFoundError(f"fetch-url.sh missing at {FETCH_URL_SH}")
        # Run fetch-url.sh — it dumps images into staging then categorizes.
        try:
            subprocess.run(
                [str(FETCH_URL_SH), "-dir", search_url, "-no-bg"],
                cwd=str(FETCH_URL_SH.parent.parent),  # studio/media/
                check=True, timeout=120,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"fetch-url.sh scrape failed: {e.stderr.decode(errors='ignore')[:200]}"
            )
        # Discover newly-arrived files in staging — best-effort.
        staging = FETCH_URL_SH.parent.parent / ".staging"
        if not staging.exists():
            return []
        out: list[PinResult] = []
        for p in sorted(staging.iterdir(), key=lambda x: -x.stat().st_mtime)[:limit]:
            if not p.is_file():
                continue
            out.append(PinResult(
                pin_id=p.stem,
                image_url=f"file://{p}",
                title=query,
                description=f"scraped from {search_url}",
                source_url=search_url,
                tags=[query],
            ))
        return out

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 25) -> list[PinResult]:
        """Try API first; fall back to scrape on 401 / missing bearer / no httpx."""
        if self._api_works is False:
            return self._scrape_search(query, limit)
        try:
            return self._api_search(query, limit)
        except (PermissionError, ImportError, RuntimeError) as e:
            print(f"[pinterest] API mode failed ({e}); falling back to scrape",
                  file=sys.stderr)
            return self._scrape_search(query, limit)

    def download_pin(self, pin: PinResult, dest_subpath: Optional[str] = None,
                     bg_remove: bool = True) -> dict:
        """Download a single pin via fetch-url.sh. Returns the metadata about
        where it landed. If dest_subpath is given, overrides the auto-classify."""
        if not pin.image_url:
            raise ValueError("pin has no image URL")
        # File:// urls (from scrape mode) are already local — skip download.
        if pin.image_url.startswith("file://"):
            local = Path(pin.image_url[len("file://"):])
            return {"path": str(local), "mode": "local"}
        cmd = [str(FETCH_URL_SH), "-url", pin.image_url]
        if dest_subpath:
            cmd += ["-dest", dest_subpath]
        if not bg_remove:
            cmd += ["-no-bg"]
        r = subprocess.run(
            cmd, cwd=str(FETCH_URL_SH.parent.parent),
            check=True, timeout=180,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        return {"mode": "downloaded", "stdout": r.stdout.decode(errors="ignore")}


# ----------------------------------------------------------------------------
# CLI:  python -m pinterest.client search "red dress" --limit 10
# ----------------------------------------------------------------------------
def _cli():
    import argparse
    ap = argparse.ArgumentParser(prog="pinterest.client")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p_search = sp.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    if args.cmd == "search":
        c = PinterestClient()
        results = c.search(args.query, limit=args.limit)
        print(json.dumps([r.to_dict() for r in results], indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
