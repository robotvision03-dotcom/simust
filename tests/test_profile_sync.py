"""Lab ↔ My SIMUST profile field sync (name/club/etc)."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_push  # noqa: E402


class ProfileSyncTests(unittest.TestCase):
    def test_remote_rename_overwrites_lab_when_newer(self):
        local = {
            "jj": {
                "name": "Old",
                "surname": "Name",
                "role": "player",
                "club": "A",
                "profile_updated_at": 100.0,
                "progress": {"unlocked_levels": ["L00-Foundation"]},
            }
        }
        remote = {
            "jj": {
                "name": "New",
                "surname": "Player",
                "role": "player",
                "club": "B",
                "profile_updated_at": 200.0,
                "progress": {"unlocked_levels": ["L00-Foundation", "L01-Entry/S1.T1"]},
            }
        }
        simust_push.merge_remote_accounts(local, remote)
        self.assertEqual(local["jj"]["name"], "New")
        self.assertEqual(local["jj"]["surname"], "Player")
        self.assertEqual(local["jj"]["club"], "B")
        self.assertEqual(local["jj"]["profile_updated_at"], 200.0)

    def test_older_lab_push_does_not_wipe_host_rename(self):
        host = {
            "name": "HostEdit",
            "surname": "Keep",
            "club": "HostClub",
            "role": "player",
            "profile_updated_at": 500.0,
        }
        lab = {
            "name": "LabOld",
            "surname": "Stale",
            "club": "LabClub",
            "role": "player",
            "profile_updated_at": 100.0,
        }
        changed = simust_push.apply_newer_profile(host, lab)
        self.assertFalse(changed)
        self.assertEqual(host["name"], "HostEdit")
        self.assertEqual(host["club"], "HostClub")

    def test_unstamped_lab_fill_does_not_mint_winning_stamp(self):
        """Lab must not gain a fresh stamp while keeping old names (remote wipe)."""
        lab = {
            "name": "Old",
            "surname": "Name",
            "role": "player",
            "club": "",
        }
        host = {
            "name": "Old",
            "surname": "Name",
            "role": "player",
            "club": "Filled",
        }
        simust_push.apply_newer_profile(lab, host)
        self.assertEqual(lab["club"], "Filled")
        self.assertEqual(float(lab.get("profile_updated_at") or 0), 0.0)

    def test_equal_stamp_does_not_overwrite_local_name(self):
        """Host pull must not wipe a lab Manage Players rename when stamps tie."""
        local = {
            "jj": {
                "name": "LabRename",
                "surname": "Keep",
                "role": "player",
                "club": "LabClub",
            }
        }
        remote = {
            "jj": {
                "name": "OldHost",
                "surname": "Name",
                "role": "player",
                "club": "HostClub",
            }
        }
        simust_push.merge_remote_accounts(local, remote)
        self.assertEqual(local["jj"]["name"], "LabRename")
        self.assertEqual(local["jj"]["surname"], "Keep")
        # Empty local fields can still be filled from remote.
        local2 = {"jj": {"name": "", "surname": "", "role": "player", "club": ""}}
        remote2 = {
            "jj": {
                "name": "Fresh",
                "surname": "Two",
                "role": "player",
                "club": "SCB",
                "profile_updated_at": 50.0,
            }
        }
        simust_push.merge_remote_accounts(local2, remote2)
        self.assertEqual(local2["jj"]["name"], "Fresh")
        self.assertEqual(local2["jj"]["club"], "SCB")

    def test_public_payload_includes_stamp(self):
        payload = simust_push.public_account_payload(
            "jj",
            {"name": "A", "surname": "B", "profile_updated_at": 42.5, "progress": {}},
        )
        self.assertEqual(payload["profile_updated_at"], 42.5)
        self.assertEqual(payload["name"], "A")


if __name__ == "__main__":
    unittest.main()
