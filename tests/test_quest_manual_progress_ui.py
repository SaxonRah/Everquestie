from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.quest_manual_progress_ui import install_quest_manual_progress_ui


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class QuestManualProgressUITests(unittest.TestCase):
    def setUp(self):
        install_quest_manual_progress_ui()
        from eqquest.app import EverQuestieApp

        self.action = EverQuestieApp._mark_selected_step_complete

    @staticmethod
    def _quest(db: Database) -> int:
        quest = db.upsert_entity(kind="quest", name="Manual UI Quest")
        db.add_quest_step(
            quest,
            1,
            "Speak with Quest Guide",
            match={"event": "npc_say", "npc": "Quest Guide", "count": 1},
        )
        db.add_quest_step(
            quest,
            2,
            "Loot Reward Token",
            match={"event": "loot", "item": "Reward Token", "count": 1},
        )
        db.track_quest(quest)
        return quest

    def test_installer_adds_explicit_button_to_existing_tracked_action_row(self):
        source = inspect.getsource(install_quest_manual_progress_ui)
        self.assertIn('text="Mark selected complete"', source)
        self.assertIn("_tracked_action_row(self)", source)
        self.assertIn("grid_slaves(row=5, column=0)", inspect.getsource(__import__(
            "eqquest.quest_manual_progress_ui", fromlist=["_tracked_action_row"]
        )._tracked_action_row))

    def test_no_exact_step_selection_does_not_mutate(self):
        fake = SimpleNamespace(
            _tracked_selected_step=lambda: None,
            status=_Status(),
        )

        result = self.action(fake)

        self.assertIsNone(result)
        self.assertIn("select an objective row", fake.status.value)

    def test_success_uses_exact_selected_step_and_refreshes_guidance_and_live_stack(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db)
                guidance = []
                live = []
                fake = SimpleNamespace(
                    db=db,
                    _tracked_selected_step=lambda: (quest, 1),
                    status=_Status(),
                    _refresh_guidance=lambda: guidance.append(True),
                    _refresh_activity_pathways=lambda force=False: live.append(bool(force)),
                )

                result = self.action(fake)

                self.assertTrue(result.completed)
                self.assertEqual(int(db.quest_steps(quest)[0]["complete"]), 1)
                self.assertEqual(int(db.tracked_quests()[0]["active_step"]), 2)
                self.assertEqual(guidance, [True])
                self.assertEqual(live, [True])
                self.assertIn("Marked objective complete", fake.status.value)
            finally:
                db.close()

    def test_stale_selection_is_rejected_from_fresh_writable_active_step(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db)
                db.set_step_progress(quest, 1, 1, True)
                guidance = []
                live = []
                fake = SimpleNamespace(
                    db=db,
                    _tracked_selected_step=lambda: (quest, 1),
                    status=_Status(),
                    _refresh_guidance=lambda: guidance.append(True),
                    _refresh_activity_pathways=lambda force=False: live.append(bool(force)),
                )

                result = self.action(fake)

                self.assertEqual(result.status, "not_active")
                self.assertEqual(int(db.tracked_quests()[0]["active_step"]), 2)
                self.assertEqual(int(db.quest_steps(quest)[1]["complete"]), 0)
                self.assertEqual(guidance, [True])
                self.assertEqual(live, [])
                self.assertIn("blocked", fake.status.value.casefold())
            finally:
                db.close()

    def test_untracked_stale_row_is_rejected_without_retracking(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db)
                db.untrack_quest(quest)
                guidance = []
                fake = SimpleNamespace(
                    db=db,
                    _tracked_selected_step=lambda: (quest, 1),
                    status=_Status(),
                    _refresh_guidance=lambda: guidance.append(True),
                )

                result = self.action(fake)

                self.assertEqual(result.status, "not_tracked")
                self.assertEqual(db.tracked_quests(), [])
                self.assertEqual(guidance, [True])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
