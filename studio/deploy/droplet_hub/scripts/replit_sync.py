"""replit_sync.py — Data dump + scheduled code generation sync to Replit.

Usage:
    python3 replit_sync.py --data-dir /opt/mspc-public/solana/feed \
                           --replit-project zero2onez-solana-sync

Requires: replit Python client or plain HTTP API key
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import time
from pathlib import Path
from typing import List


def dump_to_jsonl(data_dir: Path) -> Path:
    """Dump all feed files to a single gzipped JSONL."""
    ts = int(time.time())
    out = Path(f"/tmp/replit_sync_{ts}.jsonl.gz")
    total = 0
    with gzip.open(out, "wt") as gz:
        for feed_file in data_dir.glob("*.jsonl"):
            with open(feed_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        gz.write(line + "\n")
                        total += 1
    print(f"[replit_sync] Dumped {total} lines to {out}")
    return out


def sync_to_replit(dump_path: Path, project: str, api_key: str):
    """Upload dump to Replit via their API."""
    # Replit doesn't have a native bulk-upload API for data,
    # so we use the Repl DB or external storage.
    # For now, this is a stub that writes to a known drop point.
    drop_dir = Path.home() / ".replit_sync"
    drop_dir.mkdir(parents=True, exist_ok=True)
    dest = drop_dir / f"{project}_{dump_path.name}"
    # Copy locally (Replit can mount this dir via cloud sync)
    import shutil
    shutil.copy2(dump_path, dest)
    print(f"[replit_sync] Copied to local drop: {dest}")

    # Trigger Replit webhook if configured
    webhook = os.environ.get("REPLIT_WEBHOOK", "").strip()
    if webhook and api_key:
        try:
            import urllib.request
            payload = json.dumps({
                "project": project,
                "file": str(dest),
                "timestamp": time.time(),
                "action": "data_sync",
            }).encode()
            req = urllib.request.Request(
                webhook,
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(f"[replit_sync] Webhook response: {resp.status}")
        except Exception as e:
            print(f"[replit_sync] Webhook failed: {e}")


def generate_code_schedule(project: str, api_key: str):
    """Trigger scheduled code generation on Replit."""
    # Stub: in production, this would call Replit's GraphQL API
    # or use their deployment triggers.
    print(f"[replit_sync] Code generation schedule triggered for {project}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--replit-project", type=str, default="zero2onez-solana-sync")
    ap.add_argument("--skip-dump", action="store_true")
    ap.add_argument("--skip-codegen", action="store_true")
    args = ap.parse_args()

    api_key = os.environ.get("REPLIT_API_KEY", "").strip()

    if not args.skip_dump:
        dump = dump_to_jsonl(args.data_dir)
        sync_to_replit(dump, args.replit_project, api_key)
        dump.unlink(missing_ok=True)

    if not args.skip_codegen:
        generate_code_schedule(args.replit_project, api_key)


if __name__ == "__main__":
    main()
