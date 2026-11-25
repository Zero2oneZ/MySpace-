#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        social_graph_persistence
# role:        SUBSTRATE · SOCIAL_GRAPH_STORE
# tier:        L0
# substrate:   SQLite-backed directed multigraph of Facebook-derived player
#              relationships + append-only JSONL audit trail.
# engine:      sqlite3 (stdlib) + JSONL audit + crystal-chain anchors
# storage:     ~/.cc/social_graph.sqlite       (mode 600 on first create)
#              ~/.cc/social_graph_audit.jsonl  (mode 600 on first create)
#              override DB path via env MSPC_SOCIAL_GRAPH_DB
# card:        studio/assets/_agents/agent_defs/
#              vm_mspc_001.agents.agent_defs.social_graph_persistence.active.json
# ----------------------------------------------------------------------------
# ROUTING CONNECTIONS
# ----------------------------------------------------------------------------
# inbound:
#   - core/lib/facebook_friends_graph (parallel agent — Graph API + fb_instant
#     capture pipeline, calls upsert_player / upsert_edge)
#   - studio/dapp /api/social_graph (HTTP read endpoint — get_player,
#     get_friends, export_for_planet_map)
#   - godot planet_map_scene (fetches export_for_planet_map JSON for orbital
#     friend visualization)
# outbound:
#   - core/lib/inference_logger.InferenceLogger().log(tier='social_graph', ...)
#     (each upsert anchors a crystal hash; failures swallowed silently)
# substrate touch:
#   - reads:  the sqlite DB at MSPC_SOCIAL_GRAPH_DB or ~/.cc/social_graph.sqlite
#   - writes: same sqlite DB + audit JSONL + crystal-chain anchor row
# ============================================================================
"""social_graph_persistence.py — SQLite + JSONL audit store for player friendships.

A directed multigraph:
  - nodes = players (FB-derived identity, optional lat/lon/country)
  - edges = friendships  (source_player → target_player, with source_via tag)

Multi-edge because (A → B via graph_api) and (A → B via fb_instant) are
distinct provenance facts. Symmetric friendships are typical, so upsert_edge
defaults bidirectional=True and writes both arcs.

Every mutation:
  1. writes the sqlite row
  2. appends one JSONL audit row
  3. anchors a crystal_id via inference_logger (try/except — never blocks)

Stdlib only. No geopy, no networkx, no third-party deps.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -- paths --------------------------------------------------------------------

CC_HOME = Path(os.environ.get("CC_HOME", str(Path.home() / ".cc")))
DEFAULT_DB_PATH = CC_HOME / "social_graph.sqlite"
DEFAULT_AUDIT_PATH = CC_HOME / "social_graph_audit.jsonl"


def _db_path() -> Path:
    return Path(os.environ.get("MSPC_SOCIAL_GRAPH_DB", str(DEFAULT_DB_PATH)))


def _audit_path() -> Path:
    """Audit trail lives next to the DB; if the DB path was overridden, drop
    the audit file alongside it so smoke tests stay self-contained."""
    db = _db_path()
    if db == DEFAULT_DB_PATH:
        return DEFAULT_AUDIT_PATH
    # Override path: shadow audit beside the DB
    return db.parent / (db.stem + "_audit.jsonl")


# -- schema -------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    player_id TEXT PRIMARY KEY,
    name TEXT,
    picture_url TEXT,
    lat REAL,
    lon REAL,
    country_code TEXT,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    crystal_id TEXT
);

CREATE TABLE IF NOT EXISTS friend_edges (
    source_player TEXT NOT NULL,
    target_player TEXT NOT NULL,
    source_via TEXT NOT NULL,
    signed INTEGER NOT NULL,
    captured_at INTEGER NOT NULL,
    crystal_id TEXT,
    PRIMARY KEY (source_player, target_player, source_via)
);

CREATE INDEX IF NOT EXISTS idx_edges_target ON friend_edges (target_player);
CREATE INDEX IF NOT EXISTS idx_players_country ON players (country_code);
"""


def _connect() -> sqlite3.Connection:
    """Open the social-graph DB, creating it (mode 600) if absent."""
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    fresh = not db.exists()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    if fresh:
        try:
            os.chmod(db, 0o600)
        except OSError:
            pass
    return conn


# -- audit log ----------------------------------------------------------------

def _audit(op: str, player_id_or_pair: Any, crystal_id: str, source_via: str = "") -> None:
    """Append one JSONL audit row. Best-effort; never raises."""
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not path.exists()
        row = {
            "ts": int(time.time()),
            "op": op,
            "player_id_or_pair": player_id_or_pair,
            "crystal_id": crystal_id,
            "source_via": source_via,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")))
            f.write("\n")
        if fresh:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    except Exception:
        pass


# -- crystal anchor -----------------------------------------------------------

def _anchor_crystal(op: str, payload: str) -> str:
    """Anchor an upsert via inference_logger. Returns the crystal_id; on
    failure returns a local blake2b fallback so callers always have an id."""
    try:
        # Lazy import — keeps stdlib-only smoke tests possible if logger broken
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import inference_logger  # type: ignore
        logger = inference_logger.InferenceLogger()
        cid = logger.log(
            original_prompt=payload,
            enhanced_prompt=payload,
            output_text=f"social_graph::{op}::{payload}",
            tier="social_graph",
            model="social_graph",
            scope=f"upsert_{op}",
            tokens_in=0,
            tokens_out=0,
        )
        if cid:
            return cid
    except Exception:
        pass
    # Fallback: deterministic local hash so audit row always has a crystal_id
    return hashlib.blake2b(f"{op}::{payload}::{time.time_ns()}".encode("utf-8")).hexdigest()


# -- haversine ----------------------------------------------------------------

_EARTH_RADIUS_KM = 6371.0088


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Pure stdlib math."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    return _EARTH_RADIUS_KM * c


# -- country centroids (ISO 3166-1 alpha-2 -> (lat, lon)) ---------------------
# Approximate population-weighted centroids for the most common countries.
# Used as a fallback when a player has a country_code but no explicit lat/lon.

COUNTRY_CENTROIDS: Dict[str, Tuple[float, float]] = {
    "US": (39.83, -98.58),  "CA": (56.13, -106.35), "MX": (23.63, -102.55),
    "BR": (-14.24, -51.93), "AR": (-38.42, -63.62), "CL": (-35.68, -71.54),
    "CO": (4.57, -74.30),   "PE": (-9.19, -75.02),  "VE": (6.42, -66.59),
    "GB": (55.38, -3.44),   "IE": (53.41, -8.24),   "FR": (46.23, 2.21),
    "DE": (51.17, 10.45),   "IT": (41.87, 12.57),   "ES": (40.46, -3.75),
    "PT": (39.40, -8.22),   "NL": (52.13, 5.29),    "BE": (50.50, 4.47),
    "CH": (46.82, 8.23),    "AT": (47.52, 14.55),   "SE": (60.13, 18.64),
    "NO": (60.47, 8.47),    "FI": (61.92, 25.75),   "DK": (56.26, 9.50),
    "PL": (51.92, 19.13),   "CZ": (49.82, 15.47),   "SK": (48.67, 19.70),
    "HU": (47.16, 19.50),   "RO": (45.94, 24.97),   "BG": (42.73, 25.49),
    "GR": (39.07, 21.82),   "TR": (38.96, 35.24),   "RU": (61.52, 105.32),
    "UA": (48.38, 31.17),   "BY": (53.71, 27.95),   "EE": (58.60, 25.01),
    "LV": (56.88, 24.60),   "LT": (55.17, 23.88),
    "CN": (35.86, 104.20),  "JP": (36.20, 138.25),  "KR": (35.91, 127.77),
    "TW": (23.70, 121.00),  "HK": (22.32, 114.17),  "SG": (1.35, 103.82),
    "MY": (4.21, 101.98),   "TH": (15.87, 100.99),  "VN": (14.06, 108.28),
    "PH": (12.88, 121.77),  "ID": (-0.79, 113.92),  "IN": (20.59, 78.96),
    "PK": (30.38, 69.35),   "BD": (23.68, 90.36),   "LK": (7.87, 80.77),
    "AU": (-25.27, 133.78), "NZ": (-40.90, 174.89),
    "ZA": (-30.56, 22.94),  "EG": (26.82, 30.80),   "MA": (31.79, -7.09),
    "DZ": (28.03, 1.66),    "TN": (33.89, 9.54),    "NG": (9.08, 8.67),
    "KE": (-0.02, 37.91),   "GH": (7.95, -1.02),    "ET": (9.15, 40.49),
    "IL": (31.05, 34.85),   "AE": (23.42, 53.85),   "SA": (23.89, 45.08),
    "IR": (32.43, 53.69),   "IQ": (33.22, 43.68),   "JO": (30.59, 36.24),
    "LB": (33.85, 35.86),   "QA": (25.35, 51.18),   "KW": (29.31, 47.48),
    "CR": (9.75, -83.75),   "GT": (15.78, -90.23),  "DO": (18.74, -70.16),
    "CU": (21.52, -77.78),  "PA": (8.54, -80.78),   "UY": (-32.52, -55.77),
    "BO": (-16.29, -63.59), "EC": (-1.83, -78.18),  "PY": (-23.44, -58.44),
    "IS": (64.96, -19.02),  "MT": (35.94, 14.38),   "CY": (35.13, 33.43),
    "LU": (49.82, 6.13),    "RS": (44.02, 21.01),   "HR": (45.10, 15.20),
    "SI": (46.15, 14.99),   "BA": (43.92, 17.68),
}


def _country_latlon(code: str) -> Optional[Tuple[float, float]]:
    if not code:
        return None
    return COUNTRY_CENTROIDS.get(code.upper())


# -- public API ---------------------------------------------------------------

def upsert_player(
    player_id: str,
    name: str = "",
    picture_url: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    country_code: str = "",
) -> str:
    """Insert or update a player row. Returns crystal_id anchoring this upsert."""
    if not player_id:
        raise ValueError("player_id required")
    now = int(time.time())
    crystal_id = _anchor_crystal("player", player_id)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT first_seen FROM players WHERE player_id = ?", (player_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                """INSERT INTO players
                   (player_id, name, picture_url, lat, lon, country_code,
                    first_seen, last_seen, crystal_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (player_id, name, picture_url, lat, lon,
                 (country_code or "").upper(), now, now, crystal_id),
            )
        else:
            # Update last_seen + any provided fields (non-empty / non-None wins)
            cur.execute(
                """UPDATE players SET
                       name         = COALESCE(NULLIF(?, ''), name),
                       picture_url  = COALESCE(NULLIF(?, ''), picture_url),
                       lat          = COALESCE(?, lat),
                       lon          = COALESCE(?, lon),
                       country_code = COALESCE(NULLIF(?, ''), country_code),
                       last_seen    = ?,
                       crystal_id   = ?
                   WHERE player_id = ?""",
                (name, picture_url, lat, lon, (country_code or "").upper(),
                 now, crystal_id, player_id),
            )
        conn.commit()
    finally:
        conn.close()
    _audit("upsert_player", player_id, crystal_id, "")
    return crystal_id


def upsert_edge(
    source_player: str,
    target_player: str,
    source_via: str = "graph_api",
    signed: bool = False,
    bidirectional: bool = True,
) -> str:
    """Add a friendship arc. Friendships are typically symmetric, so
    bidirectional=True writes both (a,b,via) and (b,a,via)."""
    if not source_player or not target_player:
        raise ValueError("source_player and target_player required")
    if source_via not in ("graph_api", "fb_instant", "manual"):
        raise ValueError(f"invalid source_via: {source_via!r}")
    if source_player == target_player:
        raise ValueError("self-loop edges are not allowed")
    now = int(time.time())
    pair_label = f"{source_player}<->{target_player}" if bidirectional else f"{source_player}->{target_player}"
    crystal_id = _anchor_crystal("edge", pair_label)
    conn = _connect()
    try:
        cur = conn.cursor()
        # Ensure both endpoint rows exist (last_seen bump only — no metadata)
        for pid in (source_player, target_player):
            cur.execute("SELECT 1 FROM players WHERE player_id = ?", (pid,))
            if cur.fetchone() is None:
                cur.execute(
                    """INSERT INTO players
                       (player_id, name, picture_url, lat, lon, country_code,
                        first_seen, last_seen, crystal_id)
                       VALUES (?, '', '', NULL, NULL, '', ?, ?, ?)""",
                    (pid, now, now, crystal_id),
                )
            else:
                cur.execute(
                    "UPDATE players SET last_seen = ? WHERE player_id = ?",
                    (now, pid),
                )
        pairs = [(source_player, target_player)]
        if bidirectional:
            pairs.append((target_player, source_player))
        for src, tgt in pairs:
            cur.execute(
                """INSERT INTO friend_edges
                   (source_player, target_player, source_via, signed,
                    captured_at, crystal_id)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_player, target_player, source_via) DO UPDATE SET
                       signed       = excluded.signed,
                       captured_at  = excluded.captured_at,
                       crystal_id   = excluded.crystal_id""",
                (src, tgt, source_via, 1 if signed else 0, now, crystal_id),
            )
        conn.commit()
    finally:
        conn.close()
    _audit("upsert_edge", pair_label, crystal_id, source_via)
    return crystal_id


def get_player(player_id: str) -> Optional[Dict[str, Any]]:
    """Fetch one player row as a dict, or None."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM players WHERE player_id = ?", (player_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_friends(player_id: str) -> List[Dict[str, Any]]:
    """Direct friends of `player_id` (outgoing arcs). Deduplicated by friend
    player_id across multiple source_via rows."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT p.*,
                      GROUP_CONCAT(e.source_via) AS sources,
                      MAX(e.signed)              AS any_signed,
                      MAX(e.captured_at)         AS last_captured_at
               FROM friend_edges e
               JOIN players p ON p.player_id = e.target_player
               WHERE e.source_player = ?
               GROUP BY p.player_id
               ORDER BY last_captured_at DESC""",
            (player_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_friend_of_friend(player_id: str, depth: int = 2, limit: int = 200) -> List[Dict[str, Any]]:
    """BFS out to `depth` hops, excluding the origin and direct friends.
    Returns deduplicated player rows with a `hops` field."""
    if depth < 1:
        return []
    conn = _connect()
    try:
        cur = conn.cursor()
        visited: Dict[str, int] = {player_id: 0}
        frontier: List[str] = [player_id]
        out: List[Tuple[str, int]] = []
        for current_depth in range(1, depth + 1):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            cur.execute(
                f"""SELECT DISTINCT source_player, target_player
                    FROM friend_edges
                    WHERE source_player IN ({placeholders})""",
                tuple(frontier),
            )
            next_frontier: List[str] = []
            for row in cur.fetchall():
                tgt = row["target_player"]
                if tgt in visited:
                    continue
                visited[tgt] = current_depth
                next_frontier.append(tgt)
                if current_depth > 1:  # exclude direct friends (depth==1)
                    out.append((tgt, current_depth))
                    if len(out) >= limit:
                        break
            if len(out) >= limit:
                break
            frontier = next_frontier
        if not out:
            return []
        ids = [pid for pid, _ in out]
        placeholders = ",".join("?" for _ in ids)
        cur.execute(
            f"SELECT * FROM players WHERE player_id IN ({placeholders})",
            tuple(ids),
        )
        rows_by_id = {r["player_id"]: dict(r) for r in cur.fetchall()}
        result: List[Dict[str, Any]] = []
        for pid, hop in out:
            row = rows_by_id.get(pid)
            if row is None:
                continue
            row = dict(row)
            row["hops"] = hop
            result.append(row)
        return result
    finally:
        conn.close()


def find_in_radius(lat: float, lon: float, radius_km: float) -> List[Dict[str, Any]]:
    """All players within `radius_km` of (lat, lon). Uses player.lat/lon when
    present; otherwise falls back to country centroid lookup."""
    if radius_km <= 0:
        return []
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM players")
        rows = cur.fetchall()
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        plat, plon = d.get("lat"), d.get("lon")
        used_centroid = False
        if plat is None or plon is None:
            cc = (d.get("country_code") or "").upper()
            centroid = _country_latlon(cc)
            if centroid is None:
                continue
            plat, plon = centroid
            used_centroid = True
        dist = _haversine_km(lat, lon, float(plat), float(plon))
        if dist <= radius_km:
            d["distance_km"] = round(dist, 2)
            d["centroid_fallback"] = used_centroid
            out.append(d)
    out.sort(key=lambda x: x["distance_km"])
    return out


def stats() -> Dict[str, Any]:
    """Aggregate counts for dashboards / `cc -context`."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM players")
        players_total = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM friend_edges")
        edges_total = cur.fetchone()["n"]
        cur.execute(
            "SELECT source_via, COUNT(*) AS n FROM friend_edges GROUP BY source_via"
        )
        sources = {r["source_via"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            """SELECT country_code, COUNT(*) AS n FROM players
               WHERE country_code IS NOT NULL AND country_code != ''
               GROUP BY country_code ORDER BY n DESC LIMIT 10"""
        )
        top_countries = {r["country_code"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            "SELECT COUNT(*) AS n FROM players WHERE lat IS NOT NULL AND lon IS NOT NULL"
        )
        with_coords = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM friend_edges WHERE signed = 1")
        signed_edges = cur.fetchone()["n"]
    finally:
        conn.close()
    return {
        "players_total": players_total,
        "edges_total": edges_total,
        "sources": sources,
        "top_countries": top_countries,
        "players_with_coords": with_coords,
        "signed_edges": signed_edges,
        "db_path": str(_db_path()),
        "audit_path": str(_audit_path()),
    }


def export_for_planet_map(
    player_id: str,
    max_hops: int = 2,
    max_nodes: int = 100,
) -> Dict[str, Any]:
    """Build the JSON shape consumed by the Godot planet_map_scene fetcher:

        {
          "players":     [{player_id, lat, lon, name, picture_url}, ...],
          "friendships": [{player_a, player_b}, ...]
        }

    BFS rooted at `player_id` out to `max_hops`; capped at `max_nodes` players.
    Friendships listed once per unordered pair using lexicographic (a, b).
    Players without lat/lon get country-centroid fallback (lat/lon nullable
    if neither available)."""
    if max_hops < 0:
        max_hops = 0
    if max_nodes <= 0:
        max_nodes = 1
    conn = _connect()
    try:
        cur = conn.cursor()
        # BFS to collect player IDs
        included: List[str] = [player_id]
        visited = {player_id}
        frontier = [player_id]
        for _ in range(max_hops):
            if not frontier or len(included) >= max_nodes:
                break
            placeholders = ",".join("?" for _ in frontier)
            cur.execute(
                f"""SELECT DISTINCT target_player FROM friend_edges
                    WHERE source_player IN ({placeholders})""",
                tuple(frontier),
            )
            next_frontier: List[str] = []
            for row in cur.fetchall():
                tgt = row["target_player"]
                if tgt in visited:
                    continue
                visited.add(tgt)
                included.append(tgt)
                next_frontier.append(tgt)
                if len(included) >= max_nodes:
                    break
            frontier = next_frontier
        if not included:
            return {"players": [], "friendships": []}
        placeholders = ",".join("?" for _ in included)
        cur.execute(
            f"SELECT * FROM players WHERE player_id IN ({placeholders})",
            tuple(included),
        )
        player_rows = {r["player_id"]: dict(r) for r in cur.fetchall()}
        # All friendships *within* the included set
        cur.execute(
            f"""SELECT DISTINCT source_player, target_player FROM friend_edges
                WHERE source_player IN ({placeholders})
                  AND target_player IN ({placeholders})""",
            tuple(included) + tuple(included),
        )
        edges = cur.fetchall()
    finally:
        conn.close()
    # Project nodes
    players_out: List[Dict[str, Any]] = []
    for pid in included:
        p = player_rows.get(pid)
        if p is None:
            continue
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            centroid = _country_latlon((p.get("country_code") or "").upper())
            if centroid is not None:
                lat, lon = centroid
        players_out.append({
            "player_id":   p["player_id"],
            "lat":         lat,
            "lon":         lon,
            "name":        p.get("name") or "",
            "picture_url": p.get("picture_url") or "",
        })
    # Dedup friendships as unordered pairs
    seen_pairs: set = set()
    friendships_out: List[Dict[str, str]] = []
    for row in edges:
        a, b = row["source_player"], row["target_player"]
        if a == b:
            continue
        pair = (a, b) if a < b else (b, a)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        friendships_out.append({"player_a": pair[0], "player_b": pair[1]})
    return {"players": players_out, "friendships": friendships_out}


# -- CLI ----------------------------------------------------------------------

def _cli_kv(args: List[str]) -> Dict[str, str]:
    """Parse '--key value' pairs out of a positional argv tail."""
    out: Dict[str, str] = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("--") and i + 1 < len(args):
            out[tok[2:]] = args[i + 1]
            i += 2
        else:
            i += 1
    return out


def _cli_print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv: List[str]) -> int:
    if not argv:
        print("usage: social_graph_persistence.py "
              "<stats|upsert-player|upsert-edge|friends|fof|radius|export-planet|player> [...]",
              file=sys.stderr)
        return 2
    cmd = argv[0]
    rest = argv[1:]

    if cmd == "stats":
        _cli_print(stats())
        return 0

    if cmd == "upsert-player":
        if not rest:
            print("usage: upsert-player <player_id> [--name X --picture URL --lat F --lon F --country CC]",
                  file=sys.stderr)
            return 2
        pid = rest[0]
        kv = _cli_kv(rest[1:])
        lat = float(kv["lat"]) if "lat" in kv else None
        lon = float(kv["lon"]) if "lon" in kv else None
        cid = upsert_player(
            player_id=pid,
            name=kv.get("name", ""),
            picture_url=kv.get("picture", ""),
            lat=lat,
            lon=lon,
            country_code=kv.get("country", ""),
        )
        _cli_print({"ok": True, "player_id": pid, "crystal_id": cid})
        return 0

    if cmd == "upsert-edge":
        if len(rest) < 2:
            print("usage: upsert-edge <source> <target> [--via graph_api|fb_instant|manual] [--signed] [--oneway]",
                  file=sys.stderr)
            return 2
        src, tgt = rest[0], rest[1]
        kv = _cli_kv(rest[2:])
        flags = set(t for t in rest[2:] if t.startswith("--"))
        signed = "--signed" in flags
        bidi = "--oneway" not in flags
        cid = upsert_edge(
            source_player=src,
            target_player=tgt,
            source_via=kv.get("via", "graph_api"),
            signed=signed,
            bidirectional=bidi,
        )
        _cli_print({"ok": True, "pair": [src, tgt], "crystal_id": cid,
                    "bidirectional": bidi})
        return 0

    if cmd == "friends":
        if not rest:
            print("usage: friends <player_id>", file=sys.stderr)
            return 2
        _cli_print(get_friends(rest[0]))
        return 0

    if cmd == "fof":
        if not rest:
            print("usage: fof <player_id> [--depth N --limit N]", file=sys.stderr)
            return 2
        kv = _cli_kv(rest[1:])
        depth = int(kv.get("depth", "2"))
        limit = int(kv.get("limit", "200"))
        _cli_print(get_friend_of_friend(rest[0], depth=depth, limit=limit))
        return 0

    if cmd == "radius":
        kv = _cli_kv(rest)
        if "lat" not in kv or "lon" not in kv or "km" not in kv:
            print("usage: radius --lat F --lon F --km F", file=sys.stderr)
            return 2
        _cli_print(find_in_radius(float(kv["lat"]), float(kv["lon"]), float(kv["km"])))
        return 0

    if cmd == "player":
        if not rest:
            print("usage: player <player_id>", file=sys.stderr)
            return 2
        _cli_print(get_player(rest[0]))
        return 0

    if cmd == "export-planet":
        if not rest:
            print("usage: export-planet <player_id> [--hops N --max N]", file=sys.stderr)
            return 2
        kv = _cli_kv(rest[1:])
        hops = int(kv.get("hops", "2"))
        max_nodes = int(kv.get("max", "100"))
        _cli_print(export_for_planet_map(rest[0], max_hops=hops, max_nodes=max_nodes))
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
