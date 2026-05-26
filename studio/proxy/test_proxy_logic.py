"""test_proxy_logic.py — exercise the proxy's auth/log/rate-limit logic
without actually hitting Anthropic.

Tests the pieces that don't need network:
  1. _require_token rejects missing/invalid/non-claude tokens
  2. rate limit triggers at the configured ceiling
  3. assert_distribute_within_cap enforces MAX_ACTIVE_TOKENS=2

Skips: actual /v1/messages forwarding (would need a fake httpx fixture).
"""
from __future__ import annotations
import os
import tempfile
import unittest
from pathlib import Path

# Isolate a temp keys DB before importing.
TMP = Path(tempfile.mkdtemp(prefix="myspace-proxy-test-"))
os.environ["MYSPACE_KEYS_DB"] = str(TMP / "keys.sqlite")
os.environ["MYSPACE_KEY_MASTER"] = "test-master-do-not-use"
os.environ["MYSPACE_MAX_CLAUDE_TOKENS"] = "2"
os.environ["MYSPACE_RATE_LIMIT"] = "3"

# Need to point .env path away from the real one so kind=claude lookups
# succeed in tests too (they only check the registry, not upstream).
os.environ["MYSPACE_ENV_PATH"] = str(TMP / "fake.env")
(TMP / "fake.env").write_text("claude_guest=sk-test-placeholder\n")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth import keys  # noqa: E402

try:
    from fastapi import HTTPException
    import claude_proxy as cp  # noqa: E402
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx not installed — proxy tests skipped")
class ProxyLogicTests(unittest.TestCase):

    def test_01_require_token_missing(self):
        with self.assertRaises(cp.HTTPException) as cm:
            cp._require_token(None)
        self.assertEqual(cm.exception.status_code, 401)

    def test_02_require_token_invalid_string(self):
        with self.assertRaises(cp.HTTPException) as cm:
            cp._require_token("not-a-token")
        self.assertEqual(cm.exception.status_code, 401)

    def test_03_require_token_wrong_kind(self):
        tok = keys.distribute_token("Jamie", "pinterest")
        with self.assertRaises(cp.HTTPException) as cm:
            cp._require_token(tok)
        self.assertEqual(cm.exception.status_code, 403)

    def test_04_require_token_revoked(self):
        tok = keys.distribute_token("Bronco", "claude")
        # parse token_id out
        tid = tok.split("_")[2]
        keys.revoke_token(tid)
        with self.assertRaises(cp.HTTPException) as cm:
            cp._require_token(tok)
        self.assertEqual(cm.exception.status_code, 401)

    def test_05_rate_limit(self):
        tok = keys.distribute_token("Pete", "claude")
        # First 3 calls succeed (MYSPACE_RATE_LIMIT=3 in setUp env)
        for _ in range(3):
            cp._require_token(tok)
        # 4th raises 429
        with self.assertRaises(cp.HTTPException) as cm:
            cp._require_token(tok)
        self.assertEqual(cm.exception.status_code, 429)

    def test_06_max_active_cap(self):
        # Drain any existing actives so the cap math is deterministic.
        for t in keys.list_tokens():
            if t.kind == "claude":
                keys.revoke_token(t.token_id)
        # Issue 2 — within cap
        cp.assert_distribute_within_cap("Ashley")
        keys.distribute_token("Ashley", "claude")
        cp.assert_distribute_within_cap("Mike")
        keys.distribute_token("Mike", "claude")
        # Issue 3rd — over cap
        with self.assertRaises(RuntimeError) as cm:
            cp.assert_distribute_within_cap("Steph")
        self.assertIn("cap is 2", str(cm.exception))


def tearDownModule():
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
