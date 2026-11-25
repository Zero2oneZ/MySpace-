#!/usr/bin/env python3
"""telegram.py — Telegram outbound connector.

Dependency: `pip install python-telegram-bot`
Without it: falls back to _StubConnector.
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Any, Optional

from .base import ThirdPartyConnector, ConnectionConfig, SendResult


class TelegramConnector(ThirdPartyConnector):
    SERVICE = "telegram"

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self._bot: Optional[Any] = None
        self._token: str = config.auth.get("bot_token", "")

    def connect(self) -> str:
        try:
            from telegram import Bot
            self._bot = Bot(token=self._token)
            self._connected = True
            return "telegram_connected"
        except Exception as e:
            self._connected = False
            return f"telegram_lib_missing:{e}"

    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        self._rate_limit_wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self._connected or self._bot is None:
            result = SendResult(
                success=False,
                crystal_id="telegram_stub_" + str(hash(recipient + message + ts)),
                service="telegram",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
                error="python-telegram-bot not installed or not connected",
            )
            self._log_send(result)
            return result

        try:
            import asyncio
            async def _send():
                await self._bot.send_message(chat_id=recipient, text=message)
            loop = asyncio.get_event_loop()
            loop.run_until_complete(_send())
            result = SendResult(
                success=True,
                crystal_id="telegram_" + str(hash(recipient + message + ts)),
                service="telegram",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
            )
        except Exception as e:
            result = SendResult(
                success=False,
                crystal_id="telegram_err_" + str(hash(recipient + message + ts)),
                service="telegram",
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
        return "telegram_disconnected"
