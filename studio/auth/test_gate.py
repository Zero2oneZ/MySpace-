"""test_gate.py — exercises auth.gate.verify() with mock IPs + a temp store.

Tests every documented path:
  1. First login binds IP + sets bind_hash
  2. Re-login from same IP succeeds
  3. Re-login from a DIFFERENT IP fails
  4. The `localhost` row only accepts a loopback IP
  5. Wrong password is rejected
  6. Solo email path works for a null-username row
  7. Re-seeding the store preserves existing bindings (idempotency)

Run:
    python test_gate.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Point the gate + seed scripts at an isolated permissions file before importing.
TMPDIR = Path(tempfile.mkdtemp(prefix="myspace-auth-test-"))
TEST_PERMS = TMPDIR / "permissions.jsonl"
os.environ["MYSPACE_PERMISSIONS_PATH"] = str(TEST_PERMS)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gate  # noqa: E402  (after env var set)
import seed_permissions as sp  # noqa: E402

# Force seed module to use the same path the gate is reading.
sp.PERMISSIONS_PATH = TEST_PERMS


def reseed():
    """Wipe + seed fresh, preserving the seed schema."""
    if TEST_PERMS.exists():
        TEST_PERMS.unlink()
    rows = sp.merge(sp.SEED, [])
    sp.write(rows)


class GateTests(unittest.TestCase):

    def setUp(self):
        reseed()

    def test_01_first_login_binds_ip(self):
        r = gate.verify("Jamie", "passwd", "10.0.0.5")
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.user, "Jamie")
        self.assertEqual(r.ip, "10.0.0.5")
        self.assertEqual(r.reason, "first-login bind")
        row = gate.find_user("Jamie")
        self.assertEqual(row["ip_bound"], "10.0.0.5")
        self.assertTrue(row["bind_hash"])
        self.assertEqual(row["bind_hash"], gate.bind_hash("Jamie", "10.0.0.5"))

    def test_02_relogin_same_ip(self):
        gate.verify("Bronco", "passwd", "10.0.0.6")   # first
        r = gate.verify("Bronco", "passwd", "10.0.0.6")  # second
        self.assertTrue(r.ok, r.reason)
        self.assertNotEqual(r.reason, "first-login bind")  # second time

    def test_03_relogin_different_ip_fails(self):
        gate.verify("Pete", "passwd", "10.0.0.7")
        r = gate.verify("Pete", "passwd", "10.0.0.99")
        self.assertFalse(r.ok)
        self.assertIn("IP mismatch", r.reason or "")

    def test_04_localhost_loopback_only(self):
        r_ok   = gate.verify("localhost", None, "127.0.0.1")
        r_bad  = gate.verify("localhost", None, "10.0.0.123")
        self.assertTrue(r_ok.ok, r_ok.reason)
        self.assertFalse(r_bad.ok)
        self.assertIn("loopback", r_bad.reason or "")

    def test_05_wrong_password(self):
        r = gate.verify("Ashley", "wrong-passwd", "10.0.0.8")
        self.assertFalse(r.ok)
        self.assertIn("password", r.reason or "")
        # And no binding should have been recorded
        row = gate.find_user("Ashley")
        self.assertIsNone(row["ip_bound"])

    def test_06_solo_email_path(self):
        r = gate.verify(user=None, passwd=None,
                        client_ip="10.0.0.9", email="friends@Tmail.com")
        self.assertTrue(r.ok, r.reason)
        self.assertTrue(r.solo)
        # Subsequent solo login from a different IP must fail
        r2 = gate.verify(user=None, passwd=None,
                         client_ip="10.0.0.123", email="friends@Tmail.com")
        self.assertFalse(r2.ok)
        self.assertIn("IP mismatch", r2.reason or "")

    def test_07_unknown_user(self):
        r = gate.verify("Mallory", "passwd", "10.0.0.99")
        self.assertFalse(r.ok)
        self.assertIn("unknown user", r.reason or "")

    def test_08_no_password_field_not_required_for_localhost(self):
        # The `localhost` row has no passwd_hash — passing a passwd is OK
        # (it's ignored) AND omitting it is OK.
        r = gate.verify("localhost", "anything", "127.0.0.1")
        self.assertTrue(r.ok, r.reason)

    def test_09_seed_is_idempotent(self):
        # Bind Jamie at .5
        gate.verify("Jamie", "passwd", "10.0.0.5")
        # Re-seed and confirm Jamie's binding survives
        existing = sp.load_existing()
        merged = sp.merge(sp.SEED, existing)
        sp.write(merged)
        row = gate.find_user("Jamie")
        self.assertEqual(row["ip_bound"], "10.0.0.5")
        self.assertTrue(row["bind_hash"])

    def test_10_reset_clears_binding(self):
        gate.verify("Jamie", "passwd", "10.0.0.5")
        ok = sp.reset("Jamie")
        self.assertTrue(ok)
        row = gate.find_user("Jamie")
        self.assertIsNone(row["ip_bound"])
        self.assertIsNone(row["bind_hash"])
        # Now Jamie can log in fresh from any IP — first login binds new IP
        r = gate.verify("Jamie", "passwd", "10.0.0.55")
        self.assertTrue(r.ok)
        self.assertEqual(r.reason, "first-login bind")


def tearDownModule():
    shutil.rmtree(TMPDIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
