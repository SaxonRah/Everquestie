from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.parser import EQLogParser
from eqquest.quest_engine import QuestEngine
from eqquest.quest_progress_zone_context_ui import _zone_context_from_log


class QuestProgressZoneContextTests(unittest.TestCase):
    def _db(self, tempdir: str) -> Database:
        return Database(Path(tempdir) / "working.sqlite3")

    def _tracked_kill_quest(
        self,
        db: Database,
        *,
        name: str = "West Skeleton Hunt",
        zone: str = "West Zone",
        count: int = 1,
    ) -> int:
        quest = db.upsert_entity(kind="quest", name=name)
        db.add_quest_step(
            quest,
            1,
            f"Defeat {count} skeleton",
            zone=zone,
            match={"event": "kill", "npc": "a skeleton", "count": count},
        )
        db.track_quest(quest)
        return quest

    def _step(self, db: Database, quest: int):
        return db.quest_steps(quest)[0]

    def test_live_zone_bound_kill_rejects_same_named_mob_elsewhere(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db)
                engine = QuestEngine(db)
                engine.seed_zone_context("East Zone")

                engine.observe(Event(kind="kill", raw="kill", actor="a skeleton", target="You"))

                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 0)
                self.assertEqual(int(step["complete"]), 0)
            finally:
                db.close()

    def test_live_zone_bound_kill_accepts_matching_logged_zone(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db)
                engine = QuestEngine(db)
                engine.observe(Event(kind="zone", raw="zone", zone="West Zone"))
                engine.observe(Event(kind="kill", raw="kill", actor="a skeleton", target="You"))

                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 1)
                self.assertEqual(int(step["complete"]), 1)
            finally:
                db.close()

    def test_welcome_clears_live_kill_geography_until_new_zone_entry(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db, count=2)
                engine = QuestEngine(db)
                engine.seed_zone_context("West Zone")
                engine.observe(Event(kind="welcome", raw="Welcome to EverQuest!"))
                engine.observe(Event(kind="kill", raw="kill", actor="a skeleton", target="You"))

                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 0)

                engine.observe(Event(kind="zone", raw="zone", zone="West Zone"))
                engine.observe(Event(kind="kill", raw="kill", actor="a skeleton", target="You"))
                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 1)
                self.assertEqual(int(step["complete"]), 0)
            finally:
                db.close()

    def test_loot_progress_remains_portable_across_zones(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = db.upsert_entity(kind="quest", name="Portable Relic")
                db.add_quest_step(
                    quest,
                    1,
                    "Loot the West Relic",
                    zone="West Zone",
                    match={"event": "loot", "item": "West Relic", "count": 1},
                )
                db.track_quest(quest)
                engine = QuestEngine(db)
                engine.seed_zone_context("East Zone")

                engine.observe(Event(kind="loot", raw="loot", item="West Relic"))

                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 1)
                self.assertEqual(int(step["complete"]), 1)
            finally:
                db.close()

    def test_task_assignment_reconcile_uses_ordered_zone_history(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db, count=2)
                engine = QuestEngine(db)
                events = [
                    Event(kind="zone", raw="east", zone="East Zone"),
                    Event(kind="task_assigned", raw="assigned", text="West Skeleton Hunt"),
                    Event(kind="kill", raw="wrong", actor="a skeleton", target="You"),
                    Event(kind="zone", raw="west", zone="West Zone"),
                    Event(kind="kill", raw="right", actor="a skeleton", target="You"),
                ]

                result = engine.reconcile_quest_from_events(quest, events)

                self.assertEqual(result.boundary, "task assignment")
                self.assertEqual(result.progress_total, 1)
                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 1)
                self.assertEqual(int(step["complete"]), 0)
            finally:
                db.close()

    def test_starter_hail_boundary_requires_a_qualifying_count_objective(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db)
                starter = db.upsert_entity(kind="npc", name="Quest Guide")
                db.upsert_relationship(quest, starter, "started_by")
                engine = QuestEngine(db)

                wrong_zone_events = [
                    Event(kind="zone", raw="east", zone="East Zone"),
                    Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                    Event(kind="kill", raw="wrong", actor="a skeleton", target="You"),
                ]
                result = engine.reconcile_quest_from_events(quest, wrong_zone_events)
                self.assertEqual(result.boundary, "none")
                self.assertEqual(result.events_replayed, -1)

                right_zone_events = [
                    Event(kind="zone", raw="west", zone="West Zone"),
                    Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                    Event(kind="kill", raw="right", actor="a skeleton", target="You"),
                ]
                result = engine.reconcile_quest_from_events(quest, right_zone_events)
                self.assertEqual(result.boundary, "starter NPC hail")
                self.assertEqual(result.progress_total, 1)
            finally:
                db.close()

    def test_explicit_zone_on_kill_event_is_accepted_as_direct_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = self._tracked_kill_quest(db)
                engine = QuestEngine(db)

                engine.observe(
                    Event(
                        kind="kill",
                        raw="kill",
                        actor="a skeleton",
                        target="You",
                        zone="West Zone",
                    )
                )

                step = self._step(db, quest)
                self.assertEqual(int(step["progress_count"]), 1)
                self.assertEqual(int(step["complete"]), 1)
            finally:
                db.close()

    def test_monitor_start_seed_respects_welcome_as_a_hard_boundary(self):
        parser = EQLogParser()
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "eqlog.txt"
            path.write_text(
                "You have entered West Zone.\n"
                "Welcome to EverQuest!\n",
                encoding="utf-8",
            )
            self.assertIsNone(_zone_context_from_log(path, parser))

            path.write_text(
                "You have entered West Zone.\n"
                "Welcome to EverQuest!\n"
                "You have entered East Zone.\n",
                encoding="utf-8",
            )
            self.assertEqual(_zone_context_from_log(path, parser), "East Zone")


if __name__ == "__main__":
    unittest.main()
