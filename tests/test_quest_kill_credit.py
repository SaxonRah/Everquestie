from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.parser import EQLogParser
from eqquest.quest_engine import QuestEngine


class QuestKillCreditTests(unittest.TestCase):
    def _db(self, tempdir: str) -> Database:
        return Database(Path(tempdir) / "working.sqlite3")

    def _tracked_kill_quest(
        self,
        db: Database,
        *,
        name: str = "Skeleton Credit",
        zone: str | None = None,
        count: int = 1,
    ) -> int:
        quest = db.upsert_entity(kind="quest", name=name)
        db.add_quest_step(
            quest,
            1,
            "Kill a skeleton",
            zone=zone,
            match={"event": "kill", "npc": "a skeleton", "count": count},
        )
        db.track_quest(quest)
        return quest

    @staticmethod
    def _step(db: Database, quest_id: int):
        return db.quest_steps(quest_id)[0]

    def test_parser_direct_you_have_slain_line_auto_progresses(self):
        parser = EQLogParser()
        event = parser.parse_line("You have slain a skeleton!")
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "kill")
        self.assertEqual(event.actor, "a skeleton")
        self.assertEqual(event.target, "You")

        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db)
                QuestEngine(db).observe(event)
                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 1)
                self.assertEqual(int(step["complete"]), 1)
            finally:
                db.close()

    def test_matching_mob_slain_by_other_player_is_observation_not_progress(self):
        parser = EQLogParser()
        event = parser.parse_line("a skeleton was slain by OtherPlayer!")
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "kill")
        self.assertEqual(event.actor, "a skeleton")
        self.assertEqual(event.target, "OtherPlayer")

        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db)
                QuestEngine(db).observe(event)
                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 0)
                self.assertEqual(int(step["complete"]), 0)
            finally:
                db.close()

    def test_generic_slain_by_you_form_is_explicit_personal_evidence(self):
        parser = EQLogParser()
        event = parser.parse_line("a skeleton has been slain by You!")
        self.assertIsNotNone(event)
        self.assertEqual(event.target, "You")

        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db)
                QuestEngine(db).observe(event)
                self.assertEqual(int(self._step(db, quest)["progress_count"]), 1)
            finally:
                db.close()

    def test_other_player_kill_in_correct_zone_still_does_not_progress(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db, zone="West Zone")
                engine = QuestEngine(db)
                engine.seed_zone_context("West Zone")
                engine.observe(
                    Event(
                        kind="kill",
                        raw="a skeleton was slain by OtherPlayer!",
                        actor="a skeleton",
                        target="OtherPlayer",
                    )
                )
                self.assertEqual(int(self._step(db, quest)["progress_count"]), 0)
            finally:
                db.close()

    def test_personal_kill_in_wrong_zone_remains_blocked(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db, zone="West Zone")
                engine = QuestEngine(db)
                engine.seed_zone_context("East Zone")
                engine.observe(
                    Event(
                        kind="kill",
                        raw="You have slain a skeleton!",
                        actor="a skeleton",
                        target="You",
                    )
                )
                self.assertEqual(int(self._step(db, quest)["progress_count"]), 0)
            finally:
                db.close()

    def test_task_assignment_replay_counts_only_explicit_personal_kill(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db, count=2)
                engine = QuestEngine(db)
                events = [
                    Event(kind="task_assigned", raw="assigned", text="Skeleton Credit"),
                    Event(
                        kind="kill",
                        raw="other",
                        actor="a skeleton",
                        target="OtherPlayer",
                    ),
                    Event(kind="kill", raw="mine", actor="a skeleton", target="You"),
                ]

                result = engine.reconcile_quest_from_events(quest, events)

                self.assertEqual(result.boundary, "task assignment")
                self.assertEqual(result.progress_total, 1)
                self.assertEqual(int(self._step(db, quest)["progress_count"]), 1)
            finally:
                db.close()

    def test_starter_hail_boundary_rejects_only_other_player_kill(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db)
                starter = db.upsert_entity(kind="npc", name="Quest Guide")
                db.upsert_relationship(quest, starter, "started_by")
                engine = QuestEngine(db)

                observed_only = [
                    Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                    Event(
                        kind="kill",
                        raw="other",
                        actor="a skeleton",
                        target="OtherPlayer",
                    ),
                ]
                result = engine.reconcile_quest_from_events(quest, observed_only)
                self.assertEqual(result.boundary, "none")
                self.assertEqual(result.events_replayed, -1)

                personal = [
                    Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                    Event(kind="kill", raw="mine", actor="a skeleton", target="You"),
                ]
                result = engine.reconcile_quest_from_events(quest, personal)
                self.assertEqual(result.boundary, "starter NPC hail")
                self.assertEqual(result.progress_total, 1)
            finally:
                db.close()

    def test_loot_progress_is_unchanged_by_kill_credit_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = db.upsert_entity(kind="quest", name="Loot Credit")
                db.add_quest_step(
                    quest,
                    1,
                    "Loot Bone Chips",
                    match={"event": "loot", "item": "Bone Chips", "count": 1},
                )
                db.track_quest(quest)

                QuestEngine(db).observe(Event(kind="loot", raw="loot", item="Bone Chips"))

                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 1)
                self.assertEqual(int(step["complete"]), 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
