"""Public and lab sign-in helpers."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "test-session-secret-not-for-production")

from simust_security import hash_password, verify_password  # noqa: E402
import app as simust_app  # noqa: E402


class PasswordVerifyTests(unittest.TestCase):
    def test_pbkdf2_roundtrip(self):
        stored = hash_password("secret-pass")
        ok, upgraded = verify_password("secret-pass", stored)
        self.assertTrue(ok)
        self.assertIsNone(upgraded)

    def test_legacy_plaintext_upgrades(self):
        ok, upgraded = verify_password("lab-admin", "lab-admin")
        self.assertTrue(ok)
        self.assertTrue(upgraded and upgraded.startswith("pbkdf2$"))
        again, _ = verify_password("lab-admin", upgraded)
        self.assertTrue(again)


class UsernameLookupTests(unittest.TestCase):
    def test_case_insensitive(self):
        users = {"Admin": {"role": "admin"}, "james": {"role": "player"}}
        self.assertEqual(simust_app.find_username(users, "admin"), "Admin")
        self.assertEqual(simust_app.find_username(users, " JAMES "), "james")
        self.assertIsNone(simust_app.find_username(users, "missing"))


class EnsureAdminTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        handle.write(b"{}")
        handle.close()
        self.tmp = handle.name
        self.prev_file = simust_app.USERS_FILE
        self.prev_pw = os.environ.get("SIMUST_ADMIN_PASSWORD")
        simust_app.USERS_FILE = self.tmp

    def tearDown(self):
        simust_app.USERS_FILE = self.prev_file
        if self.prev_pw is None:
            os.environ.pop("SIMUST_ADMIN_PASSWORD", None)
        else:
            os.environ["SIMUST_ADMIN_PASSWORD"] = self.prev_pw
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_creates_admin_from_env(self):
        os.environ["SIMUST_ADMIN_PASSWORD"] = "tablet-admin-pass"
        simust_app.ensure_admin_account()
        users = simust_app.load_users()
        self.assertEqual(users["admin"]["role"], "admin")
        ok, _ = verify_password("tablet-admin-pass", users["admin"]["password"])
        self.assertTrue(ok)

    def test_does_not_overwrite(self):
        os.environ["SIMUST_ADMIN_PASSWORD"] = "new-pass"
        with open(self.tmp, "w", encoding="utf-8") as f:
            f.write('{"admin":{"role":"admin","password":"keep-me"}}')
        simust_app.ensure_admin_account()
        users = simust_app.load_users()
        self.assertEqual(users["admin"]["password"], "keep-me")


if __name__ == "__main__":
    unittest.main()
