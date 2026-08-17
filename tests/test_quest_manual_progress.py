from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.quest_manual_progress import complete_active_tracked_step
from eqquest.runtime import RuntimeDatabase


class QuestManualProgressTests(unittest.TestCase):
    def _quest(self, db: Database, *, first_count: int = 3) -> int:
        quest = db.upsert_entity(kind="quest", name="Manual Progress Quest")
        db.add_quest_step(
            quest,
            1,
            "Complete the uncertain interaction",
            match={"event": "npc_say", "npc": "Quest Guide", "count": first_count},
        )
        db.add_quest_step(
            quest,
            2,
            "Loot the reward token",
            match={"event": "loot", "item": "Reward Token", "count": 1},
        )
        db.track_quest(quest)
        return quest

    def test_exact_active_step_completion_sets_required_count_and_advances(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, first_count=3)

                result = complete_active_tracked_step(db, quest, 1)

                self.assertTrue(result.completed)
                self.assertEqual(result.progress_count, 3)
                step = db.quest_steps(quest)[0]
                self.assertEqual(int(step["progress_count"]), 3)
                self.assertEqual(int(step["complete"]), 1)
                tracked = db.tracked_quests()[0]
                self.assertEqual(int(tracked["active_step"]), 2)
            finally:
                db.close()

    def test_later_selected_step_is_blocked_and_cannot_skip_active_objective(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db)

                result = complete_active_tracked_step(db, quest, 2)

                self.assertEqual(result.status, "not_active")
                self.assertFalse(result.completed)
                self.assertEqual(int(db.tracked_quests()[0]["active_step"]), 1)
                self.assertEqual(int(db.quest_steps(quest)[1]["complete"]), 0)
            finally:
                db.close()

    def test_stale_selected_step_is_blocked_after_active_step_moves(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db)
                db.set_step_progress(quest, 1, 3, True)

                result = complete_active_tracked_step(db, quest, 1)

                self.assertEqual(result.status, "not_active")
                self.assertEqual(result.active_step, 2)
                self.assertEqual(int(db.tracked_quests()[0]["active_step"]), 2)
            finally:
                db.close()

    def test_untracked_quest_is_blocked_at_click_time(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db)
                db.untrack_quest(quest)

                result = complete_active_tracked_step(db, quest, 1)

                self.assertEqual(result.status, "not_tracked")
                self.assertFalse(result.completed)
            finally:
                db.close()

    def test_missing_active_step_fails_closed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = db.upsert_entity(kind="quest", name="Step Missing Quest")
                db.track_quest(quest)

                result = complete_active_tracked_step(db, quest, 1)

                self.assertEqual(result.status, "missing_step")
                self.assertFalse(result.completed)
            finally:
                db.close()

    def test_existing_progress_is_never_reduced(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, first_count=3)
                db.set_step_progress(quest, 1, 5, False)

                result = complete_active_tracked_step(db, quest, 1)

                self.assertTrue(result.completed)
                self.assertEqual(result.progress_count, 5)
                self.assertEqual(int(db.quest_steps(quest)[0]["progress_count"]), 5)
            finally:
                db.close()

    def test_runtime_split_writes_only_user_state_database(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            working = root / "working.sqlite3"
            knowledge = root / "everquestie-knowledge.sqlite3"
            state = root / "everquestie-user.sqlite3"

            builder = Database(working)
            try:
                quest = self._quest(builder, first_count=2)
                builder.untrack_quest(quest)
            finally:
                builder.close()
            create_knowledge_snapshot(
                working,
                knowledge,
                snapshot_version="manual-progress-test",
                overwrite=True,
            )
            before = sha256(knowledge.read_bytes()).hexdigest()

            runtime = RuntimeDatabase(knowledge, state)
            try:
                resolved, _status = runtime.resolve_entity("Manual Progress Quest", "quest")
                self.assertIsNotNone(resolved)
                quest_id = int(resolved["id"])
                runtime.track_quest(quest_id)

                result = complete_active_tracked_step(runtime, quest_id, 1)

                self.assertTrue(result.completed)
                self.assertEqual(result.progress_count, 2)
                self.assertEqual(int(runtime.quest_steps(quest_id)[0]["complete"]), 1)
                self.assertEqual(int(runtime.tracked_quests()[0]["active_step"]), 2)
            finally:
                runtime.close()

            self.assertEqual(sha256(knowledge.read_bytes()).hexdigest(), before)
            self.assertTrue(state.is_file())
            self.assertFalse(Path(str(knowledge) + "-wal").exists())
            self.assertFalse(Path(str(knowledge) + "-shm").exists())


if __name__ == "__main__":
    unittest.main()
