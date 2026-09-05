"""Paid booking rules and public-host security guards."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("SIMUST_PUBLIC_MODE", "1")
os.environ.setdefault("SIMUST_SESSION_SECRET", "test-session-secret-not-for-production")

import simust_billing  # noqa: E402
import simust_security  # noqa: E402
import app as simust_app  # noqa: E402


class BookingFeeTests(unittest.TestCase):
    def test_twenty_eur_per_half_hour(self):
        self.assertEqual(simust_billing.booking_fee_eur(30), 20)
        self.assertEqual(simust_billing.booking_fee_eur(60), 40)
        self.assertEqual(simust_billing.booking_fee_eur(180), 120)


class PlayerIdGuardTests(unittest.TestCase):
    def test_rejects_path_traversal(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            simust_security.require_player_id("../etc/passwd")
        with self.assertRaises(HTTPException):
            simust_security.require_player_id("a/b")

    def test_accepts_normal_id(self):
        self.assertEqual(simust_security.require_player_id("james"), "james")

    def test_contained_dir(self):
        from fastapi import HTTPException
        root = tempfile.mkdtemp(prefix="simust-rep-")
        inside = simust_security.contained_player_dir(root, "james")
        self.assertTrue(inside.startswith(os.path.realpath(root)))
        with self.assertRaises(HTTPException):
            simust_security.contained_player_dir(root, "..")


class ImageSanitizeTests(unittest.TestCase):
    def test_strips_data_uri_on_public(self):
        self.assertEqual(simust_security.sanitize_profile_image("data:image/png;base64,aaaa"), "")

    def test_keeps_https(self):
        self.assertTrue(simust_security.sanitize_profile_image("https://cdn.example.com/a.png").startswith("https://"))


class RegisterRoleTests(unittest.TestCase):
    def test_admin_cannot_self_register(self):
        self.assertNotIn("admin", simust_security.PUBLIC_REGISTER_ROLES)


class PublicReservationPayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.tmp.close()
        os.remove(self.tmp.name)
        self.prev = simust_app.RESERVATIONS_FILE
        simust_app.RESERVATIONS_FILE = self.tmp.name

    def tearDown(self):
        simust_app.RESERVATIONS_FILE = self.prev
        try:
            os.remove(self.tmp.name)
        except OSError:
            pass

    def test_public_create_without_payment_is_rejected(self):
        import asyncio
        from fastapi import HTTPException

        class Req:
            async def json(self):
                return {
                    "player_id": "james",
                    "start": "2099-01-01T10:00:00",
                    "end": "2099-01-01T10:30:00",
                    "payment_status": "simulated",
                }

        async def run():
            prev_users = simust_app.load_users
            prev_user = simust_app.current_user

            def users():
                return {"james": {"name": "James", "surname": "W", "role": "player", "email": "a@b.c"}}

            def viewer(_req, _users, required=False):
                return {"username": "james", "role": "player"}

            simust_app.load_users = users
            simust_app.current_user = viewer
            try:
                await simust_app.create_reservation(Req())
            finally:
                simust_app.load_users = prev_users
                simust_app.current_user = prev_user

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(run())
        self.assertEqual(ctx.exception.status_code, 402)


if __name__ == "__main__":
    unittest.main()
