"""cell_store — the unified content-addressed cell substrate for cc.

One global store (~/.cc/cc.db, tables cells / recipes / cell_edges, created by
db.py init). Every artifact (prompt, bash output, object, script, model
response) is a CELL, content-addressed by cid = blake3(content)[:32].

One cell, five uses — the cid is simultaneously:
  · the RAG key        (embed + retrieve by cosine)
  · the prompt fragment (compose into the next prompt)
  · the cache ingredient (recipe_cid = hash(upstream content + op + params))
  · the lineage pointer (cell_edges)
  · the dedup identity  (INSERT OR IGNORE on cid PK)

Determinism (temp=0, seed=42 in model_call) makes the transposition cache sound:
identical recipe -> identical output, so a cache hit short-circuits with ZERO
execution. This is the substrate that lets cc act as an outer transformer
around a cloud FFN.

This module owns the cells tables: it opens CC_GLOBAL_DB directly via sqlite3
(matches tool_rag's direct-sqlite pattern — no subprocess-per-op overhead).
db.py exposes low-level CRUD too (used by chain.py's _db_cli persistence path),
but cell_store is the canonical high-level API imported by chain.py / loop.py.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

# ─── config ──────────────────────────────────────────────────────────────
# ALWAYS the GLOBAL db — never read CC_DB (which chain.py repoints to LOCAL).
DB_PATH = Path(os.environ.get("CC_GLOBAL_DB", str(Path.home() / ".cc" / "cc.db")))
OLLAMA_URL = os.environ.get("CC_OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("CC_EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 768
EMBED_SIZE_CAP = 20000   # don't auto-embed cells whose content exceeds this (chars)
RECIPE_HIT_DRY = os.environ.get("CC_RECIPE_DRY", "0") == "1"  # skip cloud on hit


# ─── hashing (blake3 if importable, else blake2b — same width) ────────────
def _hasher():
    try:
        import blake3  # type: ignore
        return "blake3"
    except ImportError:
        return "blake2b"


_HASH = _hasher()


def cell_hash(content: str) -> str:
    """Content address: blake3(content)[:32] (16-byte / 32 hex), blake2b fallback."""
    b = content.encode("utf-8")
    if _HASH == "blake3":
        import blake3  # type: ignore
        return blake3.blake3(b).hexdigest()[:32]
    import hashlib
    return hashlib.blake2b(b, digest_size=16).hexdigest()


def recipe_hash(*parts) -> str:
    """Transposition-table key over NUL-separated parts (upstream content + op + params)."""
    blob = "\0".join(str(p) for p in parts).encode("utf-8")
    if _HASH == "blake3":
        import blake3  # type: ignore
        return blake3.blake3(blob).hexdigest()[:32]
    import hashlib
    return hashlib.blake2b(blob, digest_size=16).hexdigest()


# ─── connection ───────────────────────────────────────────────────────────
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _ensure_tables(c):
    # Idempotent — matches db.py init() so cell_store is usable standalone.
    c.executescript("""
        CREATE TABLE IF NOT EXISTS cells(
          cid TEXT PRIMARY KEY, kind TEXT, content TEXT NOT NULL,
          content_len INTEGER, embedding BLOB, intent TEXT, source TEXT,
          project TEXT, scope_cwd TEXT, agent_uuid TEXT,
          ts TEXT DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_cells_kind ON cells(kind);
        CREATE INDEX IF NOT EXISTS idx_cells_intent ON cells(intent);
        CREATE INDEX IF NOT EXISTS idx_cells_project ON cells(project);
        CREATE TABLE IF NOT EXISTS recipes(
          recipe_cid TEXT PRIMARY KEY, output_cid TEXT NOT NULL,
          kind TEXT, op TEXT, intent TEXT, model TEXT, dt_ms INTEGER,
          hit_count INTEGER DEFAULT 0, last_hit_at TEXT,
          created_at TEXT DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_recipes_output ON recipes(output_cid);
        CREATE INDEX IF NOT EXISTS idx_recipes_intent ON recipes(intent);
        CREATE TABLE IF NOT EXISTS cell_edges(
          src_cid TEXT, dst_cid TEXT, edge_kind TEXT, weight REAL,
          ts TEXT DEFAULT (datetime('now')),
          PRIMARY KEY (src_cid, dst_cid, edge_kind));
    """)
    c.commit()


# ─── embeddings (clone of rag_bridge: nomic via ollama, packed float32) ───
def embed(text: str) -> list[float]:
    if not text or not text.strip():
        return [0.0] * EMBED_DIM
    body = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL + "/api/embeddings", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read().decode("utf-8"))
    emb = j.get("embedding")
    if not isinstance(emb, list) or len(emb) != EMBED_DIM:
        raise RuntimeError(f"unexpected embedding shape: {type(emb)}")
    return emb


def _pack(emb: list[float]) -> bytes:
    try:
        import numpy as np  # type: ignore
        return np.asarray(emb, dtype="float32").tobytes()
    except ImportError:
        return struct.pack(f"<{EMBED_DIM}f", *emb)


def _unpack(blob: bytes) -> list[float]:
    try:
        import numpy as np  # type: ignore
        return np.frombuffer(blob, dtype="float32").tolist()
    except ImportError:
        return list(struct.unpack(f"<{EMBED_DIM}f", blob))


def _cos(a: list[float], b: list[float]) -> float:
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return s / (na * nb)


# ─── cell CRUD ───────────────────────────────────────────────────────────
def add_cell(kind: str, content: str, intent: str = "", source: str = "",
             project: str = "", scope_cwd: str = "", agent_uuid: str = "",
             do_embed: bool = True) -> str:
    """Insert (dedup by cid). Returns the cid. Optionally embeds if small enough."""
    cid = cell_hash(content)
    emb_blob = None
    if do_embed and len(content) <= EMBED_SIZE_CAP:
        try:
            emb_blob = _pack(embed(content))
        except Exception:
            emb_blob = None  # embedder down — store without embedding; queryable later
    with _conn() as c:
        _ensure_tables(c)
        c.execute(
            "INSERT OR IGNORE INTO cells(cid, kind, content, content_len, "
            "embedding, intent, source, project, scope_cwd, agent_uuid) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (cid, kind, content, len(content), emb_blob, intent, source,
             project, scope_cwd, agent_uuid))
        # If the cell already existed but has no embedding and we just made one, fill it.
        if emb_blob is not None:
            c.execute(
                "UPDATE cells SET embedding=? WHERE cid=? AND embedding IS NULL",
                (emb_blob, cid))
        c.commit()
    return cid


def get_cell(cid: str) -> Optional[dict]:
    with _conn() as c:
        _ensure_tables(c)
        r = c.execute(
            "SELECT cid, kind, content, content_len, intent, source, project, "
            "scope_cwd, agent_uuid, ts FROM cells WHERE cid=?", (cid,)).fetchone()
    if not r:
        return None
    return dict(r)


def cell_content(cid: str) -> Optional[str]:
    with _conn() as c:
        _ensure_tables(c)
        r = c.execute("SELECT content FROM cells WHERE cid=?", (cid,)).fetchone()
    return r["content"] if r else None


def list_cells(kind: str = "", intent: str = "", project: str = "",
               limit: int = 50) -> list[dict]:
    q = "SELECT cid, kind, content_len, intent, source, project, ts FROM cells"
    where, args = [], []
    if kind:
        where.append("kind=?"); args.append(kind)
    if intent:
        where.append("intent=?"); args.append(intent)
    if project:
        where.append("project=?"); args.append(project)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        _ensure_tables(c)
        return [dict(r) for r in c.execute(q, args).fetchall()]


# ─── RAG query (linear cosine scan — no sqlite-vec dependency) ───────────
def query(text: str, top_k: int = 5, kind: str = "", intent: str = "",
          project: str = "") -> list[dict]:
    """Embed the query, cosine-scan all embedded cells, return top_k."""
    qv = embed(text)
    with _conn() as c:
        _ensure_tables(c)
        sql = "SELECT cid, kind, content, embedding, intent, source FROM cells WHERE embedding IS NOT NULL"
        where, args = [], []
        if kind:
            where.append("kind=?"); args.append(kind)
        if intent:
            where.append("intent=?"); args.append(intent)
        if project:
            where.append("project=?"); args.append(project)
        if where:
            sql += " AND " + " AND ".join(where)
        rows = c.execute(sql, args).fetchall()
    scored = []
    for r in rows:
        score = _cos(qv, _unpack(r["embedding"]))
        snippet = (r["content"] or "")[:160].replace("\n", " ")
        scored.append({
            "cid": r["cid"], "score": round(score, 4), "kind": r["kind"],
            "intent": r["intent"], "source": r["source"], "snippet": snippet,
        })
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:top_k]


def embed_backfill(limit: int = 200) -> int:
    """Embed cells that lack embeddings (under the size cap). Returns count."""
    n = 0
    with _conn() as c:
        _ensure_tables(c)
        rows = c.execute(
            "SELECT cid, content FROM cells WHERE embedding IS NULL "
            "AND content_len <= ? ORDER BY ts DESC LIMIT ?",
            (EMBED_SIZE_CAP, limit)).fetchall()
    for r in rows:
        try:
            blob = _pack(embed(r["content"]))
        except Exception as e:
            print(f"  skip {r['cid'][:12]}: {e}", file=sys.stderr)
            continue
        with _conn() as c:
            c.execute("UPDATE cells SET embedding=? WHERE cid=?", (blob, r["cid"]))
            c.commit()
        n += 1
    return n


# ─── transposition table (recipes) ───────────────────────────────────────
def recipe_lookup(recipe_cid: str) -> Optional[str]:
    """Return output_cid if the recipe is cached, else None. Does NOT bump hit_count."""
    with _conn() as c:
        _ensure_tables(c)
        r = c.execute(
            "SELECT output_cid FROM recipes WHERE recipe_cid=?",
            (recipe_cid,)).fetchone()
    return r["output_cid"] if r else None


def recipe_store(recipe_cid: str, output_cid: str, kind: str, op: str,
                 intent: str = "", model: str = "", dt_ms: int = 0) -> None:
    with _conn() as c:
        _ensure_tables(c)
        c.execute(
            "INSERT OR REPLACE INTO recipes(recipe_cid, output_cid, kind, op, "
            "intent, model, dt_ms) VALUES(?,?,?,?,?,?,?)",
            (recipe_cid, output_cid, kind, op, intent, model, dt_ms))
        c.commit()


def recipe_hit(recipe_cid: str) -> Optional[str]:
    """Bump hit_count + return output_cid (or None if not cached)."""
    with _conn() as c:
        _ensure_tables(c)
        r = c.execute(
            "SELECT output_cid FROM recipes WHERE recipe_cid=?",
            (recipe_cid,)).fetchone()
        if not r:
            c.commit()
            return None
        c.execute(
            "UPDATE recipes SET hit_count=hit_count+1, last_hit_at=datetime('now') "
            "WHERE recipe_cid=?", (recipe_cid,))
        c.commit()
        return r["output_cid"]


# ─── edges (lineage / attention graph) ──────────────────────────────────
def edge_add(src_cid: str, dst_cid: str, edge_kind: str, weight: float = 1.0) -> None:
    with _conn() as c:
        _ensure_tables(c)
        c.execute(
            "INSERT OR IGNORE INTO cell_edges(src_cid, dst_cid, edge_kind, weight) "
            "VALUES(?,?,?,?)", (src_cid, dst_cid, edge_kind, weight))
        c.commit()


# ─── convenience: cached execute (the heart of "no wasted tokens") ──────
def cached_execute(recipe_cid: str, kind: str, op: str, executor,
                   intent: str = "", model: str = "",
                   project: str = "", scope_cwd: str = "",
                   agent_uuid: str = "") -> tuple[str, str, bool]:
    """Transposition-table wrapper around any cell-producing executor.

    executor: () -> str   (calls the model / runs bash; returns output text)
    Returns (output_cid, output_text, from_cache). On a cache hit the executor
    is NEVER called — zero cloud calls, zero bash runs.
    """
    out = recipe_lookup(recipe_cid)
    if out is not None:
        recipe_hit(recipe_cid)
        return out, cell_content(out) or "", True
    t0 = time.monotonic()
    output_text = executor()
    dt = int((time.monotonic() - t0) * 1000)
    out_kind = "response" if kind == "model" else "bashout"
    out_cid = add_cell(out_kind, output_text, intent=intent, source="chain",
                       project=project, scope_cwd=scope_cwd, agent_uuid=agent_uuid)
    recipe_store(recipe_cid, out_cid, kind, op, intent, model, dt)
    return out_cid, output_text, False


# ─── CLI ──────────────────────────────────────────────────────────────────
def _cli():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        print("\nusage: cell_store.py <cmd> ...\n"
              "  add <kind> <content> [intent] [source] [project]")
        print("  get <cid>")
        print("  list [kind] [intent] [project] [limit]")
        print("  query <text> [top_k] [kind] [intent] [project]")
        print("  embed [limit]            # backfill missing embeddings")
        print("  recipe-hash <part> ...   # print recipe_hash(parts)")
        print("  recipe-get <recipe_cid>")
        print("  recipe-hit <recipe_cid>  # bump hit_count, print output_cid")
        print("  recipe-add <recipe_cid> <output_cid> <kind> <op> [intent] [model] [dt_ms]")
        print("  cell-content <cid>       # print raw content (for cache replay)")
        print("  recipe-stats")
        print("  edge-add <src_cid> <dst_cid> [kind] [weight]")
        return 0
    cmd, rest = args[0], args[1:]
    if cmd == "add":
        cid = add_cell(rest[0], rest[1],
                       rest[2] if len(rest) > 2 else "",
                       rest[3] if len(rest) > 3 else "",
                       rest[4] if len(rest) > 4 else "")
        print(cid)
    elif cmd == "get":
        c = get_cell(rest[0])
        if not c:
            print(f"no cell {rest[0]}", file=sys.stderr); return 1
        for k, v in c.items():
            if k == "content":
                v = (v[:200] + "...") if len(v) > 200 else v
            print(f"  {k}: {v}")
    elif cmd == "list":
        rows = list_cells(rest[0] if rest and rest[0] != "-" else "",
                          rest[1] if len(rest) > 1 and rest[1] != "-" else "",
                          rest[2] if len(rest) > 2 and rest[2] != "-" else "",
                          int(rest[3]) if len(rest) > 3 else 50)
        if not rows:
            print("(no cells)")
        for r in rows:
            print(f"  {r['cid'][:12]}  {r['kind']:10} {r['content_len']:>7}  "
                  f"{r['intent'] or '-':12} {r['source'] or '-':10} {r['ts']}")
    elif cmd == "query":
        hits = query(rest[0],
                     int(rest[1]) if len(rest) > 1 else 5,
                     rest[2] if len(rest) > 2 and rest[2] != "-" else "",
                     rest[3] if len(rest) > 3 and rest[3] != "-" else "",
                     rest[4] if len(rest) > 4 and rest[4] != "-" else "")
        if not hits:
            print("(no embedded cells to query — run `cell_store.py embed`)")
        for h in hits:
            print(f"  {h['score']:.3f}  {h['cid'][:12]}  {h['kind']:10}  {h['snippet']}")
    elif cmd == "embed":
        n = embed_backfill(int(rest[0]) if rest else 200)
        print(f"embedded {n} cells")
    elif cmd == "recipe-get":
        out = recipe_lookup(rest[0])
        print(out or "")
    elif cmd == "recipe-hit":
        out = recipe_hit(rest[0])
        print(out or "")
    elif cmd == "recipe-add":
        # recipe-add <recipe_cid> <output_cid> <kind> <op> [intent] [model] [dt_ms]
        recipe_store(rest[0], rest[1], rest[2], rest[3],
                     rest[4] if len(rest) > 4 else "",
                     rest[5] if len(rest) > 5 else "",
                     int(rest[6]) if len(rest) > 6 else 0)
        print(rest[1])
    elif cmd == "cell-content":
        c = cell_content(rest[0])
        if c is None:
            print(f"no cell {rest[0]}", file=sys.stderr); return 1
        sys.stdout.write(c)
    elif cmd == "recipe-stats":
        with _conn() as c:
            _ensure_tables(c)
            r = c.execute("SELECT COUNT(*), COALESCE(SUM(hit_count),0), "
                          "COALESCE(SUM(CASE WHEN hit_count>0 THEN 1 ELSE 0 END),0) "
                          "FROM recipes").fetchone()
            print(f"recipes: {r[0]}  total_hits={r[1]}  hit_recipes={r[2]}")
            for rcid, ocid, hc, last in c.execute(
                "SELECT recipe_cid, output_cid, hit_count, COALESCE(last_hit_at,'-') "
                "FROM recipes WHERE hit_count>0 ORDER BY hit_count DESC LIMIT 10"):
                print(f"  {rcid[:12]} -> {ocid[:12]}  hits={hc}  {last}")
    elif cmd == "recipe-hash":
        # recipe_hash over all args (NUL-joined) — lets bash callers compute a key
        print(recipe_hash(*rest))
    elif cmd == "edge-add":
        edge_add(rest[0], rest[1],
                 rest[2] if len(rest) > 2 else "produced",
                 float(rest[3]) if len(rest) > 3 else 1.0)
    else:
        print(f"unknown cmd: {cmd}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli())