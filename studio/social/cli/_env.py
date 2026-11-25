"""_env.py — shared .env loader for all social CLIs.

Reads /data/Projects/MySpace++/.env (or CC_PROJECT_ROOT/.env) and
gives each CLI typed access to its platform keys.
"""
from __future__ import annotations

import os
from pathlib import Path


def _find_env() -> Path:
    root = Path(os.environ.get("CC_PROJECT_ROOT", "/data/Projects/MySpace++"))
    env = root / ".env"
    if env.exists():
        return env
    # Fallback: walk up from this file
    here = Path(__file__).resolve().parent.parent.parent.parent
    return here / ".env"


def load_env() -> dict[str, str]:
    """Parse .env into a dict."""
    env_path = _find_env()
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for ln in env_path.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        out[k.strip()] = v.strip()
    return out


def key(name: str, default: str = "") -> str:
    return load_env().get(name, default)
