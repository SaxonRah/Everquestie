from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.quest_engine import QuestEngine
from eqquest.quest_progress_identity import (
    exact_entity_name_candidates,
    install_quest_progress_identity_policy,
)
from eqquest.runtime import RuntimeDatabase


class QuestObjectiveIdentityTests(unittest.TestCase):
    def setUp(self):
        install_quest_progress_identity_policy()

    @staticmethod
    def _source(db: Database, key: str, kind: str) -> int:
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

    def _npc(self, db: Database, external_id: str, *, source: bool = True) -> int:
        page = self._source(db, external_id, "npc") if source else None
        return db.upsert_entity(
            kind="npc",
            name="a skeleton",
            external_id=external_id,
            source_page_id=page,
        )

    def _item(self, db: Database, name: str, external_id: str) -> int:
        page = self._source(db, external_id, "item")
        return db.upsert_entity(
            kind="item",
            name=name,
            external_id=external_id,
            source_page_id=page,
        )

    def _zone(self, db: Database, name: str, key: str) -> int:
        page = self._source(db, key, "zone")
        return db.upsert_entity(
            kind="zone",
            name=name,
            external_id=key,
            source_page_id=page,
        )

    def _locate(self, db: Database, entity_id: int, zone_id: int, key: str, *, provenanced=True):
        source_page_id = self._source(db, key, "npc") if provenanced else None
        db.add_location(
            entity_id,
            zone_entity_id=zone_id,
            y=1.0,
            x=2.0,
            source_page_id=source_page_id,
            evidence="fixture location" if provenanced else "",
        )

    @staticmethod
    def _track_kill(db, npc_id: int, *, zone: str | None = None) -> int:
        quest = db.upsert_entity(kind="quest", name="Identity Hunt")
        db.add_quest_step(
            quest,
            1,
            "Kill a skeleton",
            zone=zone,
            match={"event": "kill", "npc": "a skeleton", "npc_entity_id": npc_id, "count": 1},
        )
        db.track_quest(quest)
        return quest

    @staticmethod
    def _track_loot(db, item_id: int, item_text: str) -> int:
        quest = db.upsert_entity(kind="quest", name="Identity Loot")
        db.add_quest_step(
            quest,
            1,
            f"Loot {item_text}",
            match={"event": "loot", "item": item_text, "item_entity_id": item_id, "count": 1},
        )
        db.track_quest(quest)
        return quest

    @staticmethod
    def _progress(db, quest_id: int) -> int:
        return int(db.quest_steps(quest_id)[0]["progress_count"])

    def test_unique_canonical_npc_identity_progresses(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                npc = self._npc(db, "npc:1")
                quest = self._track_kill(db, npc)
                QuestEngine(db).observe(
                    Event(kind="kill", raw="You have slain a skeleton!", actor="a skeleton", target="You")
                )
                self.assertEqual(self._progress(db, quest), 1)
            finally:
                db.close()

    def test_duplicate_canonical_npc_name_without_zone_fails_closed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                target = self._npc(db, "npc:west")
                self._npc(db, "npc:east")
                quest = self._track_kill(db, target)
                QuestEngine(db).observe(
                    Event(kind="kill", raw="You have slain a skeleton!", actor="a skeleton", target="You")
                )
                self.assertEqual(self._progress(db, quest), 0)
            finally:
                db.close()

    def test_provenanced_zone_can_uniquely_disambiguate_duplicate_npc(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                west = self._zone(db, "West Zone", "zone:west")
                east = self._zone(db, "East Zone", "zone:east")
                target = self._npc(db, "npc:west")
                other = self._npc(db, "npc:east")
                self._locate(db, target, west, "loc:west")
                self._locate(db, other, east, "loc:east")
                quest = self._track_kill(db, target, zone="West Zone")
                engine = QuestEngine(db)
                engine.seed_zone_context("West Zone")
                engine.observe(
                    Event(kind="kill", raw="You have slain a skeleton!", actor="a skeleton", target="You")
                )
                self.assertEqual(self._progress(db, quest), 1)
            finally:
                db.close()

    def test_duplicate_npcs_both_known_in_objective_zone_remain_ambiguous(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                west = self._zone(db, "West Zone", "zone:west")
                target = self._npc(db, "npc:1")
                other = self._npc(db, "npc:2")
                self._locate(db, target, west, "loc:1")
                self._locate(db, other, west, "loc:2")
                quest = self._track_kill(db, target, zone="West Zone")
                engine = QuestEngine(db)
                engine.seed_zone_context("West Zone")
                engine.observe(Event(kind="kill", raw="kill", actor="a skeleton", target="You"))
                self.assertEqual(self._progress(db, quest), 0)
            finally:
                db.close()

    def test_unknown_competing_npc_geography_prevents_zone_disambiguation(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                west = self._zone(db, "West Zone", "zone:west")
                target = self._npc(db, "npc:1")
                self._npc(db, "npc:2")
                self._locate(db, target, west, "loc:1")
                quest = self._track_kill(db, target, zone="West Zone")
                engine = QuestEngine(db)
                engine.seed_zone_context("West Zone")
                engine.observe(Event(kind="kill", raw="kill", actor="a skeleton", target="You"))
                self.assertEqual(self._progress(db, quest), 0)
            finally:
                db.close()

    def test_unsourced_location_cannot_disambiguate_duplicate_npc(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                west = self._zone(db, "West Zone", "zone:west")
                east = self._zone(db, "East Zone", "zone:east")
                target = self._npc(db, "npc:1")
                other = self._npc(db, "npc:2")
                self._locate(db, target, west, "manual:west", provenanced=False)
                self._locate(db, other, east, "loc:east")
                quest = self._track_kill(db, target, zone="West Zone")
                engine = QuestEngine(db)
                engine.seed_zone_context("West Zone")
                engine.observe(Event(kind="kill", raw="kill", actor="a skeleton", target="You"))
                self.assertEqual(self._progress(db, quest), 0)
            finally:
                db.close()

    def test_duplicate_item_canonical_name_fails_closed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                target = self._item(db, "Bone Chip", "item:1")
                self._item(db, "Bone Chip", "item:2")
                quest = self._track_loot(db, target, "Bone Chip")
                QuestEngine(db).observe(Event(kind="loot", raw="loot", item="Bone Chip"))
                self.assertEqual(self._progress(db, quest), 0)
            finally:
                db.close()

    def test_unique_item_alias_progresses_but_duplicate_alias_fails_closed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                target = self._item(db, "Ancient Bone Chip", "item:1")
                db.add_alias(target, "Bone Chip", alias_type="objective")
                quest = self._track_loot(db, target, "Bone Chip")
                QuestEngine(db).observe(Event(kind="loot", raw="loot", item="Bone Chip"))
                self.assertEqual(self._progress(db, quest), 1)
            finally:
                db.close()

        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                target = self._item(db, "Ancient Bone Chip", "item:1")
                other = self._item(db, "Weathered Bone Chip", "item:2")
                db.add_alias(target, "Bone Chip", alias_type="objective")
                db.add_alias(other, "Bone Chip", alias_type="objective")
                quest = self._track_loot(db, target, "Bone Chip")
                QuestEngine(db).observe(Event(kind="loot", raw="loot", item="Bone Chip"))
                self.assertEqual(self._progress(db, quest), 0)
            finally:
                db.close()

    def test_exact_canonical_name_takes_precedence_over_other_entity_alias(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                canonical = self._item(db, "Bone Chip", "item:canonical")
                alias_target = self._item(db, "Ancient Bone Chip", "item:alias")
                db.add_alias(alias_target, "Bone Chip", alias_type="objective")
                candidates = exact_entity_name_candidates(db, "item", "Bone Chip")
                self.assertEqual(candidates.match_kind, "exact")
                self.assertEqual(candidates.entity_ids, (canonical,))

                quest = self._track_loot(db, alias_target, "Bone Chip")
                QuestEngine(db).observe(Event(kind="loot", raw="loot", item="Bone Chip"))
                self.assertEqual(self._progress(db, quest), 0)
            finally:
                db.close()

    def test_runtime_split_uses_same_strict_identity_policy(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            working = root / "working.sqlite3"
            knowledge = root / "knowledge.sqlite3"
            state = root / "state.sqlite3"
            builder = Database(working)
            try:
                target = self._item(builder, "Ancient Bone Chip", "item:1")
                builder.add_alias(target, "Bone Chip", alias_type="objective")
                quest = self._track_loot(builder, target, "Bone Chip")
                builder.untrack_quest(quest)
            finally:
                builder.close()
            create_knowledge_snapshot(
                working,
                knowledge,
                snapshot_version="objective-identity-test",
                overwrite=True,
            )

            runtime = RuntimeDatabase(knowledge, state)
            try:
                quest_row, status = runtime.resolve_entity("Identity Loot", "quest")
                self.assertIsNotNone(quest_row)
                self.assertIn(status, {"exact", "alias", "unique"})
                quest_id = int(quest_row["id"])
                runtime.track_quest(quest_id)
                QuestEngine(runtime).observe(Event(kind="loot", raw="loot", item="Bone Chip"))
                self.assertEqual(int(runtime.quest_steps(quest_id)[0]["progress_count"]), 1)
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
