"""Friend-scoped access control for MySpace++ Studio.

Not enterprise auth. Designed to gate GPU/app access to a fixed list of
known friends already authenticated at the SSH layer. See README.md for
the threat model.
"""

from .gate import require_login, get_client_ip, AuthResult  # noqa: F401

__all__ = ["require_login", "get_client_ip", "AuthResult"]
