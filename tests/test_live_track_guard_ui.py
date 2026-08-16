from __future__ import annotations

from types import SimpleNamespace
import unittest

from eqquest.live_track_guard_ui import track_live_recommendation


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class LiveTrackGuardTests(unittest.TestCase):
    def _fake(self, checker):
        tracked: list[tuple[int, str]] = []
        guidance: list[str] = []
        live_refreshes: list[bool] = []
        fake = SimpleNamespace(
            db=SimpleNamespace(is_quest_tracked=checker),
            status=_Status(),
            _track_and_reconcile=lambda quest_id, announce="": tracked.append(
                (int(quest_id), str(announce))
            ),
            _refresh_guidance=lambda: guidance.append("guidance"),
            _refresh_activity_pathways=lambda force=False: live_refreshes.append(bool(force)),
            _target_quest_relevance_key=(1, 2, 3),
        )
        return fake, tracked, guidance, live_refreshes

    def test_database_already_tracked_blocks_stale_untracked_row(self):
        fake, tracked, guidance, refreshes = self._fake(lambda quest_id: int(quest_id) == 44)
        selection = SimpleNamespace(quest_id=44, quest_name="Already Owned", tracked=False)

        changed = track_live_recommendation(
            fake,
            selection,
            announce="PATHWAY | tracking suggested quest",
            surface_label="Potential Pathway",
        )

        self.assertFalse(changed)
        self.assertEqual(tracked, [])
        self.assertEqual(guidance, [])
        self.assertEqual(refreshes, [True])
        self.assertIn("already tracked", fake.status.value)
        self.assertEqual(fake._target_quest_relevance_key, (1, 2, 3))

    def test_database_untracked_allows_action_despite_stale_tracked_row(self):
        fake, tracked, guidance, refreshes = self._fake(lambda _quest_id: False)
        selection = SimpleNamespace(quest_id=45, quest_name="Now Untracked", tracked=True)

        changed = track_live_recommendation(
            fake,
            selection,
            announce="TARGET | tracking source-backed related quest",
            surface_label="Target Intelligence",
        )

        self.assertTrue(changed)
        self.assertEqual(
            tracked,
            [(45, "TARGET | tracking source-backed related quest")],
        )
        self.assertEqual(guidance, ["guidance"])
        self.assertEqual(refreshes, [True])
        self.assertIsNone(fake._target_quest_relevance_key)

    def test_missing_ownership_checker_fails_closed(self):
        tracked: list[int] = []
        fake = SimpleNamespace(
            db=SimpleNamespace(),
            status=_Status(),
            _track_and_reconcile=lambda quest_id, announce="": tracked.append(int(quest_id)),
            _refresh_guidance=lambda: self.fail("guidance must not refresh after failed verification"),
            _refresh_activity_pathways=lambda force=False: self.fail(
                "recommendations must not refresh after failed verification"
            ),
        )
        selection = SimpleNamespace(quest_id=46, quest_name="Unknown Ownership")

        changed = track_live_recommendation(
            fake,
            selection,
            announce="ZONE OPPORTUNITY | tracking selected quest",
            surface_label="Zone Opportunity",
        )

        self.assertFalse(changed)
        self.assertEqual(tracked, [])
        self.assertIn("could not verify", fake.status.value)
        self.assertIn("was not changed", fake.status.value)

    def test_ownership_query_error_fails_closed(self):
        def broken_checker(_quest_id):
            raise RuntimeError("state unavailable")

        fake, tracked, guidance, refreshes = self._fake(broken_checker)
        selection = SimpleNamespace(quest_id=47, quest_name="Verification Failure")

        changed = track_live_recommendation(
            fake,
            selection,
            announce="PATHWAY | tracking suggested quest",
            surface_label="Potential Pathway",
        )

        self.assertFalse(changed)
        self.assertEqual(tracked, [])
        self.assertEqual(guidance, [])
        self.assertEqual(refreshes, [])
        self.assertIn("could not verify", fake.status.value)

    def test_untracked_action_uses_exact_id_and_refreshes_composed_live_stack(self):
        checked: list[int] = []

        def checker(quest_id):
            checked.append(int(quest_id))
            return False

        fake, tracked, guidance, refreshes = self._fake(checker)
        selection = SimpleNamespace(quest_id=999, quest_name="Exact Quest")

        changed = track_live_recommendation(
            fake,
            selection,
            announce="ZONE OPPORTUNITY | tracking selected quest",
            surface_label="Zone Opportunity",
        )

        self.assertTrue(changed)
        self.assertEqual(checked, [999])
        self.assertEqual(
            tracked,
            [(999, "ZONE OPPORTUNITY | tracking selected quest")],
        )
        self.assertEqual(guidance, ["guidance"])
        self.assertEqual(refreshes, [True])


if __name__ == "__main__":
    unittest.main()
