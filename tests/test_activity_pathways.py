from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from eqquest.activity_pathways import ActivityPathwayEngine, pathway_detail_text
from eqquest.db import Database
from eqquest.events import Event
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase


class ActivityPathwayEngineTests(unittest.TestCase):
    def _db(self, root: str) -> Database:
        return Database(Path(root) / "working.sqlite3")

    @staticmethod
    def _source(db: Database, key: str) -> int:
        return db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/db/quest.html?quest={key}",
            title=f"Activity pathway source {key}",
            entity_type="quest",
            sha256=f"sha-{key}",
            plain_text="reviewed structured quest objective",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=f"quest:{key}",
        )

    def test_kill_and_loot_activity_aggregate_into_exact_quest_pathway(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                page = self._source(db, "bloodsaber")
                quest = db.upsert_entity(kind="quest", name="Bloodsaber Investigation")
                db.add_quest_step(
                    quest,
                    1,
                    "Defeat Bloodsabers",
                    zone="Qeynos Catacombs",
                    match={"event": "kill", "npc": "a bloodsaber", "count": 10},
                    source_page_id=page,
                )
                db.add_quest_step(
                    quest,
                    2,
                    "Recover a Bloodsaber Blade",
                    zone="Qeynos Catacombs",
                    match={"event": "loot", "item": "Bloodsaber Blade", "count": 1},
                    source_page_id=page,
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

    def test_unprovenanced_structured_step_never_becomes_direct_pathway(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = db.upsert_entity(kind="quest", name="Unsourced Local Guess")
                db.add_quest_step(
                    quest,
                    1,
                    "Loot an Unsourced Token",
                    zone="Test Zone",
                    match={"event": "loot", "item": "Unsourced Token"},
                    source_page_id=None,
                )
                db.add_event(Event(kind="loot", raw="loot", item="Unsourced Token"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()

                self.assertEqual(engine.suggestions("Test Zone"), [])
            finally:
                db.close()

    def test_session_boundary_ignores_old_observations(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                page = self._source(db, "fresh")
                quest = db.upsert_entity(kind="quest", name="Fresh Session Quest")
                db.add_quest_step(
                    quest,
                    1,
                    "Loot the fresh token",
                    match={"event": "loot", "item": "Fresh Token"},
                    source_page_id=page,
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
                page = self._source(db, "prose")
                db.upsert_entity(kind="npc", name="a suspicious rat")
                quest = db.upsert_entity(kind="quest", name="Prose Only Quest")
                db.add_quest_step(
                    quest,
                    1,
                    "Kill a suspicious rat somewhere nearby",
                    match={"event": "kill"},
                    source_page_id=page,
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
                page = self._source(db, "tracked")
                quest = db.upsert_entity(kind="quest", name="Already Tracked")
                db.add_quest_step(
                    quest,
                    1,
                    "Loot the tracked token",
                    match={"event": "loot", "item": "Tracked Token"},
                    source_page_id=page,
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
                frequent_page = self._source(db, "frequent")
                single_page = self._source(db, "single")
                frequent = db.upsert_entity(kind="quest", name="Frequent Quest")
                single = db.upsert_entity(kind="quest", name="Single Quest")
                db.add_quest_step(
                    frequent,
                    1,
                    "Defeat repeated mob",
                    match={"event": "kill", "npc": "repeated mob"},
                    source_page_id=frequent_page,
                )
                db.add_quest_step(
                    single,
                    1,
                    "Defeat single mob",
                    match={"event": "kill", "npc": "single mob"},
                    source_page_id=single_page,
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

    def test_packaged_runtime_reads_immutable_knowledge_and_user_observations(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            working = root / "working.sqlite3"
            knowledge = root / "everquestie-knowledge.sqlite3"
            state = root / "everquestie-user.sqlite3"

            builder = Database(working)
            try:
                page = self._source(builder, "packaged")
                quest = builder.upsert_entity(kind="quest", name="Packaged Pathway Quest")
                builder.add_quest_step(
                    quest,
                    1,
                    "Loot a Packaged Token",
                    match={"event": "loot", "item": "Packaged Token"},
                    source_page_id=page,
                )
            finally:
                builder.close()
            create_knowledge_snapshot(
                working,
                knowledge,
                snapshot_version="activity-pathway-test",
                overwrite=True,
            )
            before = sha256(knowledge.read_bytes()).hexdigest()

            runtime = RuntimeDatabase(knowledge, state)
            try:
                engine = ActivityPathwayEngine(runtime)
                engine.reset_session(engine.latest_observed_event_id())
                runtime.add_event(
                    Event(
                        kind="loot",
                        raw="You have looted a Packaged Token.",
                        item="Packaged Token",
                    )
                )
                engine.refresh_observations()
                suggestions = engine.suggestions()
                self.assertEqual([s.quest_name for s in suggestions], ["Packaged Pathway Quest"])
            finally:
                runtime.close()

            self.assertEqual(sha256(knowledge.read_bytes()).hexdigest(), before)
            self.assertFalse(Path(str(knowledge) + "-wal").exists())
            self.assertFalse(Path(str(knowledge) + "-shm").exists())
            self.assertTrue(state.is_file())


if __name__ == "__main__":
    unittest.main()
