from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_map_choices import knowledge_map_choices
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class KnowledgeRelatedLocationChoiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _page(self, key: str, title: str, entity_type: str) -> int:
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

    def _located_npc(self, name: str, key: str, *, zone_id: int | None = None, y: float = 10.0, x: float = 20.0) -> tuple[int, int]:
        page = self._page(key, name, "npc")
        npc = self.db.upsert_entity(
            kind="npc",
            name=name,
            external_id=key,
            source_page_id=page,
            source_url=f"https://everquest.allakhazam.com/{key}",
        )
        self.db.add_location(
            npc,
            zone_entity_id=self.stone if zone_id is None else zone_id,
            y=y,
            x=x,
            z=5.0,
            label="known location",
            source_page_id=page,
            evidence=f"{name} at {y}, {x}",
        )
        return npc, page

    def test_item_dropper_and_turnin_npc_locations_are_safe_choices(self):
        dropper, drop_page = self._located_npc("A Stone Worker", "npc:4001", y=100.0, x=-50.0)
        turnin, turn_page = self._located_npc("Scout Fana", "npc:4002", y=200.0, x=-75.0)
        item_page = self._page("item:7001", "Hive Sample", "item")
        item = self.db.upsert_entity(
            kind="item",
            name="Hive Sample",
            external_id="item:7001",
            source_page_id=item_page,
        )
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=drop_page,
            evidence="Dropped by A Stone Worker",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            item,
            turnin,
            "turn_in_to",
            source_page_id=turn_page,
            evidence="Turn in to Scout Fana",
            data={"confidence": "structured"},
        )

        result = knowledge_map_choices(self.db, item, "The Stone Hive")
        self.assertTrue(result.ready)
        self.assertEqual(len(result.choices), 2)
        by_relation = {choice.relation: choice for choice in result.choices}
        self.assertEqual(by_relation["drops_from"].origin, "related_entity")
        self.assertEqual(by_relation["drops_from"].relation_label, "drops from")
        self.assertEqual(by_relation["drops_from"].location_entity_name, "A Stone Worker")
        self.assertEqual(by_relation["turn_in_to"].relation_label, "turn-in NPC")
        self.assertIn("A Stone Worker (drops from)", by_relation["drops_from"].map_label)
        self.assertIn("Allakhazam mirror-2026-08-14", by_relation["drops_from"].source_labels)

    def test_vendor_relationship_uses_reverse_graph_direction_without_synthetic_edge(self):
        vendor, vendor_page = self._located_npc("Merchant Omi", "npc:4101")
        item_page = self._page("item:7101", "Hive Ration", "item")
        item = self.db.upsert_entity(
            kind="item",
            name="Hive Ration",
            external_id="item:7101",
            source_page_id=item_page,
        )
        self.db.upsert_relationship(
            vendor,
            item,
            "sells",
            source_page_id=vendor_page,
            evidence="Merchant inventory",
            data={"confidence": "structured"},
        )

        result = knowledge_map_choices(self.db, item, "The Stone Hive")
        self.assertTrue(result.ready)
        self.assertEqual(len(result.choices), 1)
        choice = result.choices[0]
        self.assertEqual(choice.relation, "sells")
        self.assertEqual(choice.relation_label, "vendor")
        self.assertEqual(choice.location_entity_id, vendor)
        self.assertEqual(choice.map_label, "Merchant Omi (vendor)")
        relationships = self.db.relationships_for_entity(item)
        sells = [row for row in relationships if row["relation"] == "sells"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0]["direction"], "in")

    def test_spell_teacher_and_skill_trainer_can_supply_locations(self):
        trainer, page = self._located_npc("Guild Trainer", "npc:4201")
        spell = self.db.upsert_entity(kind="spell", name="Hive Ward", external_id="spell:8101")
        skill = self.db.upsert_entity(kind="skill", name="Hive Lore", external_id="skill:8201")
        self.db.upsert_relationship(
            trainer,
            spell,
            "teaches_spell",
            source_page_id=page,
            evidence="Teaches Hive Ward",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            trainer,
            skill,
            "trains_skill",
            source_page_id=page,
            evidence="Trains Hive Lore",
            data={"confidence": "structured"},
        )
        spell_result = knowledge_map_choices(self.db, spell, "The Stone Hive")
        skill_result = knowledge_map_choices(self.db, skill, "The Stone Hive")
        self.assertEqual(spell_result.choices[0].relation_label, "spell teacher")
        self.assertEqual(skill_result.choices[0].relation_label, "trainer")
        self.assertEqual(spell_result.choices[0].location_entity_id, trainer)
        self.assertEqual(skill_result.choices[0].location_entity_id, trainer)

    def test_related_npc_candidate_provider_location_is_not_actionable(self):
        self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="397",
            external_namespace="eqclient:zone",
        )
        mesa_page = self._page("zone:397", "Goru'kar Mesa", "zone")
        provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="zone:397",
            source_page_id=mesa_page,
        )
        dropper, drop_page = self._located_npc(
            "Mesa Worker",
            "npc:4301",
            zone_id=provider_mesa,
        )
        item = self.db.upsert_entity(kind="item", name="Mesa Sample", external_id="item:7301")
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=drop_page,
            evidence="Dropped by Mesa Worker",
            data={"confidence": "structured"},
        )
        ProviderZoneReconciliationCatalog(self.db).reconcile()

        result = knowledge_map_choices(self.db, item, "Goru'kar Mesa")
        self.assertFalse(result.ready)
        self.assertEqual(result.status, "no_navigable_location")
        self.assertEqual(result.choices, ())

    def test_finalized_runtime_keeps_related_location_choice_read_only(self):
        dropper, page = self._located_npc("Runtime Worker", "npc:4401", y=55.0, x=-22.0)
        item = self.db.upsert_entity(kind="item", name="Runtime Sample", external_id="item:7401")
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=page,
            evidence="Runtime dropper",
            data={"confidence": "structured"},
        )
        builder = knowledge_map_choices(self.db, item, "The Stone Hive")
        self.assertTrue(builder.ready)

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="related-location-choice-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            packaged = knowledge_map_choices(runtime, item, "The Stone Hive")
            self.assertEqual(packaged.status, builder.status)
            self.assertEqual(packaged.choices, builder.choices)
            self.assertEqual(packaged.choices[0].relation_label, "drops from")
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_relationships SET evidence='changed'")
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
