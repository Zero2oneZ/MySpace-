#!/usr/bin/env bash
# ============================================================================
# facebook_games_ingest.sh                                                   =
# ----------------------------------------------------------------------------=
# Fetch the 8 Facebook Games developer-doc URLs, parse each via              =
# doc_parser_facebook_games.FacebookGamesAdapter, write per-page JSONL into  =
# studio/assets/_doc_corpus/facebook_games/<sha8>.jsonl, and emit a summary  =
# INDEX.json + one crystal-anchored InferenceLogger record.                  =
#                                                                            =
# Tom can re-run any time to refresh — output filenames are content-addressed=
# so unchanged pages overwrite themselves with identical bytes.              =
#                                                                            =
# Constraints:                                                               =
#   - stdlib only (urllib + html.parser)                                     =
#   - polite scraping: 2s between requests                                   =
#   - hard cap 60s total wall time inside the python step                    =
#   - 403/429/timeout handled gracefully (per-URL skip, ingest continues)    =
# ============================================================================
set -u

# Resolve repo root from this script's location: core/scripts/.. -> core ; .. -> repo root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "${SCRIPT_DIR}/../.." && pwd )"

cd "${REPO_ROOT}"

# Ensure landing dir exists before the python step writes into it
mkdir -p "studio/assets/_doc_corpus/facebook_games"

# Run the ingester. Wall-time guarded with a Python deadline (so we don't need
# `timeout(1)` and so a slow last URL doesn't kill the summary write).
python3 - <<'PYEOF'
"""Facebook Games doc ingest driver.

Uses doc_parser_facebook_games.FacebookGamesAdapter (auto-registers on import)
plus doc_parser.parse_url() for the per-page fetch+parse+JSONL pipeline.

Polite scrape: 2s between requests. Hard wall-clock deadline: 60s total.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# -------------------------------------------------------------------------
# Wire up the lib dir, register the FB Games adapter, prepare paths
# -------------------------------------------------------------------------
REPO_ROOT = Path.cwd()
LIB_DIR = REPO_ROOT / "core" / "lib"
sys.path.insert(0, str(LIB_DIR))

import doc_parser                            # noqa: E402
import doc_parser_facebook_games as fbg      # noqa: E402  (auto-registers on import)

# Defensive: ensure registration even if a previous import was cached differently.
fbg.register()

OUT_DIR = REPO_ROOT / "studio" / "assets" / "_doc_corpus" / "facebook_games"
OUT_DIR.mkdir(parents=True, exist_ok=True)

URLS = [
    "https://developers.facebook.com/docs/games/",
    "https://developers.facebook.com/docs/games/build/instant-games/",
    "https://developers.facebook.com/docs/games/build/login/",
    "https://developers.facebook.com/docs/games/build/cloud/",
    "https://developers.facebook.com/docs/games-services/",
    "https://developers.facebook.com/docs/games/services/social-graph",
    "https://developers.facebook.com/docs/games/services/app-events",
    "https://developers.facebook.com/docs/games-services/sharing/",
]

UA = "MySpace++/games_ingest (+contact: studio@myspace-plus-plus.local)"
PER_REQUEST_TIMEOUT = 12.0   # seconds
SLEEP_BETWEEN = 2.0          # polite cadence
WALL_DEADLINE = 60.0         # hard ingest budget

start = time.monotonic()
results = []         # per-URL dict
n_total_nodes = 0
n_successful = 0


def _sha8(url: str, html_bytes: bytes) -> str:
    """Stable short id used in logs (the JSONL filename itself is set by doc_parser)."""
    h = hashlib.blake2b()
    h.update(url.encode("utf-8"))
    h.update(b"\n")
    h.update(html_bytes)
    return h.hexdigest()[:8]


def _fetch(url: str) -> tuple[int, bytes, str]:
    """Returns (status, body, error_msg). Status 0 on transport failure."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.7",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=PER_REQUEST_TIMEOUT) as resp:  # noqa: S310
            body = resp.read()
            return resp.status, body, ""
    except urllib.error.HTTPError as e:
        # Read body if any (FB sometimes returns useful 403 bodies)
        body = b""
        try:
            body = e.read() or b""
        except Exception:
            pass
        return e.code, body, f"HTTPError {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return 0, b"", f"URLError: {e.reason}"
    except TimeoutError as e:
        return 0, b"", f"Timeout: {e}"
    except Exception as e:  # noqa: BLE001 — final safety net
        return 0, b"", f"{type(e).__name__}: {e}"


for i, url in enumerate(URLS):
    elapsed = time.monotonic() - start
    if elapsed > WALL_DEADLINE:
        results.append({
            "url": url,
            "status": -1,
            "ok": False,
            "error": f"skipped: wall deadline {WALL_DEADLINE}s exceeded",
            "n_nodes": 0,
            "out": "",
        })
        continue

    status, body, err = _fetch(url)
    entry = {
        "url": url,
        "status": status,
        "ok": False,
        "error": err,
        "n_nodes": 0,
        "out": "",
        "sha8": "",
    }

    if status == 200 and body:
        try:
            # Use the in-process adapter (already registered). parse_html_file
            # is the same code path parse_url uses post-fetch.
            adapter = doc_parser.get_adapter("facebook_games")
            nodes, quality = doc_parser._run_adapter(adapter, body)
            crystal_short = doc_parser._crystal_short(body)
            out_path = OUT_DIR / f"{crystal_short}.jsonl"
            if out_path.exists():
                out_path.unlink()
            n_nodes = doc_parser._emit_jsonl(iter(nodes), out_path)
            doc_parser._log_anchor("facebook_games", url, out_path, n_nodes, quality)

            entry["ok"] = True
            entry["n_nodes"] = n_nodes
            entry["out"] = str(out_path.relative_to(REPO_ROOT))
            entry["sha8"] = _sha8(url, body)
            entry["quality"] = quality
            n_total_nodes += n_nodes
            n_successful += 1
            print(f"[ingest] OK   {url}  ->  {entry['out']}  ({n_nodes} nodes, quality={quality})")
        except Exception as e:  # noqa: BLE001
            entry["error"] = f"parse_failed: {type(e).__name__}: {e}"
            print(f"[ingest] PARSE-FAIL  {url}  ->  {entry['error']}", file=sys.stderr)
    else:
        print(f"[ingest] FETCH-FAIL  {url}  ->  status={status} err={err}", file=sys.stderr)

    results.append(entry)

    # Polite gap between requests (skip on the last one)
    if i < len(URLS) - 1:
        # Respect the wall deadline too — don't sleep past it
        remaining = WALL_DEADLINE - (time.monotonic() - start)
        if remaining > 0:
            time.sleep(min(SLEEP_BETWEEN, max(0.0, remaining - 0.1)))

# -------------------------------------------------------------------------
# Summary INDEX + one summary crystal anchor
# -------------------------------------------------------------------------
generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
summary = {
    "generated_at": generated_at,
    "urls_attempted": len(URLS),
    "urls_successful": n_successful,
    "total_cursor_nodes": n_total_nodes,
    "wall_elapsed_s": round(time.monotonic() - start, 2),
    "results": results,
    "ingest_crystal": "",  # filled in below after logger call
}

index_path = OUT_DIR / "INDEX.json"
index_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

# Log the run-level crystal anchor. Best-effort — never block the ingest.
ingest_crystal = ""
try:
    from inference_logger import InferenceLogger
    logger = InferenceLogger()
    payload = {
        "generated_at": generated_at,
        "urls_attempted": len(URLS),
        "urls_successful": n_successful,
        "total_cursor_nodes": n_total_nodes,
        "per_url": [
            {"url": r["url"], "status": r["status"], "ok": r["ok"], "n_nodes": r["n_nodes"]}
            for r in results
        ],
    }
    ingest_crystal = logger.log(
        original_prompt="facebook_games_docs",
        enhanced_prompt="doc_parser:facebook_games",
        output_text=json.dumps(payload, separators=(",", ":"))[:8192],
        tier="documentation",
        model="doc_parser:facebook_games",
        scope="games_ingest_run",
        tokens_in=0,
        tokens_out=n_total_nodes,
        complexity=0.0,
        done_flag=True,
        rc=0 if n_successful > 0 else 1,
        source_file="",
        source_folder=str(OUT_DIR.relative_to(REPO_ROOT)),
        source_action="facebook_games_ingest",
        source_step=0,
    )
    summary["ingest_crystal"] = ingest_crystal
    # Rewrite INDEX.json with the crystal attached
    index_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"[ingest] crystal={ingest_crystal}")
except Exception as e:  # noqa: BLE001
    print(f"[ingest] crystal anchor failed: {e}", file=sys.stderr)

print(json.dumps({
    "ok": n_successful > 0,
    "urls_attempted": len(URLS),
    "urls_successful": n_successful,
    "total_cursor_nodes": n_total_nodes,
    "index": str(index_path.relative_to(REPO_ROOT)),
    "ingest_crystal": ingest_crystal,
}, indent=2))

# Exit non-zero only if EVERY URL failed (so re-runs still complete partial
# corpora when Meta lets some pages through).
sys.exit(0 if n_successful > 0 else 2)
PYEOF
rc=$?

echo
echo "=== facebook_games_ingest done (rc=${rc}) ==="
exit "${rc}"
