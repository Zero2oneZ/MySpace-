"""sidecar.py — write + update JSON sidecars next to media files.

Each downloaded/imported media file gets a sibling `.json` with metadata.
The same source can produce multiple instance files (image, mask,
no-bg, depth, 3d-mesh, etc.) — those are tracked as `variants` on the
parent sidecar.

Schema:
    {
      "sha": "<8-hex content hash>",
      "source_url": "https://...",
      "source_kind": "pinterest|youtube|url|upload",
      "category": "Cloths/Female/Tops",
      "label": "Red blouse",
      "description": "Long-sleeve red blouse, satin finish",
      "tags": ["clothing", "tops", "female"],
      "downloaded_at": "2026-05-26T17:00:00Z",
      "variants": [
        {"kind": "image",  "path": "Cloths/Female/Tops/abc12345.jpg"},
        {"kind": "nobg",   "path": "Cloths/Female/Tops/abc12345_nobg.png"},
        {"kind": "mask",   "path": "Cloths/Female/Tops/abc12345_mask.png"}
      ],
      "uses": ["sample", "training", "mask"]   # what this asset is used FOR
    }

Usage:
    from sidecar import write, read, add_variant, register_use
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Optional


def content_sha(path: Path | str, prefix: int = 8) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:prefix]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sidecar_path(media_path: Path | str) -> Path:
    p = Path(media_path)
    # The sidecar sits next to the BASE asset (strip _mask / _nobg variants).
    stem = p.stem
    for suffix in ("_mask", "_nobg", "_depth", "_3d"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return p.with_name(f"{stem}.json")


def read(media_path: Path | str) -> Optional[dict]:
    sc = _sidecar_path(media_path)
    if not sc.exists():
        return None
    try:
        return json.loads(sc.read_text())
    except json.JSONDecodeError:
        return None


def write(media_path: Path | str, **fields) -> Path:
    """Create or REPLACE the sidecar JSON. Caller provides full fields."""
    sc = _sidecar_path(media_path)
    fields.setdefault("downloaded_at", now_iso())
    sc.write_text(json.dumps(fields, indent=2, sort_keys=True))
    return sc


def merge(media_path: Path | str, **fields) -> Path:
    """Create or UPDATE — merges fields into existing sidecar; lists are
    deduped, dicts shallow-merged, scalars replaced."""
    sc = _sidecar_path(media_path)
    existing = read(media_path) or {}
    for k, v in fields.items():
        if isinstance(v, list) and isinstance(existing.get(k), list):
            seen = []
            for item in existing[k] + v:
                if item not in seen:
                    seen.append(item)
            existing[k] = seen
        elif isinstance(v, dict) and isinstance(existing.get(k), dict):
            existing[k] = {**existing[k], **v}
        else:
            existing[k] = v
    existing.setdefault("downloaded_at", now_iso())
    sc.write_text(json.dumps(existing, indent=2, sort_keys=True))
    return sc


def add_variant(media_path: Path | str, variant_kind: str, variant_path: str) -> Path:
    """Append a {kind, path} entry to variants[]."""
    return merge(media_path, variants=[{"kind": variant_kind, "path": variant_path}])


def register_use(media_path: Path | str, use_label: str) -> Path:
    """Append a usage label (e.g. 'sample', 'training', 'mask', '3d-input')."""
    return merge(media_path, uses=[use_label])


if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser(prog="sidecar.py")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p_write = sp.add_parser("write")
    p_write.add_argument("path")
    p_write.add_argument("--label", default="")
    p_write.add_argument("--description", default="")
    p_write.add_argument("--source", default="")
    p_write.add_argument("--tags", nargs="*", default=[])
    p_read = sp.add_parser("read"); p_read.add_argument("path")
    p_use  = sp.add_parser("register-use")
    p_use.add_argument("path"); p_use.add_argument("use")
    args = ap.parse_args()
    if args.cmd == "write":
        sha = content_sha(args.path) if Path(args.path).exists() else "unknown"
        write(args.path, sha=sha, label=args.label,
              description=args.description,
              source_url=args.source, tags=args.tags)
        print(_sidecar_path(args.path))
    elif args.cmd == "read":
        sc = read(args.path)
        if sc is None: print("(no sidecar)"); sys.exit(1)
        print(json.dumps(sc, indent=2))
    elif args.cmd == "register-use":
        register_use(args.path, args.use)
        print(f"registered use '{args.use}' for {args.path}")
