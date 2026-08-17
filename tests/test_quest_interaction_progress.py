from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.quest_engine import QuestEngine
from eqquest.quest_interaction_guidance_ui import install_quest_interaction_guidance_ui


class QuestInteractionProgressTests(unittest.TestCase):
    def _db(self, tempdir: str) -> Database:
        return Database(Path(tempdir) / "working.sqlite3")

    def _tracked_interaction(
        self,
        db: Database,
        *,
        quest_name: str,
        description: str,
        verified: bool = False,
    ) -> tuple[int, int]:
        npc = db.upsert_entity(kind="npc", name="Quest Guide")
        quest = db.upsert_entity(kind="quest", name=quest_name)
        rule = {
            "event": "npc_say",
            "npc": "Quest Guide",
            "npc_entity_id": npc,
            "count": 1,
        }
        if verified:
            rule["verified_completion_signal"] = True
        db.add_quest_step(quest, 1, description, match=rule)
        db.track_quest(quest)
        return quest, npc

    def test_named_npc_ambient_speech_does_not_complete_speak_objective(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest, _npc = self._tracked_interaction(
                    db,
                    quest_name="Talk to the Guide",
                    description="Speak with Quest Guide",
                )
                engine = QuestEngine(db)

                engine.observe(
                    Event(
                        kind="npc_say",
                        raw="Quest Guide says, 'The weather is pleasant.'",
                        actor="Quest Guide",
                        text="The weather is pleasant.",
                    )
                )

                step = db.quest_steps(quest)[0]
                self.assertEqual(int(step["progress_count"]), 0)
                self.assertEqual(int(step["complete"]), 0)
            finally:
                db.close()

    def test_named_npc_speech_does_not_complete_item_turn_in_surrogate(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest, _npc = self._tracked_interaction(
                    db,
                    quest_name="Return the Token",
                    description="Give Quest Token to Quest Guide",
                )
                engine = QuestEngine(db)

                engine.observe(
                    Event(
                        kind="npc_say",
                        raw="Quest Guide says, 'Greetings.'",
                        actor="Quest Guide",
                        text="Greetings.",
                    )
                )

                step = db.quest_steps(quest)[0]
                self.assertEqual(int(step["progress_count"]), 0)
                self.assertEqual(int(step["complete"]), 0)
            finally:
                db.close()

    def test_reconciliation_does_not_turn_ambient_speech_into_progress(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest, _npc = self._tracked_interaction(
                    db,
                    quest_name="Talk to the Guide",
                    description="Speak with Quest Guide",
                )
                engine = QuestEngine(db)
                events = [
                    Event(
                        kind="task_assigned",
                        raw="assigned",
                        text="Talk to the Guide",
                    ),
                    Event(
                        kind="npc_say",
                        raw="Quest Guide says, 'Move along.'",
                        actor="Quest Guide",
                        text="Move along.",
                    ),
                ]

                result = engine.reconcile_quest_from_events(quest, events)

                self.assertEqual(result.boundary, "task assignment")
                self.assertEqual(result.progress_total, 0)
                self.assertEqual(result.completed_steps, 0)
                step = db.quest_steps(quest)[0]
                self.assertEqual(int(step["progress_count"]), 0)
                self.assertEqual(int(step["complete"]), 0)
            finally:
                db.close()

    def test_explicit_reviewed_completion_signal_can_opt_in(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest, _npc = self._tracked_interaction(
                    db,
                    quest_name="Reviewed Interaction",
                    description="Complete the reviewed interaction with Quest Guide",
                    verified=True,
                )
                engine = QuestEngine(db)

                engine.observe(
                    Event(
                        kind="npc_say",
                        raw="Quest Guide says, 'Verified response.'",
                        actor="Quest Guide",
                        text="Verified response.",
                    )
                )

                step = db.quest_steps(quest)[0]
                self.assertEqual(int(step["progress_count"]), 1)
                self.assertEqual(int(step["complete"]), 1)
            finally:
                db.close()

    def test_guidance_explains_unverified_interaction_is_not_auto_completed(self):
        install_quest_interaction_guidance_ui()
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                self._tracked_interaction(
                    db,
                    quest_name="Talk to the Guide",
                    description="Speak with Quest Guide",
                )
                guidance = QuestEngine(db).guidance(None)

                self.assertEqual(len(guidance), 1)
                self.assertIn("Speak with Quest Guide", guidance[0].text)
                self.assertIn("does not prove", guidance[0].text)
                self.assertIn("not auto-complete", guidance[0].text)
            finally:
                db.close()

    def test_reviewed_interaction_guidance_does_not_show_automation_warning(self):
        install_quest_interaction_guidance_ui()
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                self._tracked_interaction(
                    db,
                    quest_name="Reviewed Interaction",
                    description="Complete the reviewed interaction with Quest Guide",
                    verified=True,
                )
                guidance = QuestEngine(db).guidance(None)

                self.assertEqual(len(guidance), 1)
                self.assertNotIn("not auto-complete", guidance[0].text)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
