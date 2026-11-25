#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        freetier_callback_server
# role:        HTTP · PUBLIC_SURFACE_FOR_BOTH_DOMAINS
# tier:        L0
# substrate:   the only public HTTP entry to MySpace++/GentlyOS — single port,
#              routed by Host header to either GentlyOS.io or trollz.fun
# storage:     templates rendered fresh per request; tokens via freetier_gate
# ----------------------------------------------------------------------------
# ROUTING (Host header)
# ----------------------------------------------------------------------------
# Host: GentlyOS.io        Host: trollz.fun
#   GET  /endpoint/freetier/terms/                  GET  /terms/
#   GET  /endpoint/freetier/terms/policies/         GET  /terms/policies/
#   POST /endpoint/freetier/terms/policies/callback/   POST /terms/policies/callback/
#   GET  /endpoint/freetier/terms/policies/callback/   (form submit fallback)
#   GET  /healthz                                    GET  /healthz
# ----------------------------------------------------------------------------
# Everything else returns 404. The proprietary MCP surface is NOT served here.
# ============================================================================
"""freetier_callback_server.py — public-facing HTTP server for the two domains.

Stdlib only (http.server.ThreadingHTTPServer). Routes by Host header to the
appropriate template family (GentlyOS.io or trollz.fun). On valid POST to the
callback URL, calls freetier_gate.record_acceptance + issue_token and renders
the success page with the issued token displayed for the user to save.

Run locally:
    python3 studio/endpoints/freetier_callback/server.py --port 8540

Test with curl against the GentlyOS family:
    curl -H "Host: GentlyOS.io" http://localhost:8540/endpoint/freetier/terms/
    curl -H "Host: GentlyOS.io" http://localhost:8540/endpoint/freetier/terms/policies/
    curl -H "Host: GentlyOS.io" -X POST \
      -d "user_id=tom_dev&accepted=true" \
      http://localhost:8540/endpoint/freetier/terms/policies/callback/

Test trollz family:
    curl -H "Host: trollz.fun" http://localhost:8540/terms/
    curl -H "Host: trollz.fun" http://localhost:8540/terms/policies/
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "core" / "lib"))

# freetier_gate is the auth substrate; record + issue tokens.
from freetier_gate import (  # type: ignore  # noqa: E402
    DOMAINS,
    record_acceptance,
    issue_token,
    verify_token,
)

TEMPLATES = _HERE / "templates"


# ---------------------------------------------------------------------------
# Domain branding (mirrors DOMAINS but adds presentation params)
# ---------------------------------------------------------------------------

BRANDING: Dict[str, Dict[str, str]] = {
    "GentlyOS.io": {
        "brand_name":  "GentlyOS",
        "brand_sub":   ".io · free tier",
        "brand_mark":  "G",
        "brand_bg":    "#5b8def",
        "brand_fg":    "#ffffff",
        "theme_color": "#5b8def",
        "terms_path":     "/endpoint/freetier/terms/",
        "policies_path":  "/endpoint/freetier/terms/policies/",
        "callback_path":  "/endpoint/freetier/terms/policies/callback/",
        "terms_template":      "gently_terms.html",
        "policies_template":   "gently_policies.html",
        "callback_template":   "gently_callback_ok.html",
    },
    "trollz.fun": {
        "brand_name":  "trollz",
        "brand_sub":   ".fun · TROLLN ecosystem",
        "brand_mark":  "T",
        "brand_bg":    "#e53935",
        "brand_fg":    "#ffffff",
        "theme_color": "#e53935",
        "terms_path":     "/terms/",
        "policies_path":  "/terms/policies/",
        "callback_path":  "/terms/policies/callback/",
        "terms_template":      "trollz_terms.html",
        "policies_template":   "trollz_policies.html",
        "callback_template":   "trollz_callback_ok.html",
    },
}

# Path → (domain, kind) routing.
def _route(host: str, path: str) -> Optional[Tuple[str, str]]:
    """Return (domain, kind) where kind ∈ {terms, policies, callback, healthz}.
    Or None if no match — caller responds 404."""
    host_norm = (host or "").split(":", 1)[0].strip().lower()
    # Match canonical forms first; localhost falls through to first matching path.
    # Note: Host header carries the actual hostname; canonical keys in DOMAINS are case-preserved.
    candidates = [k for k in DOMAINS.keys() if k.lower() == host_norm]
    domain = candidates[0] if candidates else ""

    # If host doesn't match a known domain, try to infer from path
    # (lets curl smoke without setting Host correctly).
    if not domain:
        if path.startswith("/endpoint/freetier/"):
            domain = "GentlyOS.io"
        elif path.startswith("/terms/"):
            domain = "trollz.fun"
        else:
            return None
    branding = BRANDING[domain]
    if path == branding["terms_path"]:
        return (domain, "terms")
    if path == branding["policies_path"]:
        return (domain, "policies")
    if path == branding["callback_path"]:
        return (domain, "callback")
    if path == "/healthz":
        return (domain, "healthz")
    return None


# ---------------------------------------------------------------------------
# Template render (string.Template-style, stdlib-only)
# ---------------------------------------------------------------------------

def _read_template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _substitute(text: str, mapping: Dict[str, str]) -> str:
    for k, v in mapping.items():
        text = text.replace("{" + k + "}", v)
    return text


def _render_page(domain: str, inner_template: str, inner_vars: Dict[str, str]) -> str:
    branding = BRANDING[domain]
    inner = _substitute(_read_template(inner_template),
                          {**branding, **inner_vars})
    page_vars = {**branding, "content": inner, "title": branding["brand_name"] + " · " + inner_template.replace("_", " ").replace(".html", "")}
    return _substitute(_read_template("base.html"), page_vars)


# ---------------------------------------------------------------------------
# Terms / Policies hashes (deterministic per text)
# ---------------------------------------------------------------------------

def _terms_hash(domain: str) -> str:
    branding = BRANDING[domain]
    text = _read_template(branding["terms_template"])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _policies_hash(domain: str) -> str:
    branding = BRANDING[domain]
    text = _read_template(branding["policies_template"])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _combined_terms_hash(domain: str) -> str:
    """The hash baked into the issued token's accepted_terms_hash claim."""
    return hashlib.sha256(
        (_terms_hash(domain) + _policies_hash(domain)).encode("utf-8")
    ).hexdigest()[:32]


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class FreetierCallbackHandler(BaseHTTPRequestHandler):
    server_version = "FreetierCallback/0.1"

    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8",
                extra_headers: Optional[Dict[str, str]] = None) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(encoded)

    def _client_ip(self) -> str:
        # Behind Caddy/reverse-proxy, prefer X-Forwarded-For.
        xff = self.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        host = self.headers.get("Host", "")
        parsed = urllib.parse.urlparse(self.path)
        route = _route(host, parsed.path)
        if not route:
            self._send(404, "<h1>404</h1><p>Path not exposed on this host.</p>")
            return
        domain, kind = route

        if kind == "healthz":
            self._send(200, json.dumps({"ok": True, "domain": domain}),
                          content_type="application/json")
            return

        branding = BRANDING[domain]
        if kind == "terms":
            page = _render_page(domain, branding["terms_template"],
                                 {"terms_hash": _terms_hash(domain)})
            self._send(200, page)
            return
        if kind == "policies":
            page = _render_page(domain, branding["policies_template"],
                                 {"policies_hash": _policies_hash(domain)})
            self._send(200, page)
            return
        if kind == "callback":
            # GET fallback — render the policies page so the user has a form.
            page = _render_page(domain, branding["policies_template"],
                                 {"policies_hash": _policies_hash(domain)})
            self._send(405, page,
                          extra_headers={"Allow": "POST"})
            return

    def do_POST(self) -> None:  # noqa: N802
        host = self.headers.get("Host", "")
        parsed = urllib.parse.urlparse(self.path)
        route = _route(host, parsed.path)
        if not route or route[1] != "callback":
            self._send(404, "<h1>404</h1>")
            return
        domain, _ = route
        branding = BRANDING[domain]

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        form = dict(urllib.parse.parse_qsl(body, keep_blank_values=False))

        user_id = (form.get("user_id") or "").strip()[:128]
        accepted = (form.get("accepted") or "").strip().lower() in ("true", "on", "1", "yes")
        # Optional: Facebook user_friends scope harvest consent. Defaults to False
        # if the box is unchecked — users still get a valid token, just without
        # the friends_consent claim. The friends-graph harvester gates on this.
        friends_consent = (form.get("friends_consent") or "").strip().lower() in ("true", "on", "1", "yes")

        is_htmx = self.headers.get("HX-Request", "").lower() == "true"

        if not user_id or not accepted:
            err_html = _substitute(
                _read_template("error.html"),
                {
                    "message": "Both fields are required: an identifier you control AND the acceptance checkbox.",
                    "back_url": html.escape(branding["policies_path"]),
                    "brand_bg": branding["brand_bg"],
                },
            )
            if is_htmx:
                self._send(400, err_html)
                return
            page = _render_page(domain, branding["policies_template"],
                                 {"policies_hash": _policies_hash(domain),
                                  "content_extra": err_html})
            self._send(400, page)
            return

        # Record acceptance + issue token. Both crystal-anchor.
        terms_hash = _combined_terms_hash(domain)
        ip = self._client_ip()
        ua = self.headers.get("User-Agent", "")[:120]
        try:
            crystal_id = record_acceptance(
                user_id=user_id, domain=domain,
                ip=ip, user_agent=ua,
                accepted_terms_hash=terms_hash,
                friends_consent=friends_consent,
            )
            token = issue_token(
                user_id=user_id, domain=domain,
                accepted_terms_hash=terms_hash,
                ttl_seconds=30 * 24 * 3600,
                friends_consent=friends_consent,
            )
        except Exception as e:
            sys.stderr.write(f"acceptance failed for {user_id}@{domain}: {e}\n")
            err_html = _substitute(
                _read_template("error.html"),
                {
                    "message": f"Server error issuing token: {html.escape(type(e).__name__)}. Try again, and if it persists report the issue.",
                    "back_url": html.escape(branding["policies_path"]),
                    "brand_bg": branding["brand_bg"],
                },
            )
            self._send(500, err_html)
            return

        friends_consent_label = (
            "AUTHORIZED"
            if friends_consent
            else "not authorized — you can re-sign anytime to enable"
        )
        cb_vars = {
            "user_id":       html.escape(user_id),
            "tier":          html.escape(DOMAINS[domain]["tier"]),
            "crystal_short": html.escape(crystal_id[:16]) if crystal_id else "(none)",
            "token":         html.escape(token),
            "token_short":   html.escape(token[:20]),
            "friends_consent_label": html.escape(friends_consent_label),
        }
        inner = _substitute(_read_template(branding["callback_template"]),
                              {**branding, **cb_vars})

        if is_htmx:
            # Return just the inner panel (HTMX swaps into #result)
            self._send(200, inner)
            return

        # Full page render with the success panel as content
        full = _substitute(
            _read_template("base.html"),
            {
                **branding,
                "title": branding["brand_name"] + " · session token issued",
                "content": inner,
            },
        )
        self._send(200, full,
                      extra_headers={
                          "Set-Cookie": f"freetier_token={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={30*24*3600}",
                      })

    def log_message(self, format: str, *args) -> None:
        # Compact one-line access log to stderr; respects FREETIER_LOG=quiet to suppress.
        if os.environ.get("FREETIER_LOG", "") == "quiet":
            return
        host = self.headers.get("Host", "-")
        sys.stderr.write(f"{self.address_string()} {host} {format % args}\n")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="freetier_callback_server")
    ap.add_argument("--port", type=int,
                      default=int(os.environ.get("FREETIER_PORT", "8540")))
    ap.add_argument("--bind", default="127.0.0.1",
                      help="bind address; use 0.0.0.0 only behind Caddy/firewall")
    args = ap.parse_args()

    sys.stderr.write(
        f"freetier_callback_server listening on {args.bind}:{args.port}\n"
        f"  GentlyOS.io routes: /endpoint/freetier/{{terms/, terms/policies/, terms/policies/callback/}}\n"
        f"  trollz.fun routes:  /{{terms/, terms/policies/, terms/policies/callback/}}\n"
        f"  /healthz on either host\n"
    )
    srv = ThreadingHTTPServer((args.bind, args.port), FreetierCallbackHandler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
