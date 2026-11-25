"""import_pipeline.py — orchestrate every import-time pass for one asset.

Heavy lifts happen here, NOT at render time. The flow:

    file ───►  filetype_dag.plan_for(ext)
              │
              ├──► run each import_time pass via passes.inference
              │      ├─ time each (passes.timing.Timer)
              │      └─ on success, register a piece (passes.pieces_index)
              │
              ├──► pack everything into one labeled SVG (passes.svg_layers)
              │
              └──► update the sidecar (.tools/sidecar.py) so the asset
                   knows about its variants[]

Run:
    cc -passes-run <file>          # one-shot
    python3 import_pipeline.py <file>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

# Resolve siblings + the parent studio dir.
HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent.parent
sys.path.insert(0, str(STUDIO_ROOT))
sys.path.insert(0, str(HERE))

import paths                                # noqa: E402
from passes import inference, svg_layers    # noqa: E402
from passes import pieces_index, registry   # noqa: E402
from passes import filetype_dag             # noqa: E402

try:
    import sidecar                          # noqa: E402  (media/.tools/sidecar.py)
except ImportError:
    sidecar = None  # type: ignore


def _content_sha(p: Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def already_processed(asset_path: Path) -> bool:
    """An asset is considered processed if its layered SVG exists AND
    pieces index has at least one entry for its content hash."""
    sha = _content_sha(asset_path)
    svg = paths.LAYER_STYLE_DIR / f"{asset_path.stem}.layers.svg"
    if not svg.exists():
        return False
    pieces = pieces_index.by_asset(sha)
    return len(pieces) > 0


def run(asset_path: Path, *, reprocess: bool = False, verbose: bool = False) -> dict:
    """Drive the import-time pipeline for one asset. Returns a summary dict."""
    asset_path = Path(asset_path).resolve()
    if not asset_path.exists():
        raise FileNotFoundError(asset_path)
    if not reprocess and already_processed(asset_path):
        return {"ok": True, "skipped": True, "reason": "already processed",
                "asset": str(asset_path)}

    ext = asset_path.suffix.lstrip(".").lower()
    plan = filetype_dag.plan_for(ext)
    if plan["n_total"] == 0:
        return {"ok": False, "asset": str(asset_path),
                "error": f"no passes registered for .{ext}"}

    sha = _content_sha(asset_path)
    t_start = time.perf_counter()
    results: list[dict] = []
    piece_ids: list[str] = []

    for pass_id in plan["import_time"]:
        # `layered_svg` is the final bundler — skip until the end.
        if pass_id == "layered_svg":
            continue
        if verbose:
            print(f"  → {pass_id}", flush=True)
        r = inference.run(pass_id, asset_path)
        results.append(r)
        if not r["ok"]:
            continue
        # Register the piece in the index for searchability.
        try:
            pid = pieces_index.upsert(
                sha, asset_path, pass_id,
                path=r.get("path"),
                value=(str(r.get("value"))
                       if r.get("value") is not None else None),
                kind=r.get("kind"),
                label=asset_path.stem.replace("_", " ").strip(),
                description=r.get("instruction", "")
                            or registry.by_id(pass_id).description,
                tags=_seed_tags(asset_path),
            )
            piece_ids.append(pid)
        except Exception as e:
            r["index_error"] = str(e)

    # Bundle into one SVG (which is itself recorded as a piece).
    svg_path = svg_layers.pack(asset_path, results)
    pid = pieces_index.upsert(
        sha, asset_path, "layered_svg",
        path=str(svg_path), kind="SVG",
        label=asset_path.stem.replace("_", " ").strip(),
        description="bundle of all import-time pass outputs",
        tags=_seed_tags(asset_path) + ["layered"],
    )
    piece_ids.append(pid)

    # Update the sidecar with the freshly-discovered variants.
    if sidecar is not None:
        try:
            variants = []
            for r in results:
                if not r["ok"] or not r.get("path"):
                    continue
                variants.append({"kind": r["pass_id"],
                                 "path": str(r["path"])})
            variants.append({"kind": "layered_svg", "path": str(svg_path)})
            sidecar.merge(
                asset_path,
                sha=sha,
                variants=variants,
                passes_run=[r["pass_id"] for r in results if r["ok"]],
                pipeline_ms=round((time.perf_counter() - t_start) * 1000, 2),
            )
        except Exception:
            pass

    total_ms = (time.perf_counter() - t_start) * 1000
    return {
        "ok": True,
        "asset": str(asset_path),
        "asset_sha": sha,
        "svg": str(svg_path),
        "passes_ok": sum(1 for r in results if r["ok"]),
        "passes_skipped": sum(1 for r in results if not r["ok"]),
        "pieces_indexed": len(piece_ids),
        "total_ms": round(total_ms, 2),
        "details": [{"pass": r["pass_id"], "ok": r["ok"],
                     "ms": round(r.get("duration_ms", 0), 1),
                     "error": r.get("error")} for r in results],
    }


def _seed_tags(asset_path: Path) -> list[str]:
    """Seed tag list from the file's location in the media taxonomy."""
    try:
        rel = asset_path.relative_to(paths.MEDIA_ROOT)
        # Drop the filename, keep dir segments.
        return [seg for seg in rel.parent.parts if seg and not seg.startswith(".")]
    except ValueError:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(prog="import_pipeline.py")
    ap.add_argument("path", help="file to process")
    ap.add_argument("--reprocess", action="store_true",
                    help="re-run even if already processed")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    summary = run(Path(args.path), reprocess=args.reprocess, verbose=args.verbose)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
