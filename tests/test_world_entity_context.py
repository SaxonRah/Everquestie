from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.world_entity_context import (
    build_world_entity_context,
    world_entity_context_text,
)
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class WorldEntityContextTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

        self.client_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.client_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )
        self.client_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="397",
            external_namespace="eqclient:zone",
        )

        stone_page = self._source_page("zone:351", "The Stone Hive")
        blight_page = self._source_page("zone:202", "Blightfire Moors")
        mesa_page = self._source_page("zone:397", "Goru'kar Mesa")
        self.provider_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            source_page_id=stone_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=351",
            external_id="zone:351",
        )
        self.provider_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            source_page_id=blight_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=202",
            external_id="zone:202",
        )
        self.provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            source_page_id=mesa_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=397",
            external_id="zone:397",
        )
        self.db.upsert_relationship(
            self.provider_stone,
            self.provider_blight,
            "connected_to",
            source_page_id=stone_page,
            evidence="Blightfire Moors / south",
            data={"confidence": "structured", "direction": "south"},
        )

        self.npc_page = self._source_page("npc:1001", "Scout Fana", entity_type="npc")
        self.scout = self.db.upsert_entity(
            kind="npc",
            name="Scout Fana",
            source_page_id=self.npc_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1001",
            external_id="npc:1001",
            level_min=46,
            level_max=46,
            data={
                "npc_type": "Quest NPC",
                "expansion": "The Serpent's Spine",
                "npc_added": "2006",
            },
        )
        self.db.add_alias(
            self.scout,
            "Fana",
            alias_type="source",
            source_page_id=self.npc_page,
        )
        self.db.upsert_relationship(
            self.scout,
            self.provider_stone,
            "found_in",
            source_page_id=self.npc_page,
            evidence="Known Habitats: The Stone Hive",
            data={"confidence": "structured", "source_field": "Known Habitats"},
        )
        self.db.add_location(
            self.scout,
            zone_entity_id=self.provider_stone,
            y=125.0,
            x=-42.0,
            z=7.0,
            label="quest starter",
            source_page_id=self.npc_page,
            evidence="Scout Fana at 125, -42, 7",
            data={"coordinate_convention": "eq_y_x"},
        )

        lost_page = self._source_page("npc:1002", "Lost Scout", entity_type="npc")
        self.lost = self.db.upsert_entity(
            kind="npc",
            name="Lost Scout",
            source_page_id=lost_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1002",
            external_id="npc:1002",
        )
        self.db.upsert_relationship(
            self.lost,
            self.provider_mesa,
            "found_in",
            source_page_id=lost_page,
            evidence="Known Habitats: Goru'kar Mesa",
            data={"confidence": "structured"},
        )
        self.db.add_location(
            self.lost,
            zone_entity_id=self.provider_mesa,
            y=10.0,
            x=20.0,
            label="reported spawn",
            source_page_id=lost_page,
            evidence="Lost Scout at 10, 20",
        )

        self.quest_page = self._source_page(
            "quest:5001", "A Hive Inquiry", entity_type="quest"
        )
        self.quest = self.db.upsert_entity(
            kind="quest",
            name="A Hive Inquiry",
            source_page_id=self.quest_page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=5001",
            external_id="quest:5001",
            level_min=45,
            level_max=50,
            data={"quest_type": "Task", "repeatable": "No", "group_size": "1"},
        )
        self.item = self.db.upsert_entity(
            kind="item",
            name="Hive Sample",
            external_id="item:9001",
            source_url="https://everquest.allakhazam.com/db/item.html?item=9001",
        )
        self.db.upsert_relationship(
            self.quest,
            self.provider_stone,
            "occurs_in",
            source_page_id=self.quest_page,
            evidence="Where: The Stone Hive",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            self.quest,
            self.scout,
            "started_by",
            source_page_id=self.quest_page,
            evidence="Quest Started By: Scout Fana",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            self.quest,
            self.item,
            "quest_item",
            source_page_id=self.quest_page,
            evidence="Quest Items: Hive Sample",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            self.quest,
            self.scout,
            "objective_speak",
            source_page_id=self.quest_page,
            evidence="Speak with Scout Fana",
            data={"derived_from": "quest_objective"},
        )
        self.db.add_quest_step(
            self.quest,
            1,
            "Speak with Scout Fana",
            zone="The Stone Hive",
            match={"event": "npc_say", "npc_entity_id": self.scout, "count": 1},
            source_page_id=self.quest_page,
        )
        self.db.add_quest_step(
            self.quest,
            2,
            "Loot one Hive Sample",
            zone="The Stone Hive",
            match={"event": "loot", "item_entity_id": self.item, "count": 1},
            source_page_id=self.quest_page,
        )

        ProviderZoneReconciliationCatalog(self.db).reconcile()

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _source_page(self, key: str, title: str, *, entity_type: str = "zone") -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/{key.replace(':', '/')}",
            title=title,
            entity_type=entity_type,
            sha256=key,
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="mirror-2026-08-14",
        )

    def test_npc_context_projects_linked_provider_zone_and_explicit_location(self):
        context, status = build_world_entity_context(self.db, "Scout Fana", "npc")
        self.assertEqual(status, "exact")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.level_min, 46)
        self.assertEqual(context.data.get("npc_type"), "Quest NPC")
        found = next(row for row in context.relationships if row.relation == "found_in")
        self.assertEqual(found.other_entity_id, self.provider_stone)
        self.assertEqual(found.display_other_entity_id, self.client_stone)
        self.assertEqual(found.display_other_name, "The Stone Hive")
        self.assertEqual(found.zone_projection_status, "linked_provider")
        self.assertEqual(found.projected_from_zone_entity_id, self.provider_stone)
        self.assertEqual(len(context.locations), 1)
        location = context.locations[0]
        self.assertTrue(location.navigable)
        self.assertEqual(location.gameplay_zone_entity_id, self.client_stone)
        self.assertEqual(location.loc_text, "Y=125 X=-42 Z=7")

    def test_candidate_provider_location_stays_visible_but_never_becomes_map_target(self):
        context, status = build_world_entity_context(self.db, "Lost Scout", "npc")
        self.assertEqual(status, "exact")
        self.assertIsNotNone(context)
        assert context is not None
        found = next(row for row in context.relationships if row.relation == "found_in")
        self.assertEqual(found.display_other_entity_id, self.provider_mesa)
        self.assertEqual(found.zone_projection_status, "provider_candidate")
        location = context.locations[0]
        self.assertEqual(location.original_zone_entity_id, self.provider_mesa)
        self.assertIsNone(location.gameplay_zone_entity_id)
        self.assertEqual(location.zone_projection_status, "provider_candidate")
        self.assertFalse(location.navigable)
        text = world_entity_context_text(self.db, "Lost Scout", "npc")
        self.assertIn("provider_candidate", text)
        self.assertIn("not map-targetable", text)

    def test_quest_context_combines_graph_steps_and_actor_locations_without_user_progress(self):
        context, status = build_world_entity_context(self.db, "A Hive Inquiry", "quest")
        self.assertEqual(status, "exact")
        self.assertIsNotNone(context)
        assert context is not None
        occurs = next(row for row in context.relationships if row.relation == "occurs_in")
        self.assertEqual(occurs.display_other_entity_id, self.client_stone)
        self.assertEqual(occurs.zone_projection_status, "linked_provider")
        starter = next(row for row in context.relationships if row.relation == "started_by")
        self.assertEqual(starter.display_other_name, "Scout Fana")
        self.assertEqual([step.step_order for step in context.quest_steps], [1, 2])
        self.assertEqual(context.quest_steps[0].match["event"], "npc_say")
        self.assertEqual(len(context.related_locations), 1)
        actor = context.related_locations[0]
        self.assertEqual(actor.entity_id, self.scout)
        self.assertTrue(actor.navigable)
        self.assertEqual(actor.gameplay_zone_entity_id, self.client_stone)
        self.assertIn(actor.relation, {"started_by", "objective_speak"})
        text = world_entity_context_text(self.db, "A Hive Inquiry", "quest")
        self.assertIn("Structured quest steps:", text)
        self.assertIn("Quest actor locations (explicit evidence):", text)
        self.assertNotIn("progress", text.casefold())

    def test_resolution_refuses_unique_substring_but_accepts_exact_alias(self):
        context, status = build_world_entity_context(self.db, "Scout", "npc")
        self.assertIsNone(context)
        self.assertEqual(status, "missing")
        context, status = build_world_entity_context(self.db, "Fana", "npc")
        self.assertEqual(status, "alias")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.entity_id, self.scout)

    def test_finalized_runtime_exposes_same_context_read_only(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="world-entity-context-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            npc, status = build_world_entity_context(runtime, "Scout Fana", "npc")
            self.assertEqual(status, "exact")
            self.assertIsNotNone(npc)
            assert npc is not None
            self.assertEqual(npc.locations[0].gameplay_zone_entity_id, self.client_stone)
            quest, status = build_world_entity_context(runtime, "A Hive Inquiry", "quest")
            self.assertEqual(status, "exact")
            self.assertIsNotNone(quest)
            assert quest is not None
            self.assertEqual(len(quest.quest_steps), 2)
            self.assertEqual(quest.related_locations[0].gameplay_zone_entity_id, self.client_stone)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_relationships SET evidence='changed'")
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
