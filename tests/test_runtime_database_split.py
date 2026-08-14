from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase


class RuntimeDatabaseSplitTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def _build_snapshot(
        self,
        path: Path,
        *,
        quest_name: str = "A Portable Quest",
        dummy_first: bool = False,
        allakhazam_id: str = "",
    ) -> int:
        working = self.root / (path.stem + ".working.sqlite3")
        working.unlink(missing_ok=True)
        db = Database(working)
        try:
            if dummy_first:
                db.upsert_entity(kind="quest", name="A Different Quest", merge_by_name=True)

            source_page_id = None
            source_url = None
            external_namespace = None
            external_id = None
            if allakhazam_id:
                source_url = (
                    "https://everquest.allakhazam.com/db/quest.html?"
                    f"quest={allakhazam_id}"
                )
                source_page_id = db.upsert_source_page(
                    url=source_url,
                    title=quest_name,
                    entity_type="quest",
                    sha256="test",
                    plain_text="future mirror evidence",
                    raw_html="<html></html>",
                    source_name="Allakhazam",
                    source_kind="local_mirror",
                    source_key=f"quest/{allakhazam_id}.html",
                    source_version="future-test",
                )
                external_namespace = "allakhazam:quest"
                external_id = allakhazam_id

            quest_id = db.upsert_entity(
                kind="quest",
                name=quest_name,
                source_page_id=source_page_id,
                source_url=source_url,
                external_id=external_id,
                external_namespace=external_namespace,
                merge_by_name=True,
            )
            db.add_quest_step(
                quest_id,
                1,
                "Loot one Portable Token.",
                match={"event": "loot", "item": "Portable Token", "count": 1},
                source_page_id=source_page_id,
            )
        finally:
            db.close()

        create_knowledge_snapshot(
            working,
            path,
            snapshot_version=path.stem,
            overwrite=True,
        )
        return quest_id

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def test_packaged_knowledge_is_read_only_and_user_state_is_separate(self):
        knowledge = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"
        quest_id = self._build_snapshot(knowledge)
        before = self._digest(knowledge)

        db = RuntimeDatabase(knowledge, state)
        try:
            resolved, status = db.resolve_entity("A Portable Quest", "quest")
            self.assertIsNotNone(resolved)
            self.assertIn(status, {"exact", "unique"})
            self.assertEqual(int(resolved["id"]), quest_id)

            db.set_meta("map_root", r"C:\EverQuest\maps")
            db.add_event(
                Event(
                    kind="loot",
                    raw="You have looted a Portable Token.",
                    item="Portable Token",
                )
            )
            db.track_quest(quest_id)
            db.set_step_progress(quest_id, 1, 1, True)

            self.assertTrue(db.is_quest_tracked(quest_id))
            self.assertEqual(int(db.quest_steps(quest_id)[0]["complete"]), 1)
            self.assertEqual(db.get_meta("map_root"), r"C:\EverQuest\maps")

            with self.assertRaises(sqlite3.OperationalError):
                db.upsert_entity(kind="item", name="Runtime Must Not Write Knowledge")
        finally:
            db.close()

        self.assertEqual(self._digest(knowledge), before)
        self.assertFalse(Path(str(knowledge) + "-wal").exists())
        self.assertFalse(Path(str(knowledge) + "-shm").exists())
        self.assertTrue(state.is_file())

        db = RuntimeDatabase(knowledge, state)
        try:
            tracked = db.tracked_quests()
            self.assertEqual(len(tracked), 1)
            self.assertEqual(tracked[0]["name"], "A Portable Quest")
            self.assertEqual(
                int(db.quest_steps(int(tracked[0]["id"]))[0]["complete"]),
                1,
            )
            self.assertEqual(len(db.observed_event_history()), 1)
        finally:
            db.close()

    def test_state_survives_snapshot_row_id_change_and_future_provider_enrichment(self):
        knowledge = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"

        original_id = self._build_snapshot(knowledge)
        db = RuntimeDatabase(knowledge, state)
        try:
            db.track_quest(original_id)
            db.set_step_progress(original_id, 1, 1, True)
        finally:
            db.close()

        enriched_id = self._build_snapshot(
            knowledge,
            dummy_first=True,
            allakhazam_id="424242",
        )
        self.assertNotEqual(original_id, enriched_id)

        db = RuntimeDatabase(knowledge, state)
        try:
            tracked = db.tracked_quests()
            self.assertEqual(len(tracked), 1)
            self.assertEqual(int(tracked[0]["id"]), enriched_id)
            self.assertEqual(int(db.quest_steps(enriched_id)[0]["complete"]), 1)

            enriched = db.entity_by_namespaced_external_id(
                "allakhazam:quest",
                "424242",
            )
            self.assertIsNotNone(enriched)
            self.assertEqual(int(enriched["id"]), enriched_id)
        finally:
            db.close()

    def test_legacy_combined_database_state_migrates_once(self):
        legacy = self.root / "eqquest.sqlite3"
        knowledge = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"

        legacy_db = Database(legacy)
        try:
            quest_id = legacy_db.upsert_entity(
                kind="quest",
                name="Legacy Progress Quest",
                merge_by_name=True,
            )
            legacy_db.add_quest_step(
                quest_id,
                1,
                "Loot one Legacy Token.",
                match={"event": "loot", "item": "Legacy Token"},
            )
            legacy_db.track_quest(quest_id)
            legacy_db.set_step_progress(quest_id, 1, 1, True)
            legacy_db.add_event(
                Event(
                    kind="loot",
                    raw="You have looted a Legacy Token.",
                    item="Legacy Token",
                )
            )
            legacy_db.set_meta("map_root", "/legacy/maps")
        finally:
            legacy_db.close()

        create_knowledge_snapshot(
            legacy,
            knowledge,
            snapshot_version="legacy-migration-test",
        )

        db = RuntimeDatabase(knowledge, state, legacy_path=legacy)
        try:
            tracked = db.tracked_quests()
            self.assertEqual(len(tracked), 1)
            migrated_id = int(tracked[0]["id"])
            self.assertEqual(int(db.quest_steps(migrated_id)[0]["complete"]), 1)
            self.assertEqual(len(db.observed_event_history()), 1)
            self.assertEqual(db.get_meta("map_root"), "/legacy/maps")
        finally:
            db.close()

        db = RuntimeDatabase(knowledge, state, legacy_path=legacy)
        try:
            self.assertEqual(len(db.observed_event_history()), 1)
            self.assertEqual(len(db.tracked_quests()), 1)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
