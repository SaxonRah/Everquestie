from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.activity_pathways import ActivityPathwayEngine, pathway_detail_text
from eqquest.db import Database
from eqquest.events import Event


class ActivityPathwayGraphChainTests(unittest.TestCase):
    def _db(self, root: str) -> Database:
        return Database(Path(root) / "working.sqlite3")

    @staticmethod
    def _source(db: Database, key: str) -> int:
        return db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/db/quest.html?quest={key}",
            title=f"Test source {key}",
            entity_type="quest",
            sha256=f"sha-{key}",
            plain_text="structured test evidence",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=f"quest:{key}",
        )

    def test_looted_turn_in_item_surfaces_quest_without_fake_loot_step(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                page = self._source(db, "turnin")
                quest = db.upsert_entity(kind="quest", name="Turn-In Opportunity")
                item = db.upsert_entity(kind="item", name="Ancient Token")
                npc = db.upsert_entity(kind="npc", name="Keeper Test")
                db.add_quest_step(
                    quest,
                    1,
                    "Give Ancient Token to Keeper Test",
                    match={"event": "npc_say", "npc_entity_id": npc, "npc": "Keeper Test"},
                    source_page_id=page,
                )
                db.upsert_relationship(
                    quest,
                    item,
                    "objective_turn_in_item",
                    quantity=1,
                    source_page_id=page,
                    evidence="Give Ancient Token to Keeper Test",
                )
                db.add_event(Event(kind="loot", raw="loot", item="Ancient Token"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()
                suggestions = engine.suggestions()

                self.assertEqual([s.quest_id for s in suggestions], [quest])
                evidence = suggestions[0].evidence[0]
                self.assertEqual(evidence.path_kind, "loot_turn_in")
                self.assertEqual(evidence.related_item, "Ancient Token")
                detail = pathway_detail_text(suggestions[0])
                self.assertIn("structured turn-in objective", detail)
                self.assertIn("Give Ancient Token to Keeper Test", detail)
            finally:
                db.close()

    def test_observed_mob_can_chain_through_drop_to_quest_item(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                page = self._source(db, "dropchain")
                quest = db.upsert_entity(kind="quest", name="Drop Chain Quest")
                item = db.upsert_entity(kind="item", name="Bloodied Emblem")
                npc = db.upsert_entity(kind="npc", name="a bloodsaber")
                db.upsert_relationship(
                    item,
                    npc,
                    "drops_from",
                    source_page_id=page,
                    evidence="Drops: Qeynos Catacombs / a bloodsaber",
                )
                db.upsert_relationship(
                    quest,
                    item,
                    "objective_loot",
                    quantity=2,
                    source_page_id=page,
                    evidence="Loot two Bloodied Emblems",
                )
                db.add_event(Event(kind="kill", raw="kill", actor="a bloodsaber"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()
                suggestions = engine.suggestions()

                self.assertEqual([s.quest_id for s in suggestions], [quest])
                evidence = suggestions[0].evidence[0]
                self.assertEqual(evidence.path_kind, "mob_drop_quest")
                self.assertEqual(evidence.related_item, "Bloodied Emblem")
                detail = pathway_detail_text(suggestions[0])
                self.assertIn("a bloodsaber → drops Bloodied Emblem", detail)
                self.assertIn("Loot two Bloodied Emblems", detail)
            finally:
                db.close()

    def test_unprovenanced_relationships_never_create_graph_pathways(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                quest = db.upsert_entity(kind="quest", name="Unprovenanced Quest")
                item = db.upsert_entity(kind="item", name="Unprovenanced Item")
                npc = db.upsert_entity(kind="npc", name="unprovenanced mob")
                db.upsert_relationship(item, npc, "drops_from", evidence="no page")
                db.upsert_relationship(
                    quest,
                    item,
                    "objective_turn_in_item",
                    evidence="no page",
                )
                db.add_event(Event(kind="loot", raw="loot", item="Unprovenanced Item"))
                db.add_event(Event(kind="kill", raw="kill", actor="unprovenanced mob"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()
                self.assertEqual(engine.suggestions(), [])
            finally:
                db.close()

    def test_ambiguous_npc_name_does_not_choose_one_drop_identity(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                page = self._source(db, "ambiguous")
                quest = db.upsert_entity(kind="quest", name="Ambiguous Drop Quest")
                item = db.upsert_entity(kind="item", name="Identity Token")
                npc_one = db.upsert_entity(
                    kind="npc",
                    name="a shared mob",
                    external_id="npc:one",
                )
                db.upsert_entity(
                    kind="npc",
                    name="a shared mob",
                    external_id="npc:two",
                )
                db.upsert_relationship(
                    item,
                    npc_one,
                    "drops_from",
                    source_page_id=page,
                    evidence="specific provider identity",
                )
                db.upsert_relationship(
                    quest,
                    item,
                    "objective_loot",
                    source_page_id=page,
                    evidence="Loot Identity Token",
                )
                db.add_event(Event(kind="kill", raw="kill", actor="a shared mob"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()
                self.assertEqual(engine.suggestions(), [])
            finally:
                db.close()

    def test_ambiguous_item_name_does_not_attach_turn_in_relationship(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                page = self._source(db, "ambiguous-item")
                quest = db.upsert_entity(kind="quest", name="Ambiguous Item Quest")
                item_one = db.upsert_entity(
                    kind="item",
                    name="Shared Token",
                    external_id="item:one",
                )
                db.upsert_entity(
                    kind="item",
                    name="Shared Token",
                    external_id="item:two",
                )
                db.upsert_relationship(
                    quest,
                    item_one,
                    "objective_turn_in_item",
                    source_page_id=page,
                    evidence="Give Shared Token to someone",
                )
                db.add_event(Event(kind="loot", raw="loot", item="Shared Token"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()
                self.assertEqual(engine.suggestions(), [])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
