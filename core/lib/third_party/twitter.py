#!/usr/bin/env python3
"""twitter.py — X (Twitter) outbound + harvest connector.

Single profile backed by .env vars:
  X_BEARER_TOKEN + X_CONSUMER_KEY + X_CONSUMER_SECRET_KEY
  + X_ACCESS_TOKEN + X_ACCESS_SECRET_TOKEN

Note 2026-05-28: bearer probe of all 8 X-prefixed vars confirmed only the two
BEARER-shaped ones (X_BEARER_TOKEN, X_TROLLZ_BEARER) auth past 401 — and both
route to enrolled_account_id=2041735171829911552 which returns 402 Credits-
Depleted. The trollz keys are stale (the X dev account was effectively deleted
but its env vars still reference what is now the surviving main account).
Trollz profile removed from this module; only the main profile remains.
Tom needs to refill credits at developer.x.com OR provision a new X dev account
with credits before any read/write call will succeed.

Dependency: `pip install tweepy` for write path.
Read path works via stdlib urllib + bearer (no tweepy required).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

from .base import ThirdPartyConnector, ConnectionConfig, SendResult


def _load_env_for_profile(profile: str = "main") -> Dict[str, str]:
    """Resolve X .env vars. Single profile (trollz removed — see module docstring).
    Returns dict with bearer/consumer/access slots; empty strings for missing vars.

    Each slot tries the NEW name family first (matches official developer.x.com
    project terminology) and falls back to the OLD name family for backward
    compat. The first non-empty value wins per slot — letting Tom switch
    families incrementally just by adding new env vars.

    Slot          NEW family            OLD family fallback
    ─────────────────────────────────────────────────────────
    bearer_token  X_API_BEARER_TOKEN    X_BEARER_TOKEN
    consumer_key  X_API_KEY             X_CONSUMER_KEY
    consumer_sec  X_API_SECRET_KEY      X_CONSUMER_SECRET_KEY
    access_token  X_ACCESS_TOKEN        X_ACCESS_TOKEN  (same)
    access_secret X_SECRET_TOKEN        X_ACCESS_SECRET_TOKEN
    """
    env: Dict[str, str] = {}
    try:
        _here = Path(__file__).resolve().parent
        sys.path.insert(0, str(_here.parent.parent.parent / "studio"))
        from auth.keys import load_env  # type: ignore
        env = load_env()
    except Exception:
        env = dict(os.environ)

    if profile != "main":
        sys.stderr.write(
            f"warn: twitter.py only supports profile='main' now "
            f"(profile={profile!r} folded to main; trollz removed 2026-05-28)\n"
        )

    def _first_non_empty(*names: str) -> str:
        for n in names:
            v = env.get(n, "")
            if v:
                return v
        return ""

    return {
        "bearer_token":    _first_non_empty("X_API_BEARER_TOKEN", "X_BEARER_TOKEN"),
        "consumer_key":    _first_non_empty("X_API_KEY",          "X_CONSUMER_KEY"),
        "consumer_secret": _first_non_empty("X_API_SECRET_KEY",   "X_CONSUMER_SECRET_KEY"),
        "access_token":    _first_non_empty("X_ACCESS_TOKEN"),
        "access_secret":   _first_non_empty("X_SECRET_TOKEN",     "X_ACCESS_SECRET_TOKEN"),
    }


def diagnose_env() -> Dict[str, Any]:
    """Report which env var family is providing each slot — values stay hidden,
    only the source NAME + value-length are reported. Useful for `cc twitter-diag`."""
    env: Dict[str, str] = {}
    try:
        _here = Path(__file__).resolve().parent
        sys.path.insert(0, str(_here.parent.parent.parent / "studio"))
        from auth.keys import load_env  # type: ignore
        env = load_env()
    except Exception:
        env = dict(os.environ)
    slot_map = [
        ("bearer_token",    ["X_API_BEARER_TOKEN", "X_BEARER_TOKEN"]),
        ("consumer_key",    ["X_API_KEY",          "X_CONSUMER_KEY"]),
        ("consumer_secret", ["X_API_SECRET_KEY",   "X_CONSUMER_SECRET_KEY"]),
        ("access_token",    ["X_ACCESS_TOKEN"]),
        ("access_secret",   ["X_SECRET_TOKEN",     "X_ACCESS_SECRET_TOKEN"]),
    ]
    out: Dict[str, Any] = {"slots": {}, "new_family_present": False, "old_family_present": False}
    for slot, names in slot_map:
        active_name = ""
        active_len = 0
        candidates = []
        for n in names:
            v = env.get(n, "")
            candidates.append({"name": n, "present": n in env, "value_len": len(v)})
            if v and not active_name:
                active_name = n
                active_len = len(v)
                if n.startswith("X_API_") or n == "X_SECRET_TOKEN":
                    out["new_family_present"] = True
                else:
                    out["old_family_present"] = True
        out["slots"][slot] = {
            "active_source": active_name or "EMPTY",
            "value_len": active_len,
            "candidates": candidates,
        }
    return out


class TwitterConnector(ThirdPartyConnector):
    SERVICE = "twitter"

    def __init__(self, config: Optional[ConnectionConfig] = None,
                  profile: str = "main"):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name=f"twitter_{profile}",
                action="x_api",
                auth=_load_env_for_profile(profile),
            )
        elif not config.auth.get("bearer_token") and not config.auth.get("consumer_key"):
            # config provided but empty auth → fill from env
            config.auth.update(_load_env_for_profile(profile))
        super().__init__(config)
        self._profile = profile
        self._api: Any = None
        self._client: Any = None
        self._bearer: str = config.auth.get("bearer_token", "")
        self._consumer_key: str = config.auth.get("consumer_key", "")
        self._consumer_secret: str = config.auth.get("consumer_secret", "")
        self._access_token: str = config.auth.get("access_token", "")
        self._access_secret: str = config.auth.get("access_secret", "")

    @classmethod
    def from_env(cls, profile: str = "main") -> "TwitterConnector":
        """Build a connector from .env vars (the canonical entry point)."""
        return cls(config=None, profile=profile)

    def has_credentials(self) -> Dict[str, bool]:
        """Report which credential slots are populated. Values stay hidden."""
        return {
            "bearer_token":    bool(self._bearer),
            "consumer_key":    bool(self._consumer_key),
            "consumer_secret": bool(self._consumer_secret),
            "access_token":    bool(self._access_token),
            "access_secret":   bool(self._access_secret),
            "profile":         self._profile,  # type: ignore[dict-item]
        }

    # ---- Stdlib read-path (no tweepy required) ----

    def _http_x_get(self, path: str, params: Optional[Dict[str, str]] = None,
                     timeout: int = 15) -> tuple:
        """Bearer-auth GET against api.twitter.com. Returns (status, json_dict)."""
        import urllib.parse
        import urllib.request
        import urllib.error
        import json as _json
        if not self._bearer:
            return 0, {"_error": "no_bearer_token"}
        url = "https://api.twitter.com" + path
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self._bearer}",
            "User-Agent": "MySpace++/freetier_gate (zero2onez)",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                txt = resp.read().decode("utf-8", errors="replace")
                try:
                    return resp.status, _json.loads(txt)
                except _json.JSONDecodeError:
                    return resp.status, {"_raw": txt[:2048]}
        except urllib.error.HTTPError as e:
            try:
                body_txt = e.read().decode("utf-8", errors="replace")
                if body_txt.strip().startswith("{"):
                    return e.code, _json.loads(body_txt)
                return e.code, {"_error": body_txt[:1024]}
            except Exception:
                return e.code, {"_error": str(e)}
        except Exception as e:
            return 0, {"_error": f"{type(e).__name__}: {e}"}

    def verify_credentials(self) -> Dict[str, Any]:
        """Read-only smoke via stdlib urllib + bearer token (NO tweepy dep).
        Looks up the well-known @X account — proves the bearer works.

        Important distinction:
          status=200 → auth works AND request fulfilled
          status=402 → auth works but X plan has no credits (Tom needs to
                        refill at developer.x.com — NOT a wiring bug)
          status=401 → auth FAILED (bad bearer)
          status=403 → auth works but missing scopes
        """
        if not self._bearer:
            return {"success": False, "error": "no_bearer_token", "auth_works": False}
        status, body = self._http_x_get("/2/users/by/username/X",
                                          {"user.fields": "id,name,username,verified"})
        if status == 200 and isinstance(body.get("data"), dict):
            return {
                "success": True, "auth_works": True,
                "probe_account": "@X",
                "probe_user_id": body["data"].get("id", ""),
            }
        if status == 402:
            # CreditsDepleted — auth passed, plan is the problem
            return {
                "success": False, "auth_works": True, "status": 402,
                "error": "CreditsDepleted",
                "remedy": "Refill X API credits at developer.x.com; profile keys are valid",
                "enrolled_account_id": (body.get("account_id") if isinstance(body, dict) else None),
            }
        if status == 401:
            return {"success": False, "auth_works": False, "status": 401,
                     "error": body.get("title", "Unauthorized")}
        if status == 403:
            return {"success": False, "auth_works": True, "status": 403,
                     "error": "scope_missing", "detail": body.get("title", "")}
        return {"success": False, "status": status, "auth_works": False,
                "error": body.get("title", "") or body.get("_error", "") or "lookup_failed"}

    def get_user(self, username: str) -> Dict[str, Any]:
        """Look up a user by handle. Stdlib + bearer."""
        status, body = self._http_x_get(f"/2/users/by/username/{username.lstrip('@')}",
                                          {"user.fields": "id,name,username,public_metrics,verified"})
        if status == 200 and isinstance(body.get("data"), dict):
            return {"success": True, **body["data"]}
        return {"success": False, "status": status, "error": body}

    def recent_tweets(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """Search recent tweets matching query. Stdlib + bearer."""
        status, body = self._http_x_get(
            "/2/tweets/search/recent",
            {"query": query, "max_results": str(max(10, min(100, max_results))),
              "tweet.fields": "created_at,public_metrics,author_id,lang"},
        )
        if status == 200 and isinstance(body.get("data"), list):
            return {"success": True, "count": len(body["data"]),
                     "tweets": body["data"][:max_results]}
        return {"success": False, "status": status, "error": body}

    def connect(self) -> str:
        try:
            import tweepy
            self._client = tweepy.Client(
                bearer_token=self._bearer,
                consumer_key=self._consumer_key,
                consumer_secret=self._consumer_secret,
                access_token=self._access_token,
                access_token_secret=self._access_secret,
            )
            self._connected = True
            return "twitter_connected"
        except Exception as e:
            self._connected = False
            return f"tweepy_missing:{e}"

    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        self._rate_limit_wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self._connected or self._client is None:
            result = SendResult(
                success=False,
                crystal_id="twitter_stub_" + str(hash(recipient + message + ts)),
                service="twitter",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
                error="tweepy not installed or not connected",
            )
            self._log_send(result)
            return result

        try:
            # recipient = "tweet" for timeline, otherwise DM user_id
            if recipient == "tweet" or recipient == "":
                resp = self._client.create_tweet(text=message)
                tweet_id = resp.data["id"] if resp and resp.data else ""
                result = SendResult(
                    success=True,
                    crystal_id="twitter_" + str(hash(message + ts)),
                    service="twitter",
                    recipient="timeline",
                    message_preview=message[:120],
                    timestamp=ts,
                    metadata={"tweet_id": tweet_id},
                )
            else:
                resp = self._client.send_direct_message(participant_id=recipient, text=message)
                result = SendResult(
                    success=True,
                    crystal_id="twitter_" + str(hash(recipient + message + ts)),
                    service="twitter",
                    recipient=recipient,
                    message_preview=message[:120],
                    timestamp=ts,
                    metadata={"dm_id": resp.id if resp else ""},
                )
        except Exception as e:
            result = SendResult(
                success=False,
                crystal_id="twitter_err_" + str(hash(recipient + message + ts)),
                service="twitter",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
                error=str(e),
            )
        self._log_send(result)
        return result

    def history(self, thread_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return []

    def disconnect(self) -> str:
        self._connected = False
        return "twitter_disconnected"
