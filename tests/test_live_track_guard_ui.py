from __future__ import annotations

import inspect
from types import SimpleNamespace
import unittest

from eqquest.live_track_guard_ui import install_live_track_guard_ui, track_live_recommendation


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class LiveTrackGuardTests(unittest.TestCase):
    def _fake(self, checker, *, tracker=None):
        tracked: list[int] = []
        events: list[str] = []
        guidance: list[str] = []
        live_refreshes: list[bool] = []
        if tracker is None:
            tracker = lambda quest_id: tracked.append(int(quest_id))

        def forbidden(name):
            def fail(*_args, **_kwargs):
                self.fail(f"Live recommendation tracking must not call {name}")

            return fail

        fake = SimpleNamespace(
            db=SimpleNamespace(
                is_quest_tracked=checker,
                track_quest=tracker,
            ),
            status=_Status(),
            _track_and_reconcile=forbidden("_track_and_reconcile"),
            _suggest_zone_from_quest=forbidden("_suggest_zone_from_quest"),
            _reconcile_tracked_quest=forbidden("_reconcile_tracked_quest"),
            _append_event=lambda text: events.append(str(text)),
            _refresh_guidance=lambda: guidance.append("guidance"),
            _refresh_activity_pathways=lambda force=False: live_refreshes.append(bool(force)),
            _target_quest_relevance_key=(1, 2, 3),
        )
        return fake, tracked, events, guidance, live_refreshes

    def test_guard_installer_owns_recent_loot_track_action_too(self):
        source = inspect.getsource(install_live_track_guard_ui)
        self.assertIn("self._selected_loot_relevance()", source)
        self.assertIn(
            "current_app._loot_relevance_track_quest = _loot_relevance_track_quest",
            source,
        )
        self.assertIn("LOOT RELEVANCE | tracking selected quest", source)

    def test_database_already_tracked_blocks_stale_untracked_row(self):
        fake, tracked, events, guidance, refreshes = self._fake(
            lambda quest_id: int(quest_id) == 44
        )
        selection = SimpleNamespace(quest_id=44, quest_name="Already Owned", tracked=False)

        changed = track_live_recommendation(
            fake,
            selection,
            announce="PATHWAY | tracking suggested quest",
            surface_label="Potential Pathway",
        )

        self.assertFalse(changed)
        self.assertEqual(tracked, [])
        self.assertEqual(events, [])
        self.assertEqual(guidance, [])
        self.assertEqual(refreshes, [True])
        self.assertIn("already tracked", fake.status.value)
        self.assertEqual(fake._target_quest_relevance_key, (1, 2, 3))

    def test_database_untracked_allows_action_despite_stale_tracked_row(self):
        fake, tracked, events, guidance, refreshes = self._fake(lambda _quest_id: False)
        selection = SimpleNamespace(quest_id=45, quest_name="Now Untracked", tracked=True)

        changed = track_live_recommendation(
            fake,
            selection,
            announce="TARGET | tracking source-backed related quest",
            surface_label="Target Intelligence",
        )

        self.assertTrue(changed)
        self.assertEqual(tracked, [45])
        self.assertEqual(
            events,
            ["TARGET | tracking source-backed related quest: Now Untracked"],
        )
        self.assertEqual(guidance, ["guidance"])
        self.assertEqual(refreshes, [True])
        self.assertIsNone(fake._target_quest_relevance_key)

    def test_missing_ownership_checker_fails_closed(self):
        tracked: list[int] = []
        fake = SimpleNamespace(
            db=SimpleNamespace(track_quest=lambda quest_id: tracked.append(int(quest_id))),
            status=_Status(),
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

    def test_missing_writable_tracker_fails_closed(self):
        fake = SimpleNamespace(
            db=SimpleNamespace(is_quest_tracked=lambda _quest_id: False),
            status=_Status(),
            _refresh_guidance=lambda: self.fail("guidance must not refresh without a writer"),
            _refresh_activity_pathways=lambda force=False: self.fail(
                "recommendations must not refresh without a writer"
            ),
        )
        selection = SimpleNamespace(quest_id=146, quest_name="No Writable State")

        changed = track_live_recommendation(
            fake,
            selection,
            announce="LOOT RELEVANCE | tracking selected quest",
            surface_label="Recent Loot Relevance",
        )

        self.assertFalse(changed)
        self.assertIn("could not verify writable tracking state", fake.status.value)
        self.assertIn("was not changed", fake.status.value)

    def test_ownership_query_error_fails_closed(self):
        def broken_checker(_quest_id):
            raise RuntimeError("state unavailable")

        fake, tracked, events, guidance, refreshes = self._fake(broken_checker)
        selection = SimpleNamespace(quest_id=47, quest_name="Verification Failure")

        changed = track_live_recommendation(
            fake,
            selection,
            announce="PATHWAY | tracking suggested quest",
            surface_label="Potential Pathway",
        )

        self.assertFalse(changed)
        self.assertEqual(tracked, [])
        self.assertEqual(events, [])
        self.assertEqual(guidance, [])
        self.assertEqual(refreshes, [])
        self.assertIn("could not verify", fake.status.value)

    def test_tracking_write_error_fails_closed_without_projection_refresh(self):
        def broken_tracker(_quest_id):
            raise RuntimeError("user database unavailable")

        fake, tracked, events, guidance, refreshes = self._fake(
            lambda _quest_id: False,
            tracker=broken_tracker,
        )
        selection = SimpleNamespace(quest_id=147, quest_name="Write Failure")

        changed = track_live_recommendation(
            fake,
            selection,
            announce="PATHWAY | tracking suggested quest",
            surface_label="Potential Pathway",
        )

        self.assertFalse(changed)
        self.assertEqual(tracked, [])
        self.assertEqual(events, [])
        self.assertEqual(guidance, [])
        self.assertEqual(refreshes, [])
        self.assertIn("could not write tracking state", fake.status.value)
        self.assertIn("was not changed", fake.status.value)

    def test_untracked_action_uses_exact_id_and_refreshes_composed_live_stack(self):
        checked: list[int] = []

        def checker(quest_id):
            checked.append(int(quest_id))
            return False

        fake, tracked, events, guidance, refreshes = self._fake(checker)
        selection = SimpleNamespace(quest_id=999, quest_name="Exact Quest")

        changed = track_live_recommendation(
            fake,
            selection,
            announce="ZONE OPPORTUNITY | tracking selected quest",
            surface_label="Zone Opportunity",
        )

        self.assertTrue(changed)
        self.assertEqual(checked, [999])
        self.assertEqual(tracked, [999])
        self.assertEqual(
            events,
            ["ZONE OPPORTUNITY | tracking selected quest: Exact Quest"],
        )
        self.assertEqual(guidance, ["guidance"])
        self.assertEqual(refreshes, [True])


if __name__ == "__main__":
    unittest.main()
