#!/usr/bin/env python3
"""third_party — outbound connectivity to external messaging & social platforms.

Deterministic-first: every connection is a config file on disk.
State transitions by `mv`: active → paused → archived.
Every send is logged append-only JSONL with crystal hash.
"""
from .base import ThirdPartyConnector, ConnectionConfig, SendResult
from .manager import ThirdPartyManager

__all__ = ["ThirdPartyConnector", "ConnectionConfig", "SendResult", "ThirdPartyManager"]
