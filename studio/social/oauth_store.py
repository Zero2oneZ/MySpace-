"""oauth_store.py — OAuth token storage in keys.sqlite.

Table: oauth_tokens
  platform     TEXT PK
  access_token TEXT
  refresh_token TEXT
  expires_at   INTEGER (unix seconds, 0 = no expiry)
  token_type   TEXT (default 'Bearer')
  scope        TEXT (space-separated)
  extra_json   TEXT (platform-specific blob)
  created_at   TEXT ISO
  updated_at   TEXT ISO
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from keys import DB_PATH, now_iso  # keys.py already manages the same DB

OAUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_tokens (
    platform      TEXT PRIMARY KEY,
    access_token  TEXT,
    refresh_token TEXT,
    expires_at    INTEGER NOT NULL DEFAULT 0,
    token_type    TEXT NOT NULL DEFAULT 'Bearer',
    scope         TEXT,
    extra_json    TEXT,
    created_at    TEXT,
    updated_at    TEXT
);
"""


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(OAUTH_SCHEMA)
    return c


def save_token(
    platform: str,
    access_token: str,
    refresh_token: str = "",
    expires_at: int = 0,
    token_type: str = "Bearer",
    scope: str = "",
    extra: Optional[dict] = None,
) -> None:
    ts = now_iso()
    with _db() as c:
        c.execute(
            "INSERT INTO oauth_tokens (platform, access_token, refresh_token, expires_at, "
            "token_type, scope, extra_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(platform) DO UPDATE SET "
            "access_token=excluded.access_token, refresh_token=excluded.refresh_token, "
            "expires_at=excluded.expires_at, token_type=excluded.token_type, "
            "scope=excluded.scope, extra_json=excluded.extra_json, updated_at=excluded.updated_at",
            (platform, access_token, refresh_token, expires_at, token_type, scope,
             json.dumps(extra) if extra else "{}", ts, ts),
        )


def get_token(platform: str) -> Optional[dict]:
    with _db() as c:
        row = c.execute(
            "SELECT access_token, refresh_token, expires_at, token_type, scope, extra_json, updated_at "
            "FROM oauth_tokens WHERE platform=?", (platform,),
        ).fetchone()
    if row is None:
        return None
    return {
        "platform": platform,
        "access_token": row[0],
        "refresh_token": row[1],
        "expires_at": row[2],
        "token_type": row[3],
        "scope": row[4],
        "extra": json.loads(row[5]) if row[5] else {},
        "updated_at": row[6],
        "is_expired": row[2] > 0 and int(time.time()) >= row[2],
    }


def delete_token(platform: str) -> bool:
    with _db() as c:
        cur = c.execute("DELETE FROM oauth_tokens WHERE platform=?", (platform,))
        return cur.rowcount > 0


def list_tokens() -> list[dict]:
    with _db() as c:
        rows = c.execute(
            "SELECT platform, access_token, refresh_token, expires_at, token_type, scope, updated_at "
            "FROM oauth_tokens ORDER BY updated_at DESC",
        ).fetchall()
    now = int(time.time())
    return [
        {
            "platform": r[0],
            "access_token_masked": r[1][:4] + "..." + r[1][-4:] if r[1] and len(r[1]) > 8 else "",
            "has_refresh": bool(r[2]),
            "expires_at": r[3],
            "is_expired": r[3] > 0 and now >= r[3],
            "token_type": r[4],
            "scope": r[5],
            "updated_at": r[6],
        }
        for r in rows
    ]


def status() -> dict:
    return {
        "tokens": list_tokens(),
        "count": len(list_tokens()),
        "ts": now_iso(),
    }
