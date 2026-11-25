"""pieces_index.py — searchable index of pre-computed asset pieces.

Every pass output (mask, depth, caption, etc.) is registered here so
later UI surfaces (Pinterest search, library browser) can answer
"do we already have a mask for an image labeled 'red dress'?" without
re-running inference.

Schema:
    pieces(
        piece_id      PK (sha8 of asset_sha + pass_id),
        asset_sha     content hash of the source asset,
        asset_path    relative path under paths.MEDIA_ROOT,
        pass_id       which pass produced this piece,
        path          relative path to the piece file (or NULL if inline),
        value         text/numeric inline value (caption text, etc.),
        kind          output kind (MASK / DEPTH / TXT / EMB / SVG / ...),
        label         human-readable label (filename slug, caption snippet)
        description   longer description (caption text, etc.)
        tags          JSON array of tag strings
        created       iso timestamp
        last_used     iso timestamp
        used_count    int — usage tracker for cache eviction policies
    )

Search is plain SQL LIKE over (label, description, tags-JSON) ranked
by recency + used_count. No FTS extension needed.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths   # noqa: E402

DB_PATH = paths.DAG_CACHE_DIR / "pieces.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pieces (
    piece_id      TEXT PRIMARY KEY,
    asset_sha     TEXT NOT NULL,
    asset_path    TEXT NOT NULL,
    pass_id       TEXT NOT NULL,
    path          TEXT,
    value         TEXT,
    kind          TEXT,
    label         TEXT,
    description   TEXT,
    tags          TEXT,
    created       TEXT NOT NULL,
    last_used     TEXT,
    used_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_p_asset      ON pieces(asset_sha);
CREATE INDEX IF NOT EXISTS idx_p_pass       ON pieces(pass_id);
CREATE INDEX IF NOT EXISTS idx_p_kind       ON pieces(kind);
CREATE INDEX IF NOT EXISTS idx_p_label      ON pieces(label);
"""


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    return c


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _piece_id(asset_sha: str, pass_id: str) -> str:
    return hashlib.sha256(f"{asset_sha}:{pass_id}".encode()).hexdigest()[:16]


def _rel_to_media(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(paths.MEDIA_ROOT))
    except ValueError:
        return str(p)


def upsert(
    asset_sha: str,
    asset_path: str | Path,
    pass_id: str,
    *,
    path: Optional[str | Path] = None,
    value: Optional[str] = None,
    kind: Optional[str] = None,
    label: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> str:
    """Register or update a piece. Returns the piece_id."""
    pid = _piece_id(asset_sha, pass_id)
    asset_rel = _rel_to_media(asset_path)
    path_rel = _rel_to_media(path) if path else None
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    ts = now_iso()
    with _db() as c:
        c.execute("""
            INSERT INTO pieces
                (piece_id, asset_sha, asset_path, pass_id, path, value, kind,
                 label, description, tags, created, last_used, used_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)
            ON CONFLICT(piece_id) DO UPDATE SET
                asset_path = excluded.asset_path,
                path = excluded.path,
                value = excluded.value,
                kind = excluded.kind,
                label = excluded.label,
                description = excluded.description,
                tags = excluded.tags
        """, (pid, asset_sha, asset_rel, pass_id, path_rel, value, kind,
              label, description, tags_json, ts))
    return pid


def by_asset(asset_sha: str) -> list[dict]:
    with _db() as c:
        rows = c.execute(
            "SELECT piece_id, pass_id, path, value, kind, label, description, tags "
            "FROM pieces WHERE asset_sha=?", (asset_sha,),
        ).fetchall()
    return [{
        "piece_id": r[0], "pass_id": r[1], "path": r[2], "value": r[3],
        "kind": r[4], "label": r[5], "description": r[6],
        "tags": json.loads(r[7] or "[]"),
    } for r in rows]


def search(query: str, kind: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Substring match on label + description + tags JSON. Ranked by
    used_count DESC, last_used DESC."""
    q = f"%{query.lower()}%"
    where = "(LOWER(label) LIKE ? OR LOWER(description) LIKE ? OR LOWER(tags) LIKE ?)"
    params: list = [q, q, q]
    if kind:
        where += " AND kind = ?"
        params.append(kind)
    with _db() as c:
        rows = c.execute(
            f"SELECT piece_id, asset_sha, asset_path, pass_id, path, value, "
            f"       kind, label, description, tags, last_used, used_count "
            f"FROM pieces WHERE {where} "
            f"ORDER BY used_count DESC, last_used DESC NULLS LAST, created DESC "
            f"LIMIT ?", (*params, limit),
        ).fetchall()
    return [{
        "piece_id":    r[0], "asset_sha":  r[1], "asset_path": r[2],
        "pass_id":     r[3], "path":       r[4], "value":      r[5],
        "kind":        r[6], "label":      r[7], "description":r[8],
        "tags":        json.loads(r[9] or "[]"),
        "last_used":   r[10], "used_count":r[11],
    } for r in rows]


def mark_used(piece_id: str) -> None:
    with _db() as c:
        c.execute(
            "UPDATE pieces SET used_count = used_count + 1, last_used=? "
            "WHERE piece_id=?", (now_iso(), piece_id),
        )


def stats() -> dict:
    with _db() as c:
        total = c.execute("SELECT COUNT(*) FROM pieces").fetchone()[0]
        by_pass = dict(c.execute(
            "SELECT pass_id, COUNT(*) FROM pieces GROUP BY pass_id"
        ).fetchall())
        by_kind = dict(c.execute(
            "SELECT kind, COUNT(*) FROM pieces GROUP BY kind"
        ).fetchall())
        n_assets = c.execute(
            "SELECT COUNT(DISTINCT asset_sha) FROM pieces"
        ).fetchone()[0]
    return {"total": total, "n_assets": n_assets,
            "by_pass": by_pass, "by_kind": by_kind}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("stats")
    p_s = sp.add_parser("search"); p_s.add_argument("query")
    p_s.add_argument("--kind", default=None); p_s.add_argument("--limit", type=int, default=20)
    p_b = sp.add_parser("by-asset"); p_b.add_argument("sha")
    args = ap.parse_args()

    if args.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif args.cmd == "search":
        print(json.dumps(search(args.query, args.kind, args.limit), indent=2))
    elif args.cmd == "by-asset":
        print(json.dumps(by_asset(args.sha), indent=2))
