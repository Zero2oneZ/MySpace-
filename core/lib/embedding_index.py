"""embedding_index.py — cosine-similarity retrieval over the stream_encoder
output. Stdlib + optional numpy.

The encoder writes JSONL lines with `vec_hex` (L2-normalized float32 packed
to hex). This module re-hydrates a memory-resident index of the most recent N
embeddings + provides:
  - add(crystal, vec)
  - find_nearest(query_vec, k=10) -> [(crystal, similarity, source, kind)]
  - find_by_crystal(crystal) -> Optional[record]
  - reload_from_jsonl(date=today) -> count loaded
  - save(path) / load(path)

For v1 we do a linear scan (cosine via dot product, since vectors are
L2-normalized). Fine up to ~100k entries on a modern CPU. Above that, swap
in FAISS as a drop-in replacement of the `find_nearest` body.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

EMB_ROOT = Path(os.path.expanduser("~/.cc/embeddings"))
INDEX_PATH = EMB_ROOT / "_index.bin"      # packed dense matrix
META_PATH = EMB_ROOT / "_index_meta.jsonl"  # one line per row

try:
    import numpy as _np  # type: ignore
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


@dataclass
class IndexedEvent:
    crystal_anchor: str
    source: str
    kind: str
    ts: float
    sentence: str = ""
    encoded_image: str = ""


# ── vec packing ────────────────────────────────────────────────────────────

def hex_to_vec(h: str) -> List[float]:
    data = bytes.fromhex(h)
    return list(struct.unpack(f"<{len(data)//4}f", data))


def vec_to_hex(v: List[float]) -> str:
    return b"".join(struct.pack("<f", float(x)) for x in v).hex()


def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity. If both vectors are L2-normalized (the encoder
    output guarantees this), this equals the dot product."""
    n = min(len(a), len(b))
    s = 0.0
    for i in range(n):
        s += a[i] * b[i]
    return s


# ── in-memory index ────────────────────────────────────────────────────────

class EmbeddingIndex:
    def __init__(self):
        self.rows: List[IndexedEvent] = []
        # For numpy path: a (N, dim) matrix kept synchronized with rows.
        # For stdlib path: a list of list[float].
        self._vecs_np = None  # numpy array or None
        self._vecs_list: List[List[float]] = []
        self._by_crystal: Dict[str, int] = {}
        self._dim = 0

    # ---- mutation ----

    def add(self, vec: List[float], event: IndexedEvent) -> int:
        if self._dim == 0:
            self._dim = len(vec)
        if HAVE_NUMPY:
            row = _np.asarray(vec, dtype=_np.float32)
            if self._vecs_np is None:
                self._vecs_np = row.reshape(1, -1)
            else:
                self._vecs_np = _np.vstack((self._vecs_np, row))
        else:
            self._vecs_list.append(list(vec))
        idx = len(self.rows)
        self.rows.append(event)
        if event.crystal_anchor:
            self._by_crystal[event.crystal_anchor] = idx
        return idx

    # ---- query ----

    def find_nearest(self, query: List[float], k: int = 10,
                      source_filter: str = "",
                      kind_prefix: str = "") -> List[Tuple[IndexedEvent, float]]:
        if not self.rows:
            return []
        if HAVE_NUMPY and self._vecs_np is not None:
            q = _np.asarray(query, dtype=_np.float32)
            # Cosine via dot product (rows are pre-normalized)
            sims = self._vecs_np @ q
            order = _np.argsort(-sims)
            out: List[Tuple[IndexedEvent, float]] = []
            for i in order:
                ev = self.rows[int(i)]
                if source_filter and ev.source != source_filter:
                    continue
                if kind_prefix and not ev.kind.startswith(kind_prefix):
                    continue
                out.append((ev, float(sims[int(i)])))
                if len(out) >= k:
                    break
            return out
        # stdlib path
        scored: List[Tuple[int, float]] = []
        for i, v in enumerate(self._vecs_list):
            scored.append((i, _cosine(v, query)))
        scored.sort(key=lambda x: -x[1])
        out: List[Tuple[IndexedEvent, float]] = []
        for i, s in scored:
            ev = self.rows[i]
            if source_filter and ev.source != source_filter:
                continue
            if kind_prefix and not ev.kind.startswith(kind_prefix):
                continue
            out.append((ev, s))
            if len(out) >= k:
                break
        return out

    def find_by_crystal(self, crystal_anchor: str) -> Optional[Tuple[IndexedEvent, List[float]]]:
        idx = self._by_crystal.get(crystal_anchor)
        if idx is None:
            return None
        ev = self.rows[idx]
        if HAVE_NUMPY and self._vecs_np is not None:
            return ev, list(map(float, self._vecs_np[idx]))
        return ev, self._vecs_list[idx]

    def size(self) -> int:
        return len(self.rows)

    def dim(self) -> int:
        return self._dim

    # ---- persistence ----

    def save(self, path_index: Path = INDEX_PATH,
             path_meta: Path = META_PATH) -> None:
        path_index.parent.mkdir(parents=True, exist_ok=True)
        if HAVE_NUMPY and self._vecs_np is not None:
            with path_index.open("wb") as f:
                f.write(struct.pack("<II", self._vecs_np.shape[0],
                                     self._vecs_np.shape[1]))
                f.write(self._vecs_np.astype(_np.float32).tobytes())
        else:
            with path_index.open("wb") as f:
                n = len(self._vecs_list)
                d = self._dim
                f.write(struct.pack("<II", n, d))
                for v in self._vecs_list:
                    for x in v:
                        f.write(struct.pack("<f", float(x)))
        with path_meta.open("w") as f:
            for ev in self.rows:
                f.write(json.dumps(asdict(ev), separators=(",", ":")) + "\n")

    def load(self, path_index: Path = INDEX_PATH,
             path_meta: Path = META_PATH) -> int:
        if not path_index.exists() or not path_meta.exists():
            return 0
        with path_index.open("rb") as f:
            n, d = struct.unpack("<II", f.read(8))
            self._dim = d
            if HAVE_NUMPY:
                arr = _np.frombuffer(f.read(n * d * 4), dtype=_np.float32)
                self._vecs_np = arr.reshape(n, d).copy()
                self._vecs_list = []
            else:
                self._vecs_list = []
                for _ in range(n):
                    v = list(struct.unpack(f"<{d}f", f.read(d * 4)))
                    self._vecs_list.append(v)
        self.rows = []
        self._by_crystal = {}
        with path_meta.open() as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                d2 = json.loads(ln)
                ev = IndexedEvent(**d2)
                self._by_crystal[ev.crystal_anchor] = len(self.rows)
                self.rows.append(ev)
        return len(self.rows)

    # ---- ingest from stream_encoder JSONL ----

    def ingest_jsonl(self, jsonl_path: Path) -> int:
        if not jsonl_path.exists():
            return 0
        added = 0
        with jsonl_path.open() as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                vec = hex_to_vec(d["vec_hex"])
                ev = IndexedEvent(
                    crystal_anchor=str(d.get("crystal_anchor", "") or
                                         d.get("source_event_hash", "")),
                    source=str(d.get("source", "?")),
                    kind=str(d.get("kind", "?")),
                    ts=float(d.get("ts", 0.0)),
                    sentence=str(d.get("sentence", "")),
                    encoded_image=str(d.get("encoded_image", "")),
                )
                self.add(vec, ev)
                added += 1
        return added


# ── module-level singleton + helpers ────────────────────────────────────────

_SINGLETON: Optional[EmbeddingIndex] = None


def get_singleton() -> EmbeddingIndex:
    """Lazy global index. Pre-loaded from disk on first access if persisted."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = EmbeddingIndex()
        if INDEX_PATH.exists():
            try:
                _SINGLETON.load()
            except Exception as exc:
                sys.stderr.write(f"[index] load failed: {exc!r}\n")
    return _SINGLETON


def reload_today() -> int:
    """Wipe + reload from today's stream_encoder output."""
    global _SINGLETON
    _SINGLETON = EmbeddingIndex()
    today = EMB_ROOT / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
    return _SINGLETON.ingest_jsonl(today)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="embedding_index — cosine retrieval")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest stream_encoder JSONL")
    p_ingest.add_argument("--from", dest="src", required=True)

    p_save = sub.add_parser("save")
    p_load = sub.add_parser("load")
    p_load.add_argument("--reload-today", action="store_true")

    p_q = sub.add_parser("query-by-crystal")
    p_q.add_argument("crystal")
    p_q.add_argument("--k", type=int, default=10)

    p_qs = sub.add_parser("query-by-sentence",
                          help="encode a sentence via stream_encoder then find nearest")
    p_qs.add_argument("sentence")
    p_qs.add_argument("--k", type=int, default=10)
    p_qs.add_argument("--source")
    p_qs.add_argument("--kind-prefix")

    sub.add_parser("stats")

    args = ap.parse_args(argv)
    idx = get_singleton()

    if args.cmd == "ingest":
        n = idx.ingest_jsonl(Path(args.src).expanduser())
        print(f"ingested {n}; total now {idx.size()}")
        return 0

    if args.cmd == "save":
        idx.save()
        print(f"saved {idx.size()} rows to {INDEX_PATH}")
        return 0

    if args.cmd == "load":
        if args.reload_today:
            n = reload_today()
            idx_local = get_singleton()
            print(f"reloaded {n} rows from today")
        else:
            n = idx.load()
            print(f"loaded {n} rows")
        return 0

    if args.cmd == "query-by-crystal":
        hit = idx.find_by_crystal(args.crystal)
        if not hit:
            print(f"no match for crystal {args.crystal}")
            return 1
        ev, vec = hit
        print(f"hit: {ev}")
        neighbors = idx.find_nearest(vec, k=args.k)
        for ev2, sim in neighbors:
            print(f"  sim={sim:+.4f}  {ev2.source:18s} {ev2.kind:32s} {ev2.crystal_anchor[:16]}")
        return 0

    if args.cmd == "query-by-sentence":
        # Lazy import — only if user explicitly asks
        import importlib
        try:
            se = importlib.import_module("stream_encoder")
        except ImportError:
            print("stream_encoder not importable; need its sys.path", file=sys.stderr)
            return 2
        enc = se.StreamEncoder()
        enc.warm()
        vec, _ = enc.encode_text(args.sentence)
        neighbors = idx.find_nearest(vec, k=args.k,
                                       source_filter=args.source or "",
                                       kind_prefix=args.kind_prefix or "")
        for ev, sim in neighbors:
            print(f"  sim={sim:+.4f}  {ev.source:18s} {ev.kind:36s} {ev.sentence[:60]}")
        return 0

    if args.cmd == "stats":
        print(json.dumps({
            "size": idx.size(),
            "dim": idx.dim(),
            "have_numpy": HAVE_NUMPY,
            "index_path": str(INDEX_PATH),
            "meta_path": str(META_PATH),
        }, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
