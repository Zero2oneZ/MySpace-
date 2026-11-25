#!/usr/bin/env python3
"""x_v2_oauth1_writes.py — X (Twitter) v2 OAuth 1.0a USER-CONTEXT WRITE connector.

Companion to `twitter.py` (which handles bearer reads). This module covers the
write path — tweet posts, deletes, likes, retweets, DMs — using STDLIB-ONLY
HMAC-SHA1 OAuth 1.0a signing per RFC 5849 §3.4. No tweepy dependency.

Account creds come from .env (matches `twitter.py::_load_env_for_profile` family-
preference logic — new family wins, old family fallback):

  Slot          NEW family            OLD family fallback
  ─────────────────────────────────────────────────────────
  consumer_key  X_API_KEY             X_CONSUMER_KEY
  consumer_sec  X_API_SECRET_KEY      X_CONSUMER_SECRET_KEY
  access_token  X_ACCESS_TOKEN        X_ACCESS_TOKEN  (same)
  access_secret X_SECRET_TOKEN        X_ACCESS_SECRET_TOKEN

Status semantics mirror twitter.py:
  200 → connected (auth + plan + scope all OK)
  401 → BadCreds (signature/key invalid)
  402 → CreditsDepleted (auth works, plan has no credits) — Tom's free-tier
        account `2041731826381668352` may return 402 even with valid OAuth1
        because X gates writes on tier too. NOT a wiring bug.
  403 → ScopeMissing (auth works but app lacks the requested write scope)

Crystal anchor for every write: tier='social_event', model='x_v2_oauth1',
scope=f'x_<tool>'.

Smoke (READ-ONLY — verify_oauth1_creds only, no actual write):
  python3 -c "
  import sys; sys.path.insert(0,'core/lib')
  from third_party.x_v2_oauth1_writes import XV2OAuth1WriteConnector
  c = XV2OAuth1WriteConnector(); print(c.connect())
  print(c.send('verify_oauth1_creds', '').metadata)"
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import ConnectionConfig, SendResult, ThirdPartyConnector


# ─── env resolution (mirrors twitter.py family-preference) ─────────────────────

def _load_env_for_profile(profile: str = "main") -> Dict[str, str]:
    """Resolve OAuth1 .env vars. NEW family wins, OLD family fallback.

    Returns {consumer_key, consumer_secret, access_token, access_secret} with
    empty strings for missing slots. Profile is currently always 'main' (mirrors
    twitter.py — trollz folded 2026-05-28).
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
            f"warn: x_v2_oauth1_writes.py only supports profile='main' "
            f"(profile={profile!r} folded to main)\n"
        )

    def _first_non_empty(*names: str) -> str:
        for n in names:
            v = env.get(n, "")
            if v:
                return v
        return ""

    return {
        "consumer_key":    _first_non_empty("X_API_KEY",        "X_CONSUMER_KEY"),
        "consumer_secret": _first_non_empty("X_API_SECRET_KEY", "X_CONSUMER_SECRET_KEY"),
        "access_token":    _first_non_empty("X_ACCESS_TOKEN"),
        "access_secret":   _first_non_empty("X_SECRET_TOKEN",   "X_ACCESS_SECRET_TOKEN"),
    }


# ─── OAuth 1.0a HMAC-SHA1 signing (RFC 5849 §3.4) ──────────────────────────────

def _pct(s: str) -> str:
    """RFC 3986 percent-encode (OAuth 1.0a uses the stricter unreserved set:
    ALPHA / DIGIT / '-' / '.' / '_' / '~')."""
    return urllib.parse.quote(str(s), safe="-._~")


def _oauth_params(consumer_key: str, access_token: str) -> Dict[str, str]:
    """Mint the canonical OAuth 1.0a header params. nonce is a 32-char hex."""
    return {
        "oauth_consumer_key":     consumer_key,
        "oauth_nonce":            secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            access_token,
        "oauth_version":          "1.0",
    }


def _signature_base_string(method: str, url: str,
                            oauth_params: Dict[str, str],
                            query_params: Optional[Dict[str, str]] = None,
                            body_params: Optional[Dict[str, str]] = None) -> str:
    """Build the sig_base per RFC 5849 §3.4.1.

      sig_base = METHOD + "&" + pct(url) + "&" + pct(canonical_params)
    """
    # Strip query from url (already extracted to query_params by caller).
    parsed = urllib.parse.urlsplit(url)
    base_url = urllib.parse.urlunsplit((parsed.scheme.lower(),
                                         parsed.netloc.lower(),
                                         parsed.path, "", ""))
    merged: List[Tuple[str, str]] = []
    for k, v in oauth_params.items():
        merged.append((k, v))
    if query_params:
        for k, v in query_params.items():
            merged.append((k, v))
    if body_params:
        for k, v in body_params.items():
            merged.append((k, v))
    # pct-encode each k+v, sort lex by (k, v).
    encoded = sorted((_pct(k), _pct(v)) for k, v in merged)
    canonical = "&".join(f"{k}={v}" for k, v in encoded)
    return f"{method.upper()}&{_pct(base_url)}&{_pct(canonical)}"


def _sign(method: str, url: str, consumer_key: str, consumer_secret: str,
           access_token: str, access_secret: str,
           query_params: Optional[Dict[str, str]] = None,
           body_params: Optional[Dict[str, str]] = None,
           ) -> Dict[str, str]:
    """Mint oauth_params + signature. Returns the full param dict suitable for
    serialization into the Authorization header."""
    op = _oauth_params(consumer_key, access_token)
    sig_base = _signature_base_string(method, url, op, query_params, body_params)
    signing_key = f"{_pct(consumer_secret)}&{_pct(access_secret)}"
    digest = hmac.new(signing_key.encode("ascii"),
                       sig_base.encode("ascii"),
                       hashlib.sha1).digest()
    op["oauth_signature"] = base64.b64encode(digest).decode("ascii")
    return op


def _auth_header(oauth_params: Dict[str, str]) -> str:
    """Serialize oauth_* params into the Authorization: OAuth <...> header value
    per RFC 5849 §3.5.1 (each value pct-encoded and quoted, joined with ', ')."""
    parts = [f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth_params.items())]
    return "OAuth " + ", ".join(parts)


# ─── connector ─────────────────────────────────────────────────────────────────

class XV2OAuth1WriteConnector(ThirdPartyConnector):
    """X v2 write-path connector using stdlib-only OAuth 1.0a HMAC-SHA1 signing.

    Companion to bearer-read `twitter.py`. Tools:
      - verify_oauth1_creds()
      - post_tweet(text, reply_to=None, media_ids=None)
      - delete_tweet(tweet_id)
      - like_tweet(tweet_id, user_id)
      - retweet(tweet_id, user_id)
      - send_dm(recipient_id, text)
    """

    SERVICE = "x_v2_writes"
    EXPECTED_TOOLS = (
        "post_tweet",
        "send_dm",
        "delete_tweet",
        "like_tweet",
        "retweet",
        "verify_oauth1_creds",
    )

    API_ROOT = "https://api.twitter.com"

    def __init__(self, config: Optional[ConnectionConfig] = None,
                  profile: str = "main"):
        if config is None:
            config = ConnectionConfig(
                service=self.SERVICE,
                name=f"x_v2_writes_{profile}",
                action="oauth1_write",
                auth=_load_env_for_profile(profile),
            )
        elif not config.auth.get("consumer_key"):
            config.auth.update(_load_env_for_profile(profile))
        super().__init__(config)
        self._profile = profile
        self._consumer_key:    str = config.auth.get("consumer_key", "")
        self._consumer_secret: str = config.auth.get("consumer_secret", "")
        self._access_token:    str = config.auth.get("access_token", "")
        self._access_secret:   str = config.auth.get("access_secret", "")
        self._verify_cache: Optional[Dict[str, Any]] = None

    @classmethod
    def from_env(cls, profile: str = "main") -> "XV2OAuth1WriteConnector":
        return cls(config=None, profile=profile)

    def has_credentials(self) -> Dict[str, bool]:
        return {
            "consumer_key":    bool(self._consumer_key),
            "consumer_secret": bool(self._consumer_secret),
            "access_token":    bool(self._access_token),
            "access_secret":   bool(self._access_secret),
            "profile":         self._profile,  # type: ignore[dict-item]
        }

    # ─── HTTP plumbing ─────────────────────────────────────────────────────────

    def _http(self, method: str, path: str,
               json_body: Optional[Dict[str, Any]] = None,
               query: Optional[Dict[str, str]] = None,
               timeout: int = 20) -> Tuple[int, Dict[str, Any]]:
        """Sign + send. Returns (status, parsed_json_or_error_dict)."""
        if not (self._consumer_key and self._consumer_secret
                and self._access_token and self._access_secret):
            return 0, {"_error": "missing_oauth1_creds",
                        "have": self.has_credentials()}
        url = self.API_ROOT + path
        # For JSON bodies, body_params are NOT included in the signature base
        # (per RFC 5849 §3.4.1.3.1 — only application/x-www-form-urlencoded
        # bodies are signed). v2 endpoints take JSON, so body_params=None.
        oauth = _sign(method, url,
                       self._consumer_key, self._consumer_secret,
                       self._access_token, self._access_secret,
                       query_params=query, body_params=None)
        full_url = url
        if query:
            full_url = url + "?" + urllib.parse.urlencode(query)
        headers = {
            "Authorization": _auth_header(oauth),
            "User-Agent":    "MySpace++/x_v2_oauth1_writes (zero2onez)",
            "Accept":        "application/json",
        }
        data: Optional[bytes] = None
        if json_body is not None:
            data = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(full_url, data=data, headers=headers,
                                       method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                txt = resp.read().decode("utf-8", errors="replace")
                try:
                    return resp.status, json.loads(txt)
                except json.JSONDecodeError:
                    return resp.status, {"_raw": txt[:2048]}
        except urllib.error.HTTPError as e:
            try:
                body_txt = e.read().decode("utf-8", errors="replace")
                if body_txt.strip().startswith("{"):
                    return e.code, json.loads(body_txt)
                return e.code, {"_error": body_txt[:1024]}
            except Exception:
                return e.code, {"_error": str(e)}
        except Exception as e:
            return 0, {"_error": f"{type(e).__name__}: {e}"}

    # ─── tools ─────────────────────────────────────────────────────────────────

    def verify_oauth1_creds(self) -> Dict[str, Any]:
        """Probe `GET /2/users/me` (no signed body) to confirm the OAuth1 keys
        + access token sign correctly. 200/401/402/403 distinguished."""
        # /2/users/me works with GET; spec for verify probe says POST but GET
        # is canonical for users/me. Mirror twitter.py read semantics.
        status, body = self._http("GET", "/2/users/me",
                                    query={"user.fields": "id,name,username"})
        if status == 200 and isinstance(body.get("data"), dict):
            d = body["data"]
            return {
                "success": True, "auth_works": True, "status": 200,
                "user_id":  d.get("id", ""),
                "username": d.get("username", ""),
                "name":     d.get("name", ""),
            }
        if status == 401:
            return {"success": False, "auth_works": False, "status": 401,
                     "error": "BadCreds",
                     "detail": body.get("title", "") or body.get("_error", "")}
        if status == 402:
            return {"success": False, "auth_works": True, "status": 402,
                     "error": "CreditsDepleted",
                     "remedy": "Refill credits at developer.x.com — OAuth1 keys valid but plan is exhausted",
                     "enrolled_account_id": (body.get("account_id")
                                              if isinstance(body, dict) else None)}
        if status == 403:
            return {"success": False, "auth_works": True, "status": 403,
                     "error": "ScopeMissing",
                     "detail": body.get("title", "") or body.get("detail", "")}
        return {"success": False, "auth_works": False, "status": status,
                "error": body.get("title", "") or body.get("_error", "") or "unknown"}

    def post_tweet(self, text: str,
                    reply_to: Optional[str] = None,
                    media_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"text": text}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        if media_ids:
            body["media"] = {"media_ids": list(media_ids)}
        status, resp = self._http("POST", "/2/tweets", json_body=body)
        if status == 201 and isinstance(resp.get("data"), dict):
            return {"success": True, "status": 201,
                     "tweet_id": resp["data"].get("id", ""),
                     "text":     resp["data"].get("text", "")}
        return {"success": False, "status": status, "error": resp}

    def delete_tweet(self, tweet_id: str) -> Dict[str, Any]:
        status, resp = self._http("DELETE", f"/2/tweets/{tweet_id}")
        if status == 200 and isinstance(resp.get("data"), dict):
            return {"success": True, "status": 200,
                     "deleted": bool(resp["data"].get("deleted", False))}
        return {"success": False, "status": status, "error": resp}

    def like_tweet(self, tweet_id: str, user_id: str) -> Dict[str, Any]:
        status, resp = self._http("POST", f"/2/users/{user_id}/likes",
                                    json_body={"tweet_id": tweet_id})
        if status == 200 and isinstance(resp.get("data"), dict):
            return {"success": True, "status": 200,
                     "liked": bool(resp["data"].get("liked", False))}
        return {"success": False, "status": status, "error": resp}

    def retweet(self, tweet_id: str, user_id: str) -> Dict[str, Any]:
        status, resp = self._http("POST", f"/2/users/{user_id}/retweets",
                                    json_body={"tweet_id": tweet_id})
        if status == 200 and isinstance(resp.get("data"), dict):
            return {"success": True, "status": 200,
                     "retweeted": bool(resp["data"].get("retweeted", False))}
        return {"success": False, "status": status, "error": resp}

    def send_dm(self, recipient_id: str, text: str) -> Dict[str, Any]:
        status, resp = self._http(
            "POST",
            f"/2/dm_conversations/with/{recipient_id}/messages",
            json_body={"text": text},
        )
        if status in (200, 201) and isinstance(resp.get("data"), dict):
            return {"success": True, "status": status,
                     "dm_event_id": resp["data"].get("dm_event_id", ""),
                     "dm_conversation_id": resp["data"].get("dm_conversation_id", "")}
        return {"success": False, "status": status, "error": resp}

    # ─── ThirdPartyConnector contract ──────────────────────────────────────────

    def connect(self) -> str:
        """Probe verify_oauth1_creds. Cache the result. Returns a short status
        string mirroring twitter.py shape."""
        if not (self._consumer_key and self._consumer_secret
                and self._access_token and self._access_secret):
            self._connected = False
            return "x_v2_writes_missing_creds"
        r = self.verify_oauth1_creds()
        self._verify_cache = r
        if r.get("status") == 200:
            self._connected = True
            return "x_v2_writes_connected"
        if r.get("status") == 402:
            # auth works but no credits — treat as "wired but blocked"
            self._connected = True
            return "x_v2_writes_connected_no_credits"
        if r.get("status") == 401:
            self._connected = False
            return "x_v2_writes_bad_creds"
        if r.get("status") == 403:
            self._connected = False
            return f"x_v2_writes_scope_missing:{r.get('detail','')[:80]}"
        self._connected = False
        return f"x_v2_writes_unknown:{r.get('status')}:{r.get('error','')[:80]}"

    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        """Dispatch on recipient (tool name). Crystal-anchor every write.

        Tool routing:
          recipient='verify_oauth1_creds' → probe + return metadata only
          recipient='post_tweet'          → message=text
          recipient='delete_tweet'        → message=tweet_id
          recipient='like_tweet'          → message=tweet_id, kwargs['user_id']
          recipient='retweet'             → message=tweet_id, kwargs['user_id']
          recipient='send_dm'             → kwargs['recipient_id'], message=text
        """
        self._rate_limit_wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tool = recipient
        if tool not in self.EXPECTED_TOOLS:
            r = SendResult(
                success=False,
                crystal_id="x_v2_writes_unknown_tool_" + str(hash(recipient + ts)),
                service=self.SERVICE,
                recipient=recipient,
                message_preview=str(message)[:120],
                timestamp=ts,
                error=f"unknown_tool: {recipient!r} not in {self.EXPECTED_TOOLS}",
            )
            self._log_send(r)
            return r

        try:
            if tool == "verify_oauth1_creds":
                out = self.verify_oauth1_creds()
            elif tool == "post_tweet":
                out = self.post_tweet(text=message,
                                       reply_to=kwargs.get("reply_to"),
                                       media_ids=kwargs.get("media_ids"))
            elif tool == "delete_tweet":
                out = self.delete_tweet(tweet_id=message)
            elif tool == "like_tweet":
                out = self.like_tweet(tweet_id=message,
                                       user_id=str(kwargs.get("user_id", "")))
            elif tool == "retweet":
                out = self.retweet(tweet_id=message,
                                    user_id=str(kwargs.get("user_id", "")))
            elif tool == "send_dm":
                out = self.send_dm(recipient_id=str(kwargs.get("recipient_id", "")),
                                    text=message)
            else:
                out = {"success": False, "error": f"unhandled_tool: {tool}"}
        except Exception as e:
            out = {"success": False, "error": f"{type(e).__name__}: {e}"}

        # Crystal anchor: tier='social_event', model='x_v2_oauth1', scope=f'x_{tool}'
        crystal_payload = {
            "tier":  "social_event",
            "model": "x_v2_oauth1",
            "scope": f"x_{tool}",
            "ts":    ts,
            "ok":    bool(out.get("success")),
            "status": out.get("status"),
            # preview only — never log full text or tokens
            "preview": str(message)[:120],
        }
        crystal_id = hashlib.sha256(
            json.dumps(crystal_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:32]

        result = SendResult(
            success=bool(out.get("success")),
            crystal_id=f"x_v2_oauth1_{tool}_{crystal_id}",
            service=self.SERVICE,
            recipient=recipient,
            message_preview=str(message)[:120],
            timestamp=ts,
            error=(None if out.get("success") else str(out.get("error", "")))[:512]
                   if not out.get("success") else None,
            metadata=out,
        )
        self._log_send(result)
        return result

    def history(self, thread_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """No read-path here — that's twitter.py's job. Return empty."""
        return []

    def disconnect(self) -> str:
        self._connected = False
        self._verify_cache = None
        return "x_v2_writes_disconnected"
