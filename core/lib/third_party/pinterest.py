#!/usr/bin/env python3
"""pinterest.py — Pinterest outbound + search connector.

Mirrors the discord/telegram/twitter connector pattern under third_party/.
Wraps the existing studio/pinterest/client.PinterestClient for the heavy lift.

Auth: API key in $PINTREST_API (note: legacy spelling — matches MySpace++/.env).
Falls back to /search scrape if the API key is missing.

Used by:
  - workflow_card pinterest_blueprint_harvest (curated boards: blueprints,
    furniture, interior design)
  - endpoints.RoutingOperator when action=fetch_pinterest
  - Direct CLI: python3 third_party_cli.py send --service pinterest --to <query> ...
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import ThirdPartyConnector, ConnectionConfig, SendResult


# Make studio/ importable so we can reuse the existing PinterestClient.
_REPO = Path(__file__).resolve().parents[3]
_STUDIO = _REPO / "studio"
if str(_STUDIO) not in sys.path:
    sys.path.insert(0, str(_STUDIO))


# Curated query templates for real estate / avatar / interior design.
CURATED_QUERIES = {
    "blueprint":      ["floor plan", "architectural blueprint", "house plan"],
    "furniture":      ["modern furniture", "mid-century chair", "scandinavian sofa"],
    "interior":       ["minimalist living room", "modern bedroom", "luxury apartment interior"],
    "exterior":       ["modern home exterior", "contemporary architecture", "luxury villa"],
    "lighting":       ["pendant lighting design", "warm interior lighting"],
    "kitchen":        ["modern kitchen design", "minimalist kitchen"],
    "avatar_ref":     ["character design reference", "human pose reference"],
    "style_ref":      ["fashion editorial", "streetwear lookbook"],
}


class PinterestConnector(ThirdPartyConnector):
    SERVICE = "pinterest"

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        # Token preference: explicit auth.token → $PINTREST_API → empty (scrape fallback)
        self._token: str = (
            (config.auth or {}).get("token")
            or (config.auth or {}).get("api_key")
            or os.environ.get("PINTREST_API")
            or os.environ.get("PINTEREST_API")
            or ""
        )
        self._client: Optional[Any] = None

    # ---- lifecycle -------------------------------------------------

    def connect(self) -> str:
        try:
            from pinterest.client import PinterestClient  # studio/pinterest/client.py
        except Exception as e:
            self._connected = False
            return f"pinterest_client_missing:{type(e).__name__}"

        try:
            self._client = PinterestClient(api_token=self._token or None)
            self._connected = True
            mode = "api" if self._token else "scrape"
            return f"pinterest_connected_{mode}"
        except Exception as e:
            self._connected = False
            return f"pinterest_connect_failed:{type(e).__name__}"

    def disconnect(self) -> str:
        self._client = None
        self._connected = False
        return "pinterest_disconnected"

    # ---- main op ---------------------------------------------------

    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        """For Pinterest, 'send' = 'search'. recipient = query, message = unused.

        Reuses the existing studio.pinterest.client.PinterestClient.search().
        Returns a SendResult whose `data` field carries the pin list.
        """
        self._rate_limit_wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        query = recipient

        if not self._connected or self._client is None:
            connect_status = self.connect()
            if not self._connected:
                result = SendResult(
                    success=False,
                    crystal_id="pinterest_disconnected_" + str(hash(query + ts)),
                    service="pinterest",
                    recipient=query,
                    message_preview=message[:120],
                    timestamp=ts,
                    error=f"could not connect: {connect_status}",
                )
                self._log_send(result)
                return result

        try:
            pins = self._client.search(query, limit=int(kwargs.get("limit", 20)))
            data = [
                {
                    "id": getattr(p, "id", None),
                    "title": getattr(p, "title", "") or "",
                    "description": (getattr(p, "description", "") or "")[:300],
                    "image_url": getattr(p, "image_url", "") or "",
                    "source_url": getattr(p, "source_url", "") or "",
                }
                for p in (pins or [])
            ]
        except Exception as e:
            result = SendResult(
                success=False,
                crystal_id="pinterest_search_failed_" + str(hash(query + ts)),
                service="pinterest",
                recipient=query,
                message_preview=message[:120],
                timestamp=ts,
                error=f"{type(e).__name__}: {e}",
            )
            self._log_send(result)
            return result

        result = SendResult(
            success=True,
            crystal_id="pinterest_search_" + str(hash(query + ts)),
            service="pinterest",
            recipient=query,
            message_preview=f"{len(data)} pins for '{query}'",
            timestamp=ts,
            data=data,
        )
        self._log_send(result)
        return result

    # ---- convenience: curated harvest -----------------------------

    def harvest_curated(self, category: str, limit_per_query: int = 5) -> Dict[str, List[Dict]]:
        """Run a curated batch of queries for a category (blueprint, furniture, etc.)
        and aggregate the pins by query. Returns {query: [pin_dict, ...]}."""
        queries = CURATED_QUERIES.get(category)
        if not queries:
            return {}
        out: Dict[str, List[Dict]] = {}
        for q in queries:
            r = self.send(q, "", limit=limit_per_query)
            out[q] = r.data if (r.success and r.data) else []
            time.sleep(0.4)  # gentle pacing
        return out

    def history(self, recipient: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Read past send-logs for the pinterest connector."""
        return self._read_log_tail(limit)
