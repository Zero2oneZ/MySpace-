"""hf_sync.py — Push Solana feed data to HuggingFace Datasets + DO Spaces.

Usage:
    python3 hf_sync.py --feed /opt/mspc-public/solana/feed/live_features.jsonl \
                       --dataset zero2onez/solana-pump-patterns

Requires: huggingface_hub (pip install huggingface_hub)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Dict, List

try:
    from huggingface_hub import HfApi, create_repo, upload_file
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    print("[hf_sync] WARNING: huggingface_hub not installed. Install: pip install huggingface_hub")


def load_feed(feed_path: Path, max_lines: int = 50000) -> List[Dict]:
    records = []
    with open(feed_path) as f:
        for i, line in enumerate(f):
            if max_lines > 0 and i >= max_lines:
                break
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
                if o.get("slot", 0) > 0 and o.get("token"):
                    records.append({
                        "signature": o.get("signature", ""),
                        "slot": o.get("slot", 0),
                        "wallet": o.get("wallet", ""),
                        "token": o.get("token", ""),
                        "features": json.dumps(o.get("features", [])),
                        "is_buy": bool(o.get("is_buy")),
                        "is_sell": bool(o.get("is_sell")),
                        "is_create": bool(o.get("is_create")),
                        "sol_delta": o.get("sol_delta", 0.0),
                        "fee": o.get("fee", 0),
                        "ts": o.get("ts", 0.0),
                    })
            except Exception:
                pass
    return records


def sync_to_hf(records: List[Dict], dataset_name: str, token: str):
    if not HF_AVAILABLE:
        print("[hf_sync] Skipping HF sync — huggingface_hub not available")
        return

    api = HfApi(token=token)

    # Check if repo exists, create if not
    try:
        api.repo_info(repo_id=dataset_name, repo_type="dataset")
    except Exception:
        print(f"[hf_sync] Creating dataset repo: {dataset_name}")
        create_repo(dataset_name, repo_type="dataset", token=token, exist_ok=True)

    # Write as JSONL
    ts = int(time.time())
    tmp_path = Path(f"/tmp/hf_sync_{ts}.jsonl")
    with open(tmp_path, "w") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")

    # Upload
    upload_file(
        path_or_fileobj=str(tmp_path),
        path_in_repo=f"data/solana_feed_{ts}.jsonl",
        repo_id=dataset_name,
        repo_type="dataset",
        token=token,
    )
    print(f"[hf_sync] Uploaded {len(records)} records to {dataset_name}/data/solana_feed_{ts}.jsonl")
    tmp_path.unlink(missing_ok=True)


def sync_to_spaces(records: List[Dict], bucket: str, region: str, key: str, secret: str):
    """Sync to DigitalOcean Spaces (S3-compatible)."""
    try:
        import boto3
    except ImportError:
        print("[hf_sync] boto3 not installed, skipping Spaces sync")
        return

    session = boto3.session.Session()
    client = session.client(
        "s3",
        region_name=region,
        endpoint_url=f"https://{region}.digitaloceanspaces.com",
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )

    ts = int(time.time())
    key_name = f"solana/pump_patterns_{ts}.jsonl"
    body = "\n".join(json.dumps(r, default=str) for r in records)

    try:
        client.put_object(Bucket=bucket, Key=key_name, Body=body.encode())
        print(f"[hf_sync] Uploaded to Spaces: {bucket}/{key_name}")
    except Exception as e:
        print(f"[hf_sync] Spaces upload failed: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", type=Path, required=True)
    ap.add_argument("--dataset", type=str, default="zero2onez/solana-pump-patterns")
    ap.add_argument("--max-lines", type=int, default=50000)
    ap.add_argument("--spaces-bucket", type=str, default="")
    ap.add_argument("--spaces-region", type=str, default="nyc3")
    args = ap.parse_args()

    hf_token = os.environ.get("HF_TOKEN", "").strip()
    spaces_key = os.environ.get("SPACES_KEY", "").strip()
    spaces_secret = os.environ.get("SPACES_SECRET", "").strip()

    print(f"[hf_sync] Loading feed: {args.feed}")
    records = load_feed(args.feed, args.max_lines)
    print(f"[hf_sync] Records loaded: {len(records)}")

    if not records:
        print("[hf_sync] No records to sync.")
        return

    if hf_token:
        sync_to_hf(records, args.dataset, hf_token)
    else:
        print("[hf_sync] No HF_TOKEN — skipping HuggingFace sync")

    if args.spaces_bucket and spaces_key and spaces_secret:
        sync_to_spaces(records, args.spaces_bucket, args.spaces_region, spaces_key, spaces_secret)
    else:
        print("[hf_sync] No Spaces credentials — skipping Spaces sync")


if __name__ == "__main__":
    main()
