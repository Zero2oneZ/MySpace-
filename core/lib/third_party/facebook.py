#!/usr/bin/env python3
"""facebook.py — Facebook outbound connector.

Dependency: `pip install facebook-sdk`
Without it: falls back to _StubConnector.
"""
from __future__ import annotations

import time
from typing import Dict, List, Any

from .base import ThirdPartyConnector, ConnectionConfig, SendResult


class FacebookConnector(ThirdPartyConnector):
    SERVICE = "facebook"

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self._api: Any = None
        self._access_token: str = config.auth.get("access_token", "")
        self._page_id: str = config.auth.get("page_id", "")

    def connect(self) -> str:
        try:
            import facebook
            self._api = facebook.GraphAPI(access_token=self._access_token)
            self._connected = True
            return "facebook_connected"
        except Exception as e:
            self._connected = False
            return f"facebook_sdk_missing:{e}"

    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        self._rate_limit_wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self._connected or self._api is None:
            result = SendResult(
                success=False,
                crystal_id="facebook_stub_" + str(hash(recipient + message + ts)),
                service="facebook",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
                error="facebook-sdk not installed or not connected",
            )
            self._log_send(result)
            return result

        try:
            target = recipient if recipient else self._page_id
            resp = self._api.put_object(parent_object=target, connection_name="feed", message=message)
            result = SendResult(
                success=True,
                crystal_id="facebook_" + str(hash(target + message + ts)),
                service="facebook",
                recipient=target,
                message_preview=message[:120],
                timestamp=ts,
                metadata={"post_id": resp.get("id", "")},
            )
        except Exception as e:
            result = SendResult(
                success=False,
                crystal_id="facebook_err_" + str(hash(recipient + message + ts)),
                service="facebook",
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
        return "facebook_disconnected"
