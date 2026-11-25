#!/usr/bin/env python3
"""whatsapp.py — WhatsApp outbound connector.

Dependency: `pip install pywhatkit` (for simple sends) or `meta-sdk` for Business API.
Without it: falls back to _StubConnector.
"""
from __future__ import annotations

import time
from typing import Dict, List, Any

from .base import ThirdPartyConnector, ConnectionConfig, SendResult


class WhatsAppConnector(ThirdPartyConnector):
    SERVICE = "whatsapp"

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self._phone_id: str = config.auth.get("phone_id", "")
        self._access_token: str = config.auth.get("access_token", "")

    def connect(self) -> str:
        if self._access_token and self._phone_id:
            self._connected = True
            return "whatsapp_connected"
        return "whatsapp_no_credentials"

    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        self._rate_limit_wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self._connected:
            result = SendResult(
                success=False,
                crystal_id="whatsapp_stub_" + str(hash(recipient + message + ts)),
                service="whatsapp",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
                error="WhatsApp not connected (missing credentials)",
            )
            self._log_send(result)
            return result

        # Try Meta Business API first
        try:
            import requests
            url = f"https://graph.facebook.com/v18.0/{self._phone_id}/messages"
            headers = {"Authorization": f"Bearer {self._access_token}", "Content-Type": "application/json"}
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"body": message},
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            result = SendResult(
                success=resp.status_code == 200,
                crystal_id="whatsapp_" + str(hash(recipient + message + ts)),
                service="whatsapp",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
                metadata={"status_code": resp.status_code, "body": resp.text[:200]},
            )
        except Exception as e:
            result = SendResult(
                success=False,
                crystal_id="whatsapp_err_" + str(hash(recipient + message + ts)),
                service="whatsapp",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
                error=str(e),
            )
        self._log_send(result)
        return result

    def history(self, thread_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return []

    def disconnect(self) -> str:
        self._connected = False
        return "whatsapp_disconnected"
