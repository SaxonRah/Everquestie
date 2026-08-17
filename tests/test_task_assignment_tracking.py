from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.quest_engine import QuestEngine
from eqquest.runtime import RuntimeDatabase
from eqquest.task_assignment_tracking_ui import handle_live_task_assignment


class _Recorder:
    def __init__(self, db):
        self.db = db
        self.events: list[str] = []
        self.live_refreshes: list[bool] = []
        self._reconcile_tracked_quest = self._forbidden_reconcile
        self._suggest_zone_from_quest = self._forbidden_zone_inference

    def _append_event(self, text: str) -> None:
        self.events.append(str(text))

    def _refresh_activity_pathways(self, *, force: bool = False) -> None:
        self.live_refreshes.append(bool(force))

    @staticmethod
    def _forbidden_reconcile(*_args, **_kwargs):
        raise AssertionError("live task assignment must not read/reconcile ahead in the log")

    @staticmethod
    def _forbidden_zone_inference(*_args, **_kwargs):
        raise AssertionError("task assignment does not prove the player's current zone")


class TaskAssignmentTrackingTests(unittest.TestCase):
    @staticmethod
    def _source(db: Database, key: str, kind: str = "quest") -> int:
        return db.upsert_source_page(
            url=f"https://example.invalid/{key}",
            title=key,
            entity_type=kind,
            sha256=key,
            plain_text=key,
            raw_html="",
            source_name="Test Source",
            source_kind="fixture",
            source_key=key,
        )

    def _quest(
        self,
        db: Database,
        name: str,
        external_id: str,
        *,
        count: int = 2,
    ) -> int:
        page = self._source(db, external_id)
        quest = db.upsert_entity(
            kind="quest",
            name=name,
            external_id=external_id,
            source_page_id=page,
        )
        db.add_quest_step(
            quest,
            1,
            "Kill a skeleton",
            match={"event": "kill", "npc": "a skeleton", "count": count},
            source_page_id=page,
        )
        return quest

    @staticmethod
    def _assigned(name: str) -> Event:
        return Event(
            kind="task_assigned",
            raw=f"You have been assigned the task '{name}'.",
            text=name,
        )

    @staticmethod
    def _progress(db, quest_id: int) -> int:
        return int(db.quest_steps(quest_id)[0]["progress_count"])

    def test_unique_exact_assignment_tracks_without_log_lookahead_or_zone_inference(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Skeleton Duty", "quest:1")
                app = _Recorder(db)

                result = handle_live_task_assignment(app, self._assigned("Skeleton Duty"))

                self.assertEqual(result.status, "tracked")
                self.assertEqual(result.quest_id, quest)
                self.assertTrue(db.is_quest_tracked(quest))
                self.assertEqual(self._progress(db, quest), 0)
                self.assertEqual(app.live_refreshes, [True])
                self.assertTrue(any("no log lookahead" in line for line in app.events))
            finally:
                db.close()

    def test_unique_alias_assignment_tracks_exact_quest_identity(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Formal Task Name", "quest:1")
                db.add_alias(quest, "Short Task", alias_type="quest_short_name")
                app = _Recorder(db)

                result = handle_live_task_assignment(app, self._assigned("Short Task"))

                self.assertEqual(result.status, "tracked")
                self.assertEqual(result.quest_id, quest)
                self.assertTrue(db.is_quest_tracked(quest))
            finally:
                db.close()

    def test_duplicate_canonical_assignment_name_fails_closed_and_preserves_progress(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Twin Task", "quest:1", count=3)
                self._quest(db, "Twin Task", "quest:2")
                db.track_quest(quest)
                db.set_step_progress(quest, 1, 1, False)
                app = _Recorder(db)

                result = handle_live_task_assignment(app, self._assigned("Twin Task"))

                self.assertEqual(result.status, "ambiguous")
                self.assertEqual(self._progress(db, quest), 1)
                self.assertEqual(app.live_refreshes, [])
                self.assertTrue(any("ambiguous" in line for line in app.events))
            finally:
                db.close()

    def test_duplicate_alias_assignment_fails_closed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                one = self._quest(db, "Formal One", "quest:1")
                two = self._quest(db, "Formal Two", "quest:2")
                db.add_alias(one, "Shared Task", alias_type="quest_short_name")
                db.add_alias(two, "Shared Task", alias_type="quest_short_name")
                app = _Recorder(db)

                result = handle_live_task_assignment(app, self._assigned("Shared Task"))

                self.assertEqual(result.status, "ambiguous")
                self.assertEqual(db.tracked_quests(), [])
            finally:
                db.close()

    def test_exact_canonical_name_takes_precedence_over_other_quest_alias(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                canonical = self._quest(db, "Shared Task", "quest:canonical")
                alias_owner = self._quest(db, "Formal Other", "quest:alias")
                db.add_alias(alias_owner, "Shared Task", alias_type="quest_short_name")
                app = _Recorder(db)

                result = handle_live_task_assignment(app, self._assigned("Shared Task"))

                self.assertEqual(result.status, "tracked")
                self.assertEqual(result.quest_id, canonical)
                tracked_ids = {int(row["id"]) for row in db.tracked_quests()}
                self.assertEqual(tracked_ids, {canonical})
            finally:
                db.close()

    def test_unknown_assignment_is_observed_but_not_auto_tracked(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                app = _Recorder(db)

                result = handle_live_task_assignment(app, self._assigned("Unknown Task"))

                self.assertEqual(result.status, "unknown")
                self.assertEqual(db.tracked_quests(), [])
                self.assertTrue(any("not uniquely present" in line for line in app.events))
            finally:
                db.close()

    def test_task_update_is_not_an_assignment_or_ownership_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                self._quest(db, "Skeleton Duty", "quest:1")
                app = _Recorder(db)
                event = Event(
                    kind="task_update",
                    raw="Your task 'Skeleton Duty' has been updated.",
                    text="Skeleton Duty",
                )

                result = handle_live_task_assignment(app, event)

                self.assertEqual(result.status, "ignored")
                self.assertEqual(db.tracked_quests(), [])
                self.assertEqual(app.events, [])
            finally:
                db.close()

    def test_explicit_reassignment_restarts_existing_task_at_current_stream_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Repeatable Duty", "quest:1", count=3)
                db.track_quest(quest)
                db.set_step_progress(quest, 1, 2, False)
                app = _Recorder(db)

                result = handle_live_task_assignment(app, self._assigned("Repeatable Duty"))

                self.assertEqual(result.status, "restarted")
                self.assertTrue(result.was_tracked)
                self.assertEqual(self._progress(db, quest), 0)
                self.assertTrue(any("restarted assigned task" in line for line in app.events))
            finally:
                db.close()

    def test_one_post_assignment_kill_is_counted_exactly_once(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Skeleton Duty", "quest:1", count=2)
                app = _Recorder(db)
                engine = QuestEngine(db)
                assignment = self._assigned("Skeleton Duty")

                handle_live_task_assignment(app, assignment)
                engine.observe(assignment)
                engine.observe(
                    Event(
                        kind="kill",
                        raw="You have slain a skeleton!",
                        actor="a skeleton",
                        target="You",
                    )
                )

                self.assertEqual(self._progress(db, quest), 1)
                self.assertEqual(int(db.quest_steps(quest)[0]["complete"]), 0)
            finally:
                db.close()

    def test_runtime_assignment_writes_only_user_state_not_packaged_knowledge(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            working = root / "working.sqlite3"
            knowledge = root / "everquestie-knowledge.sqlite3"
            state = root / "everquestie-user.sqlite3"

            builder = Database(working)
            try:
                self._quest(builder, "Runtime Task", "quest:runtime")
            finally:
                builder.close()
            create_knowledge_snapshot(
                working,
                knowledge,
                snapshot_version="task-assignment-test",
                overwrite=True,
            )
            before = sha256(knowledge.read_bytes()).hexdigest()

            runtime = RuntimeDatabase(knowledge, state)
            try:
                app = _Recorder(runtime)
                result = handle_live_task_assignment(app, self._assigned("Runtime Task"))
                self.assertEqual(result.status, "tracked")
                self.assertEqual(len(runtime.tracked_quests()), 1)
                self.assertEqual(self._progress(runtime, int(result.quest_id)), 0)
            finally:
                runtime.close()

            self.assertEqual(sha256(knowledge.read_bytes()).hexdigest(), before)
            self.assertTrue(state.is_file())
            self.assertFalse(Path(str(knowledge) + "-wal").exists())
            self.assertFalse(Path(str(knowledge) + "-shm").exists())


if __name__ == "__main__":
    unittest.main()
