from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.activity_pathways import ActivityPathwayEngine, pathway_detail_text
from eqquest.db import Database
from eqquest.events import Event


class ActivityPathwayEngineTests(unittest.TestCase):
    def _db(self, root: str) -> Database:
        return Database(Path(root) / "working.sqlite3")

    def test_kill_and_loot_activity_aggregate_into_exact_quest_pathway(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = db.upsert_entity(kind="quest", name="Bloodsaber Investigation")
                db.add_quest_step(
                    quest,
                    1,
                    "Defeat Bloodsabers",
                    zone="Qeynos Catacombs",
                    match={"event": "kill", "npc": "a bloodsaber", "count": 10},
                )
                db.add_quest_step(
                    quest,
                    2,
                    "Recover a Bloodsaber Blade",
                    zone="Qeynos Catacombs",
                    match={"event": "loot", "item": "Bloodsaber Blade", "count": 1},
                )

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                for _ in range(3):
                    db.add_event(Event(kind="kill", raw="kill", actor="a bloodsaber", target="You"))
                db.add_event(Event(kind="loot", raw="loot", item="Bloodsaber Blade"))
                engine.refresh_observations()

                suggestions = engine.suggestions("Qeynos Catacombs")
                self.assertEqual(len(suggestions), 1)
                suggestion = suggestions[0]
                self.assertEqual(suggestion.quest_id, quest)
                self.assertEqual(suggestion.quest_name, "Bloodsaber Investigation")
                self.assertEqual(len(suggestion.evidence), 2)
                self.assertGreaterEqual(suggestion.score, 100)

                detail = pathway_detail_text(suggestion)
                self.assertIn("a bloodsaber", detail)
                self.assertIn("Bloodsaber Blade", detail)
                self.assertIn("potential pathway", detail)
                self.assertIn("not proof", detail)
            finally:
                db.close()

    def test_session_boundary_ignores_old_observations(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = db.upsert_entity(kind="quest", name="Fresh Session Quest")
                db.add_quest_step(
                    quest,
                    1,
                    "Loot the fresh token",
                    match={"event": "loot", "item": "Fresh Token"},
                )
                db.add_event(Event(kind="loot", raw="old", item="Fresh Token"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(engine.latest_observed_event_id())
                engine.refresh_observations()
                self.assertEqual(engine.suggestions(), [])

                db.add_event(Event(kind="loot", raw="new", item="Fresh Token"))
                engine.refresh_observations()
                self.assertEqual([s.quest_id for s in engine.suggestions()], [quest])
            finally:
                db.close()

    def test_description_prose_without_structured_target_never_becomes_pathway(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                db.upsert_entity(kind="npc", name="a suspicious rat")
                quest = db.upsert_entity(kind="quest", name="Prose Only Quest")
                db.add_quest_step(
                    quest,
                    1,
                    "Kill a suspicious rat somewhere nearby",
                    match={"event": "kill"},
                )
                db.add_event(Event(kind="kill", raw="kill", actor="a suspicious rat"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()
                self.assertEqual(engine.suggestions(), [])
            finally:
                db.close()

    def test_tracked_quest_is_not_recommended_as_a_potential_pathway(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = db.upsert_entity(kind="quest", name="Already Tracked")
                db.add_quest_step(
                    quest,
                    1,
                    "Loot the tracked token",
                    match={"event": "loot", "item": "Tracked Token"},
                )
                db.track_quest(quest)
                db.add_event(Event(kind="loot", raw="loot", item="Tracked Token"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()
                self.assertEqual(engine.suggestions(), [])
            finally:
                db.close()

    def test_repeated_exact_activity_ranks_above_single_observation(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                frequent = db.upsert_entity(kind="quest", name="Frequent Quest")
                single = db.upsert_entity(kind="quest", name="Single Quest")
                db.add_quest_step(
                    frequent,
                    1,
                    "Defeat repeated mob",
                    match={"event": "kill", "npc": "repeated mob"},
                )
                db.add_quest_step(
                    single,
                    1,
                    "Defeat single mob",
                    match={"event": "kill", "npc": "single mob"},
                )
                for _ in range(5):
                    db.add_event(Event(kind="kill", raw="kill", actor="repeated mob"))
                db.add_event(Event(kind="kill", raw="kill", actor="single mob"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()
                suggestions = engine.suggestions()
                self.assertEqual([s.quest_id for s in suggestions[:2]], [frequent, single])
                self.assertGreater(suggestions[0].score, suggestions[1].score)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
