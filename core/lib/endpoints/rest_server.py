#!/usr/bin/env python3
"""rest_server.py — Minimal REST inbound listener.

Uses stdlib http.server. Expects JSON POST bodies.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Dict, List, Any

from .base import EndpointListener, EndpointConfig, ReceiveEvent


class RestListener(EndpointListener):
    KIND = "rest"
    SERVICE = "generic"

    def __init__(self, config: EndpointConfig):
        super().__init__(config)
        self._server: Any = None
        self._thread: Any = None

    def start(self) -> str:
        try:
            import threading
            import http.server
            import socketserver

            host = self.config.bind.get("host", "0.0.0.0")
            port = int(self.config.bind.get("port", 9001))
            base = self.config.bind.get("path", "/api/v1")

            class _Handler(http.server.BaseHTTPRequestHandler):
                listener = self
                base_path = base

                def do_GET(self):
                    if not self.path.startswith(self.base_path):
                        self.send_response(404)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "status": "ok",
                        "listener": self.listener.config.name,
                        "health": self.listener.health(),
                    }).encode())

                def do_POST(self):
                    if not self.path.startswith(self.base_path):
                        self.send_response(404)
                        self.end_headers()
                        return
                    content_len = int(self.headers.get("Content-Length", 0))
                    raw_body = self.rfile.read(content_len).decode("utf-8", errors="replace")
                    try:
                        body = json.loads(raw_body)
                    except Exception:
                        body = {"raw": raw_body}

                    event = self.listener.receive({
                        "headers": dict(self.headers),
                        "body": body,
                        "source_ip": self.client_address[0],
                    })

                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "received": True,
                        "crystal_id": event.crystal_id,
                        "tag": event.tag,
                        "route": event.matched_route,
                    }).encode())

                def log_message(self, format, *args):
                    pass

            self._server = socketserver.TCPServer((host, port), _Handler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            self._running = True
            self._start_ts = time.time()
            return f"rest_started_{host}:{port}{base}"
        except Exception as e:
            return f"rest_start_failed:{e}"

    def stop(self) -> str:
        if self._server:
            self._server.shutdown()
        self._running = False
        return "rest_stopped"

    def receive(self, raw_request: Dict[str, Any]) -> ReceiveEvent:
        body = raw_request.get("body", {})
        tag = body.get("tag", body.get("event", "rest_inbound"))
        crystal = hashlib.sha256(json.dumps(raw_request, sort_keys=True, default=str).encode()).hexdigest()
        event = ReceiveEvent(
            crystal_id=crystal,
            endpoint_asset_id=self.config.asset_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            source_ip=raw_request.get("source_ip", "0.0.0.0"),
            headers=raw_request.get("headers", {}),
            body=body,
            tag=tag,
        )
        self._log_receive(event)
        return event

    def health(self) -> Dict[str, Any]:
        h = super().health()
        h["port"] = self.config.bind.get("port", 0)
        return h
