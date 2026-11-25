#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        noun_project
# role:        CONNECTOR · NOUN_PROJECT_FREE_TRAINING_DATA
# tier:        L0
# substrate:   curated icon harvest — every icon is FREE labeled training data
# storage:     studio/assets/_corpus/icons/<crystal_short>.{svg,json}
#              ~/.cc/third_party_logs/noun_project_sends.jsonl
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.noun_project.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio_runtime (when pass.provider_family='noun_project')
#   - workflow_card noun_project_icon_harvest (planned)
#   - direct CLI: python3 third_party_cli.py send --service noun_project ...
# outbound:
#   - https://api.thenounproject.com/v2/* via stdlib urllib (OAuth1 two-legged)
#   - inference_logger.log (tier='noun_project_import', model='noun_project')
# substrate touch:
#   - reads:  NOUNPROJECT_API_KEY + NOUNPROJECT_SECRET_KEY from .env
#   - writes: studio/assets/_corpus/icons/ + send_log + crystal-chain records
# ============================================================================
"""noun_project.py — Noun Project REST connector + curated icon harvester.

The Noun Project exposes an OAuth1-two-legged JSON API at
https://api.thenounproject.com/v2/ . Every icon comes with a curated text
label (`term`), a tag list, a license, and creator credits — so every icon
harvested is a free labeled training example for icon-recognition / icon-
generation / text-to-vector models.

Tools (via send(recipient=tool_name, message=json_args)):
  - search(query, limit=10)              → /v2/icon/search
  - harvest_query(query, limit=10)       → search + download SVG + sidecar JSON
  - get_icon(noun_id)                    → /v2/icon/<id>
  - list_terms_for_collection(coll_id)   → /v2/collection/<id>/icons

Auth: OAuth1 (consumer_key + consumer_secret), two-legged — no user context.
Implemented inline with stdlib hmac / hashlib / base64 / urllib (no
`requests_oauthlib` dep).

Graceful absent-keys mode: if NOUNPROJECT_API_KEY or NOUNPROJECT_SECRET_KEY
is missing from .env, connect() returns False and every send() returns a
SendResult(success=False, error='noun_project keys not configured'). No crash.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent     # /data/Projects/MySpace++/
_STUDIO_ROOT = _PROJECT_ROOT / "studio"
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))
sys.path.insert(0, str(_STUDIO_ROOT))

from base import ThirdPartyConnector, ConnectionConfig, SendResult  # type: ignore  # noqa: E402

NOUN_API_ROOT = "https://api.thenounproject.com"
ICON_CORPUS_DIR = _STUDIO_ROOT / "assets" / "_corpus" / "icons"
EXPECTED_TOOLS = (
    "search",
    "harvest_query",
    "get_icon",
    "list_terms_for_collection",
)


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------

def _load_consumer_keys() -> Tuple[str, str]:
    """Resolve NOUNPROJECT_API_KEY + NOUNPROJECT_SECRET_KEY from .env / env.
    Returns (key, secret) — either may be empty string if not configured."""
    key = ""
    secret = ""
    # Prefer studio/auth/keys.load_env (matches stripe pattern).
    try:
        from auth.keys import load_env  # type: ignore
        env = load_env()
        key = env.get("NOUNPROJECT_API_KEY", "") or env.get("NOUN_PROJECT_KEY", "")
        secret = env.get("NOUNPROJECT_SECRET_KEY", "") or env.get("NOUN_PROJECT_SECRET", "")
    except Exception:
        pass
    if not key:
        key = os.environ.get("NOUNPROJECT_API_KEY", "") or os.environ.get("NOUN_PROJECT_KEY", "")
    if not secret:
        secret = os.environ.get("NOUNPROJECT_SECRET_KEY", "") or os.environ.get("NOUN_PROJECT_SECRET", "")
    return key, secret


# ---------------------------------------------------------------------------
# OAuth1 two-legged signing (RFC 5849 §3.4.1) — ~50 LOC, stdlib only.
#
# sig_base = METHOD + "&" + percent_encode(base_url) +
#            "&" + percent_encode(canonical_params)
# signing_key = percent_encode(consumer_secret) + "&"   # empty token secret
# signature   = base64(HMAC-SHA1(signing_key, sig_base))
# Authorization header carries oauth_consumer_key, oauth_nonce, oauth_signature,
# oauth_signature_method=HMAC-SHA1, oauth_timestamp, oauth_version=1.0.
# ---------------------------------------------------------------------------

def _percent_encode(s: str) -> str:
    # RFC 3986 unreserved: A-Z a-z 0-9 - . _ ~  → urllib.parse.quote with safe=""
    return urllib.parse.quote(str(s), safe="-._~")


def _oauth1_header(method: str, url: str, params: Dict[str, str],
                     consumer_key: str, consumer_secret: str) -> str:
    """Build the OAuth1 Authorization header for a two-legged request.

    `params` should be the query-string params for GET (already split from URL).
    For two-legged the token + token_secret are empty.
    """
    oauth_params = {
        "oauth_consumer_key":     consumer_key,
        "oauth_nonce":            hashlib.sha1(os.urandom(16)).hexdigest(),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_version":          "1.0",
    }
    # Canonical params = oauth_* + query params, sorted by encoded key then value.
    canonical = []
    for k, v in {**oauth_params, **(params or {})}.items():
        canonical.append((_percent_encode(k), _percent_encode(v)))
    canonical.sort()
    canonical_str = "&".join(f"{k}={v}" for k, v in canonical)

    sig_base = "&".join([
        method.upper(),
        _percent_encode(url),
        _percent_encode(canonical_str),
    ])
    signing_key = _percent_encode(consumer_secret) + "&"   # empty token secret
    raw_sig = hmac.new(signing_key.encode("utf-8"),
                        sig_base.encode("utf-8"), hashlib.sha1).digest()
    oauth_params["oauth_signature"] = base64.b64encode(raw_sig).decode("ascii")

    header_parts = [f'{_percent_encode(k)}="{_percent_encode(v)}"'
                     for k, v in sorted(oauth_params.items())]
    return "OAuth " + ", ".join(header_parts)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_get(url: str, headers: Dict[str, str], timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(txt)
            except json.JSONDecodeError:
                return resp.status, {"_raw": txt[:8192]}
    except urllib.error.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
            return e.code, (json.loads(body_txt)
                              if body_txt.strip().startswith("{")
                              else {"_error": body_txt[:2048]})
        except Exception:
            return e.code, {"_error": str(e)}
    except Exception as e:
        return 0, {"_error": f"{type(e).__name__}: {e}"}


def _http_get_bytes(url: str, headers: Optional[Dict[str, str]] = None,
                     timeout: int = 30) -> Tuple[int, bytes]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


# ---------------------------------------------------------------------------
# Geometry crystal — try svg_vector_embed.compute_geometry_crystal, else sha256
# ---------------------------------------------------------------------------

def _svg_crystal(svg_bytes: bytes) -> str:
    """Stable hash of an SVG. Prefers svg_vector_embed.compute_geometry_crystal
    (shape-invariant). Falls back to plain SHA-256 of bytes if unavailable."""
    try:
        from svg_vector_embed import compute_geometry_crystal  # type: ignore
        return compute_geometry_crystal(svg_bytes)  # type: ignore[arg-type]
    except Exception:
        return hashlib.sha256(svg_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Crystal-chain logging
# ---------------------------------------------------------------------------

def _log_import(tool: str, params: Dict[str, Any], result: Dict[str, Any],
                  latency_ms: int, status_code: int) -> str:
    """Append one InferenceRecord with tier='noun_project_import'.
    Returns the crystal_id (or '' if logger unavailable)."""
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        crystal_id = il.log(
            original_prompt=f"noun_project.{tool}",
            enhanced_prompt=json.dumps(params, separators=(",", ":"))[:512],
            output_text=json.dumps({k: v for k, v in result.items()
                                     if k in ("id", "term", "license_description",
                                              "creator", "preview_url", "thumbnail_url")},
                                    separators=(",", ":"))[:512],
            tier="noun_project_import",
            model="noun_project",
            scope=f"noun_project_{tool}",
            tokens_in=0, tokens_out=0, latency_ms=latency_ms,
            source_action=f"noun_project.{tool}",
            done_flag=(200 <= status_code < 300),
            rc=0 if 200 <= status_code < 300 else 1,
        )
        return crystal_id or ""
    except Exception as e:
        sys.stderr.write(f"warn: noun_project crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Connector class
# ---------------------------------------------------------------------------

class NounProjectConnector(ThirdPartyConnector):
    """Noun Project REST connector — OAuth1 two-legged, stdlib only."""

    SERVICE = "noun_project"

    def __init__(self, config: Optional[ConnectionConfig] = None):
        if config is None:
            config = ConnectionConfig(service=self.SERVICE,
                                       name="noun_project_default",
                                       action="icon_harvest")
        super().__init__(config)
        self._consumer_key: str = ""
        self._consumer_secret: str = ""
        self._connected = False

    # ---- lifecycle ------------------------------------------------------

    def connect(self) -> bool:
        """Validate that consumer key + secret are present. We do NOT smoke-
        ping the API on connect — Noun Project's free tier has a tight rate
        limit and the smoke would burn one of our requests."""
        self._consumer_key, self._consumer_secret = _load_consumer_keys()
        self._connected = bool(self._consumer_key and self._consumer_secret)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    # ---- main op --------------------------------------------------------

    def send(self, recipient: str, message: str = "", **kwargs) -> SendResult:
        """recipient = tool name; message = JSON args (preferred) or empty.

        For tool=search, recipient='search' and message='{"query":...}'.
        """
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Lazy connect — populates _consumer_key/secret even if no explicit connect().
        if not self._connected and not self.connect():
            res = SendResult(
                success=False,
                crystal_id="noun_project_no_keys",
                service=self.SERVICE,
                recipient=recipient,
                message_preview="",
                timestamp=ts,
                error="noun_project keys not configured",
                metadata={"hint": "set NOUNPROJECT_API_KEY + NOUNPROJECT_SECRET_KEY in .env"},
            )
            self._log_send(res)
            return res

        params: Dict[str, Any] = {}
        if message:
            try:
                params = json.loads(message)
            except json.JSONDecodeError:
                params = {"message": message}
        params.update(kwargs)

        t0 = time.time()
        if recipient == "search":
            status, body = self._search(params)
        elif recipient == "harvest_query":
            status, body = self._harvest_query(params)
        elif recipient == "get_icon":
            status, body = self._get_icon(params)
        elif recipient == "list_terms_for_collection":
            status, body = self._list_collection(params)
        else:
            res = SendResult(
                success=False,
                crystal_id="noun_project_unknown_tool",
                service=self.SERVICE,
                recipient=recipient,
                message_preview="",
                timestamp=ts,
                error=f"unknown_tool:{recipient}",
                metadata={"expected_tools": list(EXPECTED_TOOLS)},
            )
            self._log_send(res)
            return res

        latency_ms = int((time.time() - t0) * 1000)
        crystal_id = _log_import(recipient, params, body, latency_ms, status)
        success = (200 <= status < 300)

        if isinstance(body, dict):
            preview_id = body.get("id") or body.get("count") or ""
            preview = f"{recipient} ok id={preview_id}" if success else f"{recipient} fail"
            err = "" if success else (body.get("_error", "") or f"http_{status}")
        else:
            preview = f"{recipient} ok ({len(body) if hasattr(body, '__len__') else '?'})"
            err = "" if success else f"http_{status}"

        meta: Dict[str, Any] = {
            "status_code": status,
            "latency_ms": latency_ms,
            "tool": recipient,
        }
        if isinstance(body, dict):
            # Pass through useful fields without dumping the whole body.
            for k in ("id", "term", "license_description", "preview_url",
                       "thumbnail_url", "icon_url", "saved_svg",
                       "saved_sidecar", "saved_crystal", "harvested",
                       "skipped", "icons_meta"):
                if k in body:
                    meta[k] = body[k]

        res = SendResult(
            success=success,
            crystal_id=crystal_id or f"noun_project_{recipient}_{int(t0)}",
            service=self.SERVICE,
            recipient=recipient,
            message_preview=preview[:200],
            timestamp=ts,
            error=err,
            metadata=meta,
        )
        self._log_send(res)
        return res

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        log_path = Path.home() / ".cc" / "third_party_logs" / "noun_project_sends.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [json.loads(ln) for ln in lines if ln.strip()]
        except Exception:
            return []

    # ---- HTTP convenience -----------------------------------------------

    def _signed_get(self, path: str, query: Optional[Dict[str, Any]] = None,
                      timeout: int = 30) -> Tuple[int, Dict[str, Any]]:
        """Build a signed OAuth1 GET against the v2 API."""
        query = {k: str(v) for k, v in (query or {}).items() if v is not None}
        base_url = f"{NOUN_API_ROOT}{path}"
        auth_header = _oauth1_header("GET", base_url, query,
                                       self._consumer_key, self._consumer_secret)
        qs = urllib.parse.urlencode(query) if query else ""
        full_url = base_url + (f"?{qs}" if qs else "")
        return _http_get(full_url, {"Authorization": auth_header}, timeout=timeout)

    # ---- Tool implementations -------------------------------------------

    def _search(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        query = str(p.get("query", "")).strip()
        if not query:
            return 400, {"_error": "missing query"}
        limit = int(p.get("limit", 10))
        # Noun Project v2 search endpoint is GET /v2/icon?query=...
        # (the older docs sometimes show /v2/icon/search; the canonical v2
        # form is /v2/icon with query param).
        return self._signed_get("/v2/icon",
                                  {"query": query, "limit": limit})

    def _get_icon(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        noun_id = str(p.get("noun_id", "") or p.get("id", "")).strip()
        if not noun_id:
            return 400, {"_error": "missing noun_id"}
        return self._signed_get(f"/v2/icon/{noun_id}")

    def _list_collection(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        coll_id = str(p.get("collection_id", "") or p.get("id", "")).strip()
        if not coll_id:
            return 400, {"_error": "missing collection_id"}
        limit = int(p.get("limit", 50))
        return self._signed_get(f"/v2/collection/{coll_id}/icons",
                                  {"limit": limit})

    def _harvest_query(self, p: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """search → download each SVG to icons/<crystal>.svg + sidecar JSON.

        Each downloaded icon emits its own InferenceRecord via _log_import
        (called once per icon below).
        Returns aggregate dict with `harvested` (list) + `skipped` (list)."""
        query = str(p.get("query", "")).strip()
        if not query:
            return 400, {"_error": "missing query"}
        limit = int(p.get("limit", 10))

        ICON_CORPUS_DIR.mkdir(parents=True, exist_ok=True)

        status, body = self._search({"query": query, "limit": limit})
        if not (200 <= status < 300) or not isinstance(body, dict):
            return status, body

        # v2 returns {'icons': [...], 'next_page': ...} typically; be defensive.
        icons = body.get("icons") or body.get("data") or []
        if not isinstance(icons, list):
            icons = []

        harvested: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        icons_meta: List[Dict[str, Any]] = []

        for icon in icons:
            try:
                meta = self._download_icon(icon, query=query)
                if meta.get("ok"):
                    harvested.append(meta)
                else:
                    skipped.append(meta)
                icons_meta.append({
                    "noun_id": meta.get("noun_id"),
                    "term": meta.get("noun_term"),
                    "crystal_short": meta.get("crystal_short"),
                    "saved_svg": meta.get("saved_svg"),
                    "ok": meta.get("ok", False),
                })
            except Exception as e:
                skipped.append({"ok": False, "error": f"{type(e).__name__}: {e}",
                                  "noun_id": icon.get("id") if isinstance(icon, dict) else ""})

        return 200, {
            "query": query,
            "icons_returned": len(icons),
            "harvested": [m for m in harvested if isinstance(m, dict)],
            "skipped": skipped,
            "icons_meta": icons_meta,
            "corpus_dir": str(ICON_CORPUS_DIR),
        }

    # ---- icon download + sidecar ----------------------------------------

    def _download_icon(self, icon: Dict[str, Any], query: str = "") -> Dict[str, Any]:
        """Pull SVG bytes, hash to a crystal, write svg + JSON sidecar.
        Defensive about the shape of the v2 response (fields vary)."""
        if not isinstance(icon, dict):
            return {"ok": False, "error": "icon not dict"}

        noun_id = str(icon.get("id", "") or icon.get("noun_id", "") or "")
        term = (icon.get("term") or icon.get("term_slug") or "").strip()
        tags_raw = icon.get("tags") or []
        if isinstance(tags_raw, list):
            tags = [str(t.get("slug") if isinstance(t, dict) else t)
                     for t in tags_raw if t]
        else:
            tags = []

        creator = icon.get("uploader") or icon.get("creator") or {}
        if isinstance(creator, dict):
            creator_dict = {
                "name": creator.get("name", ""),
                "username": creator.get("username", ""),
                "permalink": creator.get("permalink", ""),
            }
        else:
            creator_dict = {"name": str(creator)}

        license_desc = (icon.get("license_description")
                         or icon.get("license")
                         or "Creative Commons (verify per icon)")
        attribution = (icon.get("attribution")
                        or f"{creator_dict.get('name','')} via the Noun Project")

        # SVG URL — Noun Project v2 typically exposes a `icon_url` (SVG) or
        # `preview_url` (PNG). We prefer SVG; tolerate either.
        svg_url = (icon.get("icon_url")
                    or icon.get("svg_url")
                    or icon.get("preview_url_84")
                    or icon.get("preview_url")
                    or "")
        if not svg_url:
            return {"ok": False, "noun_id": noun_id, "error": "no icon_url in response"}

        # Only attempt OAuth-signed for thenounproject.com URLs; CDN URLs are public.
        headers: Dict[str, str] = {}
        if "api.thenounproject.com" in svg_url:
            headers["Authorization"] = _oauth1_header(
                "GET", svg_url, {}, self._consumer_key, self._consumer_secret)
        status, svg_bytes = _http_get_bytes(svg_url, headers=headers)
        if status != 200 or not svg_bytes:
            return {"ok": False, "noun_id": noun_id, "error": f"download_failed http_{status}"}

        is_svg = b"<svg" in svg_bytes[:512].lower()
        crystal = _svg_crystal(svg_bytes)
        crystal_short = crystal[:16]
        ext = "svg" if is_svg else "bin"
        out_svg = ICON_CORPUS_DIR / f"{crystal_short}.{ext}"
        out_json = ICON_CORPUS_DIR / f"{crystal_short}.json"

        # Skip rewrite if same crystal already on disk (true dedup).
        if not out_svg.exists():
            out_svg.write_bytes(svg_bytes)

        sidecar = {
            "noun_id": noun_id,
            "noun_term": term,
            "tags": tags,
            "use_cases": [query] if query else [],
            "license": license_desc,
            "attribution": attribution,
            "creator": creator_dict,
            "crystal": crystal,
            "crystal_short": crystal_short,
            "svg_url_origin": svg_url,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "is_svg": is_svg,
        }
        # Merge with any existing sidecar (extend use_cases / tags).
        if out_json.exists():
            try:
                prior = json.loads(out_json.read_text(encoding="utf-8"))
                merged_uses = list({*prior.get("use_cases", []), *sidecar["use_cases"]})
                merged_tags = list({*prior.get("tags", []), *sidecar["tags"]})
                prior.update({
                    "use_cases": merged_uses,
                    "tags": merged_tags,
                    "last_seen": sidecar["saved_at"],
                })
                sidecar = prior
            except Exception:
                pass
        out_json.write_text(json.dumps(sidecar, indent=2, sort_keys=True),
                              encoding="utf-8")

        # Per-icon crystal-chain entry (small payload).
        _log_import(
            tool="harvest_icon",
            params={"query": query, "noun_id": noun_id, "term": term},
            result={
                "id": noun_id, "term": term,
                "license_description": license_desc,
                "creator": creator_dict.get("name", ""),
                "preview_url": svg_url,
            },
            latency_ms=0, status_code=200,
        )

        return {
            "ok": True,
            "noun_id": noun_id,
            "noun_term": term,
            "tags": tags,
            "crystal": crystal,
            "crystal_short": crystal_short,
            "saved_svg": str(out_svg),
            "saved_sidecar": str(out_json),
            "saved_crystal": crystal,
            "license_description": license_desc,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="noun_project — Noun Project connector smoke")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("connect")
    p_search = sub.add_parser("search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=5)
    p_harv = sub.add_parser("harvest")
    p_harv.add_argument("--query", required=True)
    p_harv.add_argument("--limit", type=int, default=5)
    p_icon = sub.add_parser("icon")
    p_icon.add_argument("--id", required=True)
    p_coll = sub.add_parser("collection")
    p_coll.add_argument("--id", required=True)
    p_coll.add_argument("--limit", type=int, default=20)
    sub.add_parser("providers", help="list expected tools")

    args = ap.parse_args()
    c = NounProjectConnector()

    if args.cmd == "connect":
        ok = c.connect()
        print(json.dumps({"connected": ok,
                          "has_key": bool(c._consumer_key),
                          "has_secret": bool(c._consumer_secret)}, indent=2))
    elif args.cmd == "search":
        r = c.send("search", json.dumps({"query": args.query, "limit": args.limit}))
        print(json.dumps({"success": r.success, "error": r.error,
                          "preview": r.message_preview,
                          "meta": r.metadata}, indent=2, default=str))
    elif args.cmd == "harvest":
        r = c.send("harvest_query",
                    json.dumps({"query": args.query, "limit": args.limit}))
        print(json.dumps({"success": r.success, "error": r.error,
                          "preview": r.message_preview,
                          "meta": r.metadata}, indent=2, default=str))
    elif args.cmd == "icon":
        r = c.send("get_icon", json.dumps({"noun_id": args.id}))
        print(json.dumps({"success": r.success, "error": r.error,
                          "meta": r.metadata}, indent=2, default=str))
    elif args.cmd == "collection":
        r = c.send("list_terms_for_collection",
                    json.dumps({"collection_id": args.id, "limit": args.limit}))
        print(json.dumps({"success": r.success, "error": r.error,
                          "meta": r.metadata}, indent=2, default=str))
    elif args.cmd == "providers":
        print(json.dumps(list(EXPECTED_TOOLS), indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
