#!/usr/bin/env python3
"""discord.py — Discord outbound connector.

Dependency: `pip install discord.py`
Without it: falls back to _StubConnector.
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Any, Optional

from .base import ThirdPartyConnector, ConnectionConfig, SendResult


class DiscordConnector(ThirdPartyConnector):
    SERVICE = "discord"

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self._client: Optional[Any] = None
        self._token: str = config.auth.get("bot_token", "")

    def connect(self) -> str:
        try:
            import discord
        except Exception as e:
            self._connected = False
            return f"discord.py_missing:{e}"

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._connected = True
        return "discord_connected"

    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        self._rate_limit_wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self._connected or self._client is None:
            result = SendResult(
                success=False,
                crystal_id="discord_stub_" + str(hash(recipient + message + ts)),
                service="discord",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
                error="discord.py not installed or not connected",
            )
            self._log_send(result)
            return result

        try:
            import asyncio
            async def _send():
                channel = self._client.get_channel(int(recipient))
                if channel is None:
                    user = await self._client.fetch_user(int(recipient))
                    if user:
                        await user.send(message)
                        return "dm"
                    return "not_found"
                await channel.send(message)
                return "channel"

            loop = asyncio.get_event_loop()
            sent_to = loop.run_until_complete(_send())
            result = SendResult(
                success=True,
                crystal_id="discord_" + str(hash(recipient + message + ts)),
                service="discord",
                recipient=recipient,
                message_preview=message[:120],
                timestamp=ts,
                metadata={"sent_to": sent_to},
            )
        except Exception as e:
            result = SendResult(
                success=False,
                crystal_id="discord_err_" + str(hash(recipient + message + ts)),
                service="discord",
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
        if self._client:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                loop.run_until_complete(self._client.close())
            except Exception:
                pass
        return "discord_disconnected"
