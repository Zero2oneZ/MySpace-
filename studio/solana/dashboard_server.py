"""dashboard_server.py — Tiny HTTP server for the Pattern Intelligence Dashboard.

Serves dashboard.html and JSON data files with CORS headers.
Auto-refreshes when data changes.

Usage:
    python3 dashboard_server.py --port 8765
    cc -pattern-dashboard
"""
from __future__ import annotations

import argparse
import json
import os
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        self.base_dir = directory or str(HERE)
        super().__init__(*args, directory=self.base_dir, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Suppress noisy logs
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # API endpoint: live stats
        if path == "/api/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            summary_path = HERE / "feed" / "orchestration_summary.json"
            model_path = HERE / "feed" / "pattern_model.json"
            stats = {
                "timestamp": time.time(),
                "summary_exists": summary_path.exists(),
                "model_exists": model_path.exists(),
            }
            if summary_path.exists():
                try:
                    with open(summary_path) as f:
                        s = json.load(f)
                    stats.update({
                        "total_contracts": s.get("total_contracts", 0),
                        "self_activating": s.get("self_activating_contracts", 0),
                        "recursive_cycles": s.get("recursive_cycles", 0),
                        "deep_chains": s.get("deep_chains", 0),
                        "pattern_count": len(s.get("patterns", [])),
                    })
                except Exception as e:
                    stats["error"] = str(e)
            self.wfile.write(json.dumps(stats).encode())
            return

        # Default: serve files from base_dir
        super().do_GET()


def run_server(port: int = 8767):
    os.chdir(str(HERE))
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"[dashboard] Serving at http://localhost:{port}")
    print(f"[dashboard] Base dir: {HERE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopped")
        server.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8767)
    args = ap.parse_args()
    run_server(args.port)


if __name__ == "__main__":
    main()
