#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        freetier_gate
# role:        AUTH · PUBLIC_TIER_TOKEN_ISSUER_AND_VERIFIER
# tier:        L0
# substrate:   the ONE gate between public callback URLs and the proprietary MCPs
# storage:     studio/auth/freetier_acceptances.sqlite + crystal chain
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - studio/endpoints/freetier_callback/server.py (issues tokens after acceptance)
#   - core/lib/model_api.py (verifies tokens on /v1/* requests)
#   - core/lib/third_party/generative_mcp.py (verifies token before external call)
#   - any future externally-reachable surface
# outbound:
#   - inference_logger.log (tier='legal_acceptance', model='callback_handler')
# substrate touch:
#   - reads:  MYSPACE_KEY_MASTER from studio/auth/keys.master_secret()
#   - writes: studio/auth/freetier_acceptances.sqlite (per-user acceptance ledger)
#   - writes: crystal chain (every acceptance event)
# ----------------------------------------------------------------------------
# THE TWO PUBLIC DOMAINS
# ----------------------------------------------------------------------------
# GentlyOS.io  — free tier; path /endpoint/freetier/terms/policies/callback/
# trollz.fun    — TROLLN tier; path /terms/policies/callback/
# Tokens issued by either domain can be configured cross-domain or scoped per-domain.
# Default v1: per-domain (TROLLN-gated stays on trollz.fun).
# ============================================================================
"""freetier_gate.py — the public-tier token gate.

Issues HMAC-signed session tokens AFTER a user has accepted terms and
policies through one of the two callback URLs. Records every acceptance
event in (a) a sqlite ledger at studio/auth/freetier_acceptances.sqlite
and (b) the crystal chain as tier='legal_acceptance'.

Every proprietary MCP surface that is reachable from the public internet
must wrap its handler with `require_token(handler)` or call
`verify_token(token_str, domain) -> Optional[TokenClaims]` directly.

Token format (compact, JWT-shaped but stdlib only):
    header.payload.sig
where header = base64url({"alg":"HS256","kind":"freetier_v1"})
      payload = base64url({"user_id","domain","tier","accepted_terms_hash","iat","exp"})
      sig = base64url(hmac_sha256(MYSPACE_KEY_MASTER, header + "." + payload))
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))


# ---------------------------------------------------------------------------
# Domain config — the only two public surfaces
# ---------------------------------------------------------------------------

DOMAINS: Dict[str, Dict[str, Any]] = {
    "GentlyOS.io": {
        "callback_path":  "/endpoint/freetier/terms/policies/callback/",
        "tier":           "freetier",
        "cross_domain":   False,   # v1: token scoped to this domain
        "terms_url":      "/endpoint/freetier/terms/",
        "policies_url":   "/endpoint/freetier/policies/",
        "accepted_terms_hash_default": "",  # filled when terms text published
    },
    "trollz.fun": {
        "callback_path":  "/terms/policies/callback/",
        "tier":           "trolln_tier",
        "cross_domain":   False,
        "terms_url":      "/terms/",
        "policies_url":   "/policies/",
        "accepted_terms_hash_default": "",
    },
}


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

LEDGER_PATH = Path(os.environ.get(
    "MYSPACE_FREETIER_LEDGER",
    str(_PROJECT_ROOT / "studio" / "auth" / "freetier_acceptances.sqlite"),
))


def _connect() -> sqlite3.Connection:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(LEDGER_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS acceptances (
        user_id TEXT NOT NULL,
        domain TEXT NOT NULL,
        tier TEXT NOT NULL,
        accepted_at INTEGER NOT NULL,
        accepted_terms_hash TEXT NOT NULL,
        ip TEXT NOT NULL,
        user_agent TEXT NOT NULL,
        crystal_id TEXT NOT NULL,
        PRIMARY KEY (user_id, domain)
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_accepted_at ON acceptances (accepted_at)""")
    return conn


# ---------------------------------------------------------------------------
# Master secret
# ---------------------------------------------------------------------------

def _master_secret() -> bytes:
    """Resolve via studio/auth/keys.master_secret() — single source of truth."""
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "studio"))
        from auth.keys import master_secret  # type: ignore
        s = master_secret()
        if isinstance(s, bytes) and len(s) >= 16:
            return s
        if isinstance(s, str) and len(s) >= 16:
            return s.encode("utf-8")
    except Exception:
        pass
    env = os.environ.get("MYSPACE_KEY_MASTER", "")
    if env:
        return env.encode("utf-8")
    # Final fallback: deterministic from project path (NEVER for production)
    return hashlib.sha256(str(_PROJECT_ROOT).encode("utf-8")).digest()


# ---------------------------------------------------------------------------
# Token codec
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


@dataclass
class TokenClaims:
    user_id: str
    domain: str
    tier: str
    accepted_terms_hash: str
    iat: int
    exp: int
    friends_consent: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def issue_token(user_id: str, domain: str,
                  accepted_terms_hash: str,
                  ttl_seconds: int = 30 * 24 * 3600,
                  friends_consent: bool = False) -> str:
    """Issue a signed freetier token. Caller must have already recorded the
    acceptance event via record_acceptance() — this just stamps the token.

    If ``friends_consent`` is True, the token's payload carries an extra
    ``friends_consent: true`` claim. The friends-graph harvester refuses
    to harvest unless this claim is True on the bearer.
    """
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain: {domain}")
    cfg = DOMAINS[domain]
    now = int(time.time())
    claims = TokenClaims(
        user_id=user_id,
        domain=domain,
        tier=cfg["tier"],
        accepted_terms_hash=accepted_terms_hash,
        iat=now,
        exp=now + ttl_seconds,
        friends_consent=bool(friends_consent),
    )
    header = {"alg": "HS256", "kind": "freetier_v1"}
    h = _b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    p = _b64url(json.dumps(claims.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{h}.{p}".encode("ascii")
    sig = hmac.new(_master_secret(), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def verify_token(token: str, expected_domain: Optional[str] = None) -> Optional[TokenClaims]:
    """Return TokenClaims if valid + non-expired + (optionally) for expected_domain.
    Returns None on any failure. Never raises."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h_b64, p_b64, sig_b64 = parts
        signing_input = f"{h_b64}.{p_b64}".encode("ascii")
        expected_sig = hmac.new(_master_secret(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig_b64), expected_sig):
            return None
        header = json.loads(_b64url_decode(h_b64))
        if header.get("alg") != "HS256" or header.get("kind") != "freetier_v1":
            return None
        payload = json.loads(_b64url_decode(p_b64))
        claims = TokenClaims(
            user_id=payload["user_id"],
            domain=payload["domain"],
            tier=payload["tier"],
            accepted_terms_hash=payload["accepted_terms_hash"],
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
            # Backward-compat: tokens issued before friends_consent landed
            # simply default to False.
            friends_consent=bool(payload.get("friends_consent", False)),
        )
        if claims.exp < int(time.time()):
            return None
        if expected_domain and claims.domain != expected_domain:
            # Per-domain scoping (v1 default): cross-domain rejected
            if not DOMAINS.get(claims.domain, {}).get("cross_domain", False):
                return None
        return claims
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Acceptance ledger + crystal anchor
# ---------------------------------------------------------------------------

def record_acceptance(user_id: str, domain: str,
                        ip: str = "", user_agent: str = "",
                        accepted_terms_hash: str = "",
                        friends_consent: bool = False) -> str:
    """Record a legal acceptance event. Writes to sqlite + crystal chain.
    Returns the crystal_id. Idempotent on (user_id, domain) — re-acceptance
    updates accepted_at + crystal_id but does NOT duplicate.

    ``friends_consent`` (optional) records whether the user authorized the
    Facebook ``user_friends`` scope harvest at the time of acceptance. The
    flag is forwarded to the crystal anchor for audit; the per-row sqlite
    schema is unchanged for backward-compat (the flag lives on the
    issued token + crystal entry).
    """
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain: {domain}")
    cfg = DOMAINS[domain]
    if not accepted_terms_hash:
        accepted_terms_hash = cfg.get("accepted_terms_hash_default", "") or hashlib.sha256(
            (cfg["terms_url"] + cfg["policies_url"]).encode("utf-8")
        ).hexdigest()[:32]
    now = int(time.time())
    tier = cfg["tier"]

    crystal_id = _crystal_anchor_acceptance(user_id, domain, tier,
                                              accepted_terms_hash, now,
                                              ip, user_agent,
                                              friends_consent=bool(friends_consent))

    with _connect() as conn:
        conn.execute("""INSERT INTO acceptances
            (user_id, domain, tier, accepted_at, accepted_terms_hash, ip, user_agent, crystal_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, domain) DO UPDATE SET
                accepted_at = excluded.accepted_at,
                accepted_terms_hash = excluded.accepted_terms_hash,
                ip = excluded.ip,
                user_agent = excluded.user_agent,
                crystal_id = excluded.crystal_id
        """, (user_id, domain, tier, now, accepted_terms_hash, ip, user_agent, crystal_id))
        conn.commit()
    return crystal_id


def lookup_acceptance(user_id: str, domain: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("""SELECT user_id, domain, tier, accepted_at,
                                       accepted_terms_hash, ip, user_agent, crystal_id
                                FROM acceptances
                                WHERE user_id = ? AND domain = ?""",
                              (user_id, domain)).fetchone()
    if not row:
        return None
    return {
        "user_id": row[0], "domain": row[1], "tier": row[2],
        "accepted_at": row[3], "accepted_terms_hash": row[4],
        "ip": row[5], "user_agent": row[6], "crystal_id": row[7],
    }


def list_acceptances(domain: Optional[str] = None, limit: int = 50) -> list:
    with _connect() as conn:
        if domain:
            cursor = conn.execute("""SELECT user_id, domain, tier, accepted_at, crystal_id
                                       FROM acceptances WHERE domain = ?
                                       ORDER BY accepted_at DESC LIMIT ?""", (domain, limit))
        else:
            cursor = conn.execute("""SELECT user_id, domain, tier, accepted_at, crystal_id
                                       FROM acceptances
                                       ORDER BY accepted_at DESC LIMIT ?""", (limit,))
        return [
            {"user_id": r[0], "domain": r[1], "tier": r[2],
             "accepted_at": r[3], "crystal_id": r[4]}
            for r in cursor.fetchall()
        ]


def _crystal_anchor_acceptance(user_id: str, domain: str, tier: str,
                                 accepted_terms_hash: str, ts: int,
                                 ip: str, user_agent: str,
                                 friends_consent: bool = False) -> str:
    try:
        from inference_logger import InferenceLogger  # type: ignore
        il = InferenceLogger()
        return il.log(
            original_prompt=f"legal_acceptance:{domain}",
            enhanced_prompt=f"user={user_id} terms_hash={accepted_terms_hash[:16]}",
            output_text=json.dumps({"tier": tier, "ts": ts, "ip_prefix": ip[:8],
                                      "ua_prefix": user_agent[:32],
                                      "friends_consent": bool(friends_consent)},
                                     separators=(",", ":")),
            tier="legal_acceptance", model="callback_handler",
            scope=f"acceptance_{domain.replace('.', '_')}",
            tokens_in=0, tokens_out=0, latency_ms=0,
            source_action="terms_policies_signed",
            done_flag=True, rc=0,
        ) or ""
    except Exception as e:
        sys.stderr.write(f"warn: acceptance crystal log failed: {type(e).__name__}: {e}\n")
        return ""


# ---------------------------------------------------------------------------
# Middleware helper (use in any external HTTP handler)
# ---------------------------------------------------------------------------

def extract_token_from_headers(headers: Dict[str, str]) -> str:
    """Pull bearer token from Authorization or X-Freetier-Token header."""
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (headers.get("X-Freetier-Token") or headers.get("x-freetier-token") or "").strip()


def require_token(headers: Dict[str, str], expected_domain: Optional[str] = None) -> Optional[TokenClaims]:
    """Return TokenClaims if valid, else None. Caller responds 401 on None."""
    return verify_token(extract_token_from_headers(headers), expected_domain)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="freetier_gate — public-tier token gate")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("domains", help="list configured public domains")

    p_issue = sub.add_parser("issue", help="issue a token (manual, e.g. for smoke)")
    p_issue.add_argument("--user-id", required=True)
    p_issue.add_argument("--domain", required=True, choices=list(DOMAINS.keys()))
    p_issue.add_argument("--terms-hash", default="")
    p_issue.add_argument("--ttl", type=int, default=30 * 24 * 3600)
    p_issue.add_argument("--record", action="store_true",
                          help="also record acceptance in ledger + crystal chain")
    p_issue.add_argument("--ip", default="127.0.0.1")
    p_issue.add_argument("--user-agent", default="cc_smoke")
    p_issue.add_argument("--friends-consent", action="store_true",
                          help="stamp friends_consent=True on the issued token")

    p_verify = sub.add_parser("verify", help="verify a token + print claims")
    p_verify.add_argument("token")
    p_verify.add_argument("--expected-domain", default=None,
                            choices=list(DOMAINS.keys()) + [None])

    p_list = sub.add_parser("list", help="list recent acceptances")
    p_list.add_argument("--domain", default=None, choices=list(DOMAINS.keys()) + [None])
    p_list.add_argument("--limit", type=int, default=20)

    p_lookup = sub.add_parser("lookup")
    p_lookup.add_argument("--user-id", required=True)
    p_lookup.add_argument("--domain", required=True, choices=list(DOMAINS.keys()))

    args = ap.parse_args()

    if args.cmd == "domains":
        print(json.dumps(DOMAINS, indent=2))

    elif args.cmd == "issue":
        if args.record:
            crystal = record_acceptance(args.user_id, args.domain,
                                          ip=args.ip, user_agent=args.user_agent,
                                          accepted_terms_hash=args.terms_hash,
                                          friends_consent=args.friends_consent)
        else:
            crystal = ""
        token = issue_token(args.user_id, args.domain,
                              accepted_terms_hash=args.terms_hash or
                                  hashlib.sha256(args.domain.encode("utf-8")).hexdigest()[:32],
                              ttl_seconds=args.ttl,
                              friends_consent=args.friends_consent)
        print(json.dumps({"token": token, "crystal_id_for_acceptance": crystal[:24] if crystal else "",
                            "expires_in_seconds": args.ttl,
                            "friends_consent": bool(args.friends_consent)}, indent=2))

    elif args.cmd == "verify":
        claims = verify_token(args.token, args.expected_domain)
        if claims:
            print(json.dumps({"valid": True, "claims": claims.to_dict()}, indent=2))
        else:
            print(json.dumps({"valid": False}, indent=2))

    elif args.cmd == "list":
        rows = list_acceptances(domain=args.domain, limit=args.limit)
        for r in rows:
            print(json.dumps(r, separators=(",", ":")))

    elif args.cmd == "lookup":
        r = lookup_acceptance(args.user_id, args.domain)
        print(json.dumps(r, indent=2) if r else "not_found")

    else:
        ap.print_help()


if __name__ == "__main__":
    _main()
