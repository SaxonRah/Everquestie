from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.loot_relevance import loot_relevance_text, recent_loot_relevance


class LootRelevanceTests(unittest.TestCase):
    def _db(self, tempdir: str) -> Database:
        return Database(Path(tempdir) / "working.sqlite3")

    def _source(self, db: Database, suffix: str = "1") -> int:
        return db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/db/quest.html?quest={suffix}",
            title=f"Quest {suffix}",
            entity_type="quest",
            sha256=f"sha-{suffix}",
            plain_text="structured quest source",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=f"quest:{suffix}",
        )

    def test_recent_loot_projects_reviewed_quest_uses_and_tracking_state(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                source = self._source(db)
                item = db.upsert_entity(
                    kind="item",
                    name="Bog Bark",
                    external_id="item:100",
                )
                turnin = db.upsert_entity(
                    kind="quest",
                    name="Bark for the Brewer",
                    external_id="quest:1",
                    source_page_id=source,
                    source_url="https://everquest.allakhazam.com/db/quest.html?quest=1",
                )
                loot = db.upsert_entity(
                    kind="quest",
                    name="Gather Bog Bark",
                    external_id="quest:2",
                    source_page_id=source,
                    source_url="https://everquest.allakhazam.com/db/quest.html?quest=2",
                )
                listed = db.upsert_entity(
                    kind="quest",
                    name="A Curious Bark",
                    external_id="quest:3",
                    source_page_id=source,
                    source_url="https://everquest.allakhazam.com/db/quest.html?quest=3",
                )
                db.upsert_relationship(
                    turnin,
                    item,
                    "objective_turn_in_item",
                    quantity=4,
                    source_page_id=source,
                    evidence="Bring back four Bog Bark to the brewer.",
                )
                db.upsert_relationship(
                    loot,
                    item,
                    "objective_loot",
                    quantity=2,
                    source_page_id=source,
                    evidence="Loot two Bog Bark.",
                )
                db.upsert_relationship(
                    listed,
                    item,
                    "quest_item",
                    source_page_id=source,
                    evidence="Quest Items: Bog Bark",
                )
                db.track_quest(loot)
                db.add_event(Event(kind="loot", raw="loot 1", item="Bog Bark"))
                db.add_event(Event(kind="loot", raw="loot 2", item="bog bark"))

                rows = recent_loot_relevance(db, 0)
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row.item_id, item)
                self.assertEqual(row.observed_count, 2)
                self.assertEqual(
                    [use.relation for use in row.uses],
                    ["objective_turn_in_item", "objective_loot", "quest_item"],
                )
                self.assertFalse(row.uses[0].tracked)
                self.assertTrue(row.uses[1].tracked)
                self.assertEqual(row.uses[0].quantity, 4)
                self.assertIn("turn-in item", row.primary_reason)

                text = loot_relevance_text(row)
                self.assertIn("Looted this monitoring session: 2", text)
                self.assertIn("Bark for the Brewer", text)
                self.assertIn("tracked", text)
                self.assertIn("does not mean the quest is owned", text)
                self.assertIn("not automatically vendor trash", text)
            finally:
                db.close()

    def test_session_boundary_excludes_old_loot(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                source = self._source(db)
                item = db.upsert_entity(kind="item", name="Old Coin", external_id="item:1")
                quest = db.upsert_entity(
                    kind="quest",
                    name="Coin Quest",
                    external_id="quest:coin",
                    source_page_id=source,
                )
                db.upsert_relationship(
                    quest,
                    item,
                    "objective_turn_in_item",
                    source_page_id=source,
                    evidence="Give Old Coin to the collector.",
                )
                db.add_event(Event(kind="loot", raw="old", item="Old Coin"))
                boundary = int(
                    db.conn.execute("SELECT MAX(id) AS n FROM observed_events").fetchone()["n"]
                )
                self.assertEqual(recent_loot_relevance(db, boundary), ())

                db.add_event(Event(kind="loot", raw="new", item="Old Coin"))
                rows = recent_loot_relevance(db, boundary)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].observed_count, 1)
            finally:
                db.close()

    def test_ambiguous_item_name_is_never_attached(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                source = self._source(db)
                first = db.upsert_entity(kind="item", name="Ancient Token", external_id="item:1")
                db.upsert_entity(kind="item", name="Ancient Token", external_id="item:2")
                quest = db.upsert_entity(
                    kind="quest",
                    name="Token Quest",
                    external_id="quest:token",
                    source_page_id=source,
                )
                db.upsert_relationship(
                    quest,
                    first,
                    "objective_turn_in_item",
                    source_page_id=source,
                    evidence="Give the Ancient Token.",
                )
                db.add_event(Event(kind="loot", raw="loot", item="Ancient Token"))
                self.assertEqual(recent_loot_relevance(db, 0), ())
            finally:
                db.close()

    def test_relationship_without_source_provenance_is_not_relevance(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                item = db.upsert_entity(kind="item", name="Mystery Scrap", external_id="item:1")
                quest = db.upsert_entity(
                    kind="quest",
                    name="Unproven Quest",
                    external_id="quest:unproven",
                )
                db.upsert_relationship(
                    quest,
                    item,
                    "objective_turn_in_item",
                    evidence="synthetic relationship without a source page",
                )
                db.add_event(Event(kind="loot", raw="loot", item="Mystery Scrap"))
                self.assertEqual(recent_loot_relevance(db, 0), ())
            finally:
                db.close()

    def test_items_without_reviewed_quest_use_stay_quiet(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                db.upsert_entity(kind="item", name="Vendor Pebble", external_id="item:1")
                db.add_event(Event(kind="loot", raw="loot", item="Vendor Pebble"))
                self.assertEqual(recent_loot_relevance(db, 0), ())
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
