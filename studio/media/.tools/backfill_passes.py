"""backfill_passes.py — loop over existing media + apply the import pipeline.

For every file under studio/media/ that hasn't been processed yet (no
layered SVG, no pieces index entries), run the same import-pipeline
flow that runs at fresh import. Idempotent — safe to re-run.

Modes:
    --rate N            cap at N files/sec (gentle background)
    --dry-run           list what WOULD run, don't actually run
    --only PATH         scope to a subdir (e.g. Cloths/Female/Tops)
    --reprocess         redo even already-processed files
    --limit N           process at most N files this run
    --pass-id PID       run ONLY a specific pass (across all assets), bypassing pipeline
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parent.parent
sys.path.insert(0, str(STUDIO_ROOT))
sys.path.insert(0, str(HERE))

import paths                              # noqa: E402
import import_pipeline                    # noqa: E402
from passes import inference, registry    # noqa: E402

# File types we know how to process at all.
KNOWN_EXTS = set()
for p in registry.REGISTRY:
    KNOWN_EXTS.update(e.lower() for e in p.file_extensions)


def discover(scope: Path) -> list[Path]:
    """All files under `scope` whose extension is recognized."""
    out: list[Path] = []
    for p in scope.rglob("*"):
        if not p.is_file():
            continue
        if any(seg.startswith(".") for seg in p.parts):
            continue        # skip .tools / .staging / .logs / __pycache__
        # Skip pass-output files (foo__mask.png etc)
        if "__" in p.stem and p.stem.split("__")[-1] in {
                "thumb", "mask", "nobg", "depth", "normal_map",
                "vidthumb", "waveform", "embedding"}:
            continue
        if p.suffix.lstrip(".").lower() in KNOWN_EXTS:
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="backfill_passes.py")
    ap.add_argument("--rate", type=float, default=0.0,
                    help="max files/sec (0 = unlimited)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would run, don't actually run")
    ap.add_argument("--only", default=None,
                    help="restrict to subdir under media/ (e.g. Cloths/Female/Tops)")
    ap.add_argument("--reprocess", action="store_true",
                    help="re-process even already-processed files")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N files (0 = no limit)")
    ap.add_argument("--pass-id", default=None,
                    help="run only this single pass across discovered files "
                         "(bypasses the full pipeline)")
    args = ap.parse_args()

    scope = paths.MEDIA_ROOT if args.only is None else (paths.MEDIA_ROOT / args.only)
    if not scope.exists():
        print(f"scope dir missing: {scope}", file=sys.stderr); return 2

    files = discover(scope)
    print(f"backfill: scope={scope}  candidates={len(files)}", file=sys.stderr)

    if args.dry_run:
        for f in files[:50]:
            print(f)
        if len(files) > 50:
            print(f"  ... and {len(files) - 50} more")
        return 0

    ok = skipped = failed = 0
    delay = 1.0 / args.rate if args.rate > 0 else 0.0
    log_path = paths.LOGS_ROOT / f"backfill-{int(time.time())}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w")

    for i, f in enumerate(files):
        if args.limit and ok + failed >= args.limit:
            break
        try:
            if args.pass_id:
                # Targeted single-pass mode (e.g. backfill captions only).
                r = inference.run(args.pass_id, f)
                rec = {"file": str(f), "pass": args.pass_id, **r}
            else:
                rec = import_pipeline.run(f, reprocess=args.reprocess)
                rec.setdefault("ok", False)
                if rec.get("skipped"):
                    skipped += 1
                elif rec["ok"]:
                    ok += 1
                else:
                    failed += 1
        except Exception as e:
            rec = {"file": str(f), "ok": False, "error": str(e)}
            failed += 1
        log.write(json.dumps(rec, default=str) + "\n"); log.flush()
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(files)}  ok={ok} skipped={skipped} failed={failed}",
                  file=sys.stderr)
        if delay > 0:
            time.sleep(delay)

    log.close()
    print(f"\nbackfill done: ok={ok} skipped={skipped} failed={failed}",
          file=sys.stderr)
    print(f"log: {log_path}", file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
