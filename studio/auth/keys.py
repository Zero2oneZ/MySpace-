"""keys.py — salted-token registry for friend API access.

What this is:
    A registry that issues opaque tokens to friends so they can use a
    Tom-owned API key (Claude guest pass, Pinterest API, client API)
    without ever seeing the key itself. Every call gets logged with
    bytes-in / bytes-out / cost so usage can be capped.

Token format:
    mspc_<kind>_<token-id>_<hmac>
    e.g.  mspc_claude_a1b2c3d4_4e5f6a7b8c9d…

    - <kind>     = "claude" | "pinterest" | "client"   (3 chars min)
    - <token-id> = 8 hex chars (uuid4 prefix; index into registry)
    - <hmac>     = HMAC_SHA256(master_secret, kind || token-id || user || salt)
                   truncated to 32 hex chars.

    The friend never sees the master_secret, the upstream API key, or
    other friends' tokens. The proxy reverses the lookup by token-id +
    HMAC verification, then forwards using the real key from .env.

Master secret:
    Read from $MYSPACE_KEY_MASTER (env var) or studio/auth/.master_secret
    (a 32-byte random file created on first run, mode 600). If you ever
    rotate the master, all distributed tokens are invalidated.

Storage:
    SQLite at studio/auth/keys.sqlite. Two tables:
      tokens(token_id PK, user, kind, salt, hmac, created, last_used,
             active, calls, tokens_in, tokens_out, cost_estimate)
      usage_log(id PK, token_id, ts, endpoint, tokens_in, tokens_out,
                cost, status)

Pricing (for cost_estimate, rough numbers — adjust as needed):
    Per the env (claude_guest), assume Claude Sonnet 4.6-ish:
      $3 / 1M input tokens
      $15 / 1M output tokens
    Pinterest + client API costs aren't metered (no token notion); only
    call counts are tracked.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get(
    "MYSPACE_KEYS_DB", str(HERE / "keys.sqlite")))
MASTER_FILE = HERE / ".master_secret"
ENV_PATH = Path(os.environ.get(
    "MYSPACE_ENV_PATH", str(HERE.parent.parent / ".env")))

# Pricing in USD per token.
CLAUDE_INPUT_PRICE_PER_TOKEN  = 3.0  / 1_000_000
CLAUDE_OUTPUT_PRICE_PER_TOKEN = 15.0 / 1_000_000

KINDS = ("claude", "pinterest", "client")


# ----------------------------------------------------------------------------
# .env loader (minimal, no python-dotenv dep)
# ----------------------------------------------------------------------------
def load_env() -> dict:
    """Parse the project .env into a dict. Missing file → {}."""
    if not ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for ln in ENV_PATH.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        out[k.strip()] = v.strip().strip("'\"")
    return out


def upstream_key(kind: str) -> Optional[str]:
    """Look up the real (upstream) API key for a kind from .env."""
    env = load_env()
    return {
        "claude":    env.get("claude_guest") or env.get("CLAUDE_GUEST"),
        "pinterest": env.get("pintrest_api") or env.get("PINTEREST_API")
                     or env.get("PINTREST_API"),
        "client":    env.get("client_api")   or env.get("CLIENT_API"),
    }.get(kind)


# ----------------------------------------------------------------------------
# Master secret (file-backed, auto-created)
# ----------------------------------------------------------------------------
def master_secret() -> bytes:
    env = os.environ.get("MYSPACE_KEY_MASTER")
    if env:
        return env.encode("utf-8")
    if not MASTER_FILE.exists():
        MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
        MASTER_FILE.write_bytes(secrets.token_bytes(32))
        try:
            os.chmod(MASTER_FILE, 0o600)
        except OSError:
            pass
    return MASTER_FILE.read_bytes()


# ----------------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    token_id        TEXT PRIMARY KEY,
    user            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    salt            TEXT NOT NULL,
    hmac            TEXT NOT NULL,
    created         TEXT NOT NULL,
    last_used       TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    calls           INTEGER NOT NULL DEFAULT 0,
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    cost_estimate   REAL NOT NULL DEFAULT 0.0
);
CREATE TABLE IF NOT EXISTS usage_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id        TEXT NOT NULL,
    ts              TEXT NOT NULL,
    endpoint        TEXT,
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    cost            REAL NOT NULL DEFAULT 0.0,
    status          INTEGER,
    FOREIGN KEY (token_id) REFERENCES tokens(token_id)
);
CREATE INDEX IF NOT EXISTS idx_log_ts        ON usage_log(ts);
CREATE INDEX IF NOT EXISTS idx_log_token     ON usage_log(token_id);
CREATE INDEX IF NOT EXISTS idx_tokens_user   ON tokens(user);
CREATE INDEX IF NOT EXISTS idx_tokens_kind   ON tokens(kind);
"""


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    return c


# ----------------------------------------------------------------------------
# Token math
# ----------------------------------------------------------------------------
def _compute_hmac(kind: str, token_id: str, user: str, salt: str) -> str:
    payload = f"{kind}|{token_id}|{user}|{salt}".encode("utf-8")
    return hmac.new(master_secret(), payload, hashlib.sha256).hexdigest()[:32]


def _format_token(kind: str, token_id: str, h: str) -> str:
    return f"mspc_{kind}_{token_id}_{h}"


def _parse_token(token: str) -> Optional[tuple]:
    """token → (kind, token_id, hmac) or None on invalid format."""
    if not token.startswith("mspc_"):
        return None
    parts = token.split("_")
    # mspc + kind + token_id + hmac → 4 parts
    if len(parts) != 4:
        return None
    _, kind, token_id, h = parts
    if kind not in KINDS:
        return None
    if not (token_id and h):
        return None
    return kind, token_id, h


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
@dataclass
class TokenRow:
    token_id: str
    user: str
    kind: str
    active: bool
    created: str
    last_used: Optional[str]
    calls: int
    tokens_in: int
    tokens_out: int
    cost_estimate: float


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def distribute_token(user: str, kind: str) -> str:
    """Create + register a new token. Returns the opaque token string
    that should be handed to the friend ONCE (not stored anywhere else)."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind} (allowed: {KINDS})")
    token_id = uuid.uuid4().hex[:8]
    salt = secrets.token_hex(16)
    h = _compute_hmac(kind, token_id, user, salt)
    with db() as c:
        c.execute(
            "INSERT INTO tokens (token_id, user, kind, salt, hmac, created) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (token_id, user, kind, salt, h, now_iso()),
        )
    return _format_token(kind, token_id, h)


def verify_token(token: str) -> Optional[TokenRow]:
    """Returns the TokenRow if the token is valid + active, else None."""
    parsed = _parse_token(token)
    if parsed is None:
        return None
    kind, token_id, supplied_h = parsed
    with db() as c:
        row = c.execute(
            "SELECT token_id, user, kind, salt, hmac, active, created, "
            "       last_used, calls, tokens_in, tokens_out, cost_estimate "
            "FROM tokens WHERE token_id = ?", (token_id,),
        ).fetchone()
    if row is None:
        return None
    (tid, user, kind_db, salt, h, active, created,
     last_used, calls, tin, tout, cost) = row
    if kind_db != kind:
        return None
    if not active:
        return None
    # Recompute HMAC + constant-time compare
    expected = _compute_hmac(kind, tid, user, salt)
    if not hmac.compare_digest(expected, h):
        return None
    if not hmac.compare_digest(supplied_h, h):
        return None
    return TokenRow(
        token_id=tid, user=user, kind=kind,
        active=bool(active), created=created, last_used=last_used,
        calls=calls, tokens_in=tin, tokens_out=tout, cost_estimate=cost,
    )


def log_usage(
    token_id: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    endpoint: Optional[str] = None,
    status: Optional[int] = None,
) -> float:
    """Record a single API call. Returns the cost delta added."""
    cost = (
        tokens_in  * CLAUDE_INPUT_PRICE_PER_TOKEN
      + tokens_out * CLAUDE_OUTPUT_PRICE_PER_TOKEN
    )
    ts = now_iso()
    with db() as c:
        c.execute(
            "INSERT INTO usage_log (token_id, ts, endpoint, tokens_in, "
            "                      tokens_out, cost, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token_id, ts, endpoint, tokens_in, tokens_out, cost, status),
        )
        c.execute(
            "UPDATE tokens SET last_used=?, calls=calls+1, "
            "tokens_in=tokens_in+?, tokens_out=tokens_out+?, "
            "cost_estimate=cost_estimate+? WHERE token_id=?",
            (ts, tokens_in, tokens_out, cost, token_id),
        )
    return cost


def revoke_token(token_id: str) -> bool:
    with db() as c:
        cur = c.execute(
            "UPDATE tokens SET active=0 WHERE token_id=? AND active=1",
            (token_id,),
        )
        return cur.rowcount > 0


def list_tokens(include_inactive: bool = False) -> list[TokenRow]:
    where = "" if include_inactive else "WHERE active=1"
    with db() as c:
        rows = c.execute(
            f"SELECT token_id, user, kind, active, created, last_used, "
            f"       calls, tokens_in, tokens_out, cost_estimate "
            f"FROM tokens {where} ORDER BY created",
        ).fetchall()
    return [TokenRow(*r[:3], bool(r[3]), *r[4:]) for r in rows]


def status_summary() -> dict:
    with db() as c:
        total = c.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
        active = c.execute("SELECT COUNT(*) FROM tokens WHERE active=1").fetchone()[0]
        calls = c.execute("SELECT COALESCE(SUM(calls),0) FROM tokens").fetchone()[0]
        cost = c.execute("SELECT COALESCE(SUM(cost_estimate),0) FROM tokens").fetchone()[0]
        today = time.strftime("%Y-%m-%d", time.gmtime())
        calls_today = c.execute(
            "SELECT COUNT(*) FROM usage_log WHERE ts LIKE ?", (today + "%",),
        ).fetchone()[0]
        cost_today = c.execute(
            "SELECT COALESCE(SUM(cost),0) FROM usage_log WHERE ts LIKE ?", (today + "%",),
        ).fetchone()[0]
    return {
        "tokens_total":  total,
        "tokens_active": active,
        "calls_total":   calls,
        "calls_today":   calls_today,
        "cost_total":    cost,
        "cost_today":    cost_today,
    }


# ----------------------------------------------------------------------------
# CLI surface — `python keys.py distribute Jamie claude`
# ----------------------------------------------------------------------------
def _cli():
    import argparse, json, sys
    ap = argparse.ArgumentParser(prog="keys.py")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p_dist = sp.add_parser("distribute", help="issue a new token")
    p_dist.add_argument("user")
    p_dist.add_argument("kind", choices=KINDS)

    sp.add_parser("list", help="list active tokens")
    sp_all = sp.add_parser("list-all", help="list all tokens incl. revoked")  # noqa: F841

    p_rev = sp.add_parser("revoke", help="deactivate a token by token-id")
    p_rev.add_argument("token_id")

    p_ver = sp.add_parser("verify", help="dry-run verify a token string")
    p_ver.add_argument("token")

    sp.add_parser("status", help="one-line counts + cost")

    p_log = sp.add_parser("log", help="record a usage event")
    p_log.add_argument("token_id"); p_log.add_argument("tokens_in", type=int)
    p_log.add_argument("tokens_out", type=int)
    p_log.add_argument("--endpoint", default=None)

    args = ap.parse_args()

    if args.cmd == "distribute":
        tok = distribute_token(args.user, args.kind)
        print(tok)
        print("# share this token with the friend ONCE — it isn't recoverable.",
              file=sys.stderr)
        return 0

    if args.cmd in ("list", "list-all"):
        include = (args.cmd == "list-all")
        rows = list_tokens(include_inactive=include)
        print(f"{'id':<10} {'user':<12} {'kind':<10} {'A':<2} "
              f"{'calls':<7} {'tok_in':<8} {'tok_out':<8} {'cost':<8}")
        print("-" * 80)
        for r in rows:
            print(f"{r.token_id:<10} {r.user:<12} {r.kind:<10} "
                  f"{'Y' if r.active else 'N':<2} {r.calls:<7} "
                  f"{r.tokens_in:<8} {r.tokens_out:<8} ${r.cost_estimate:<7.4f}")
        return 0

    if args.cmd == "revoke":
        ok = revoke_token(args.token_id)
        print("revoked" if ok else "no such active token")
        return 0 if ok else 1

    if args.cmd == "verify":
        row = verify_token(args.token)
        if row is None:
            print("invalid token"); return 1
        print(json.dumps(row.__dict__, default=str, indent=2))
        return 0

    if args.cmd == "status":
        s = status_summary()
        print(f"tokens: {s['tokens_active']} active / {s['tokens_total']} total")
        print(f"calls:  {s['calls_today']} today / {s['calls_total']} total")
        print(f"cost:   ${s['cost_today']:.4f} today / ${s['cost_total']:.4f} total")
        return 0

    if args.cmd == "log":
        c = log_usage(args.token_id, args.tokens_in, args.tokens_out,
                      endpoint=args.endpoint)
        print(f"logged: cost+=${c:.6f}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
