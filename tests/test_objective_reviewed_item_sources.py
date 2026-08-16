from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.objective_reviewed_item_sources import augment_objective_with_reviewed_item_sources
from eqquest.quest_objective_navigation import tracked_quest_objective_navigation


class ObjectiveReviewedItemSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
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
            url=f"https://everquest.allakhazam.com/{key}",
            title=title,
            entity_type=entity_type,
            sha256=f"sha-{key}",
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="reviewed-source-test",
        )

    def _quest(self, name: str = "Collect Samples") -> tuple[int, int]:
        page = self._page("quest/collect", name, "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name=name,
            external_id=f"quest:{name}",
            source_page_id=page,
        )
        return quest, page

    def _item(self, name: str = "Hive Sample") -> int:
        page = self._page("item/sample", name, "item")
        return self.db.upsert_entity(
            kind="item",
            name=name,
            external_id=f"item:{name}",
            source_page_id=page,
        )

    def _npc(self, name: str, zone_id: int, *, y: float = 10.0, x: float = 20.0):
        page = self._page(f"npc/{name}", name, "npc")
        npc = self.db.upsert_entity(
            kind="npc",
            name=name,
            external_id=f"npc:{name}",
            source_page_id=page,
        )
        self.db.add_location(
            npc,
            zone_entity_id=zone_id,
            y=y,
            x=x,
            z=5.0,
            label="known location",
            source_page_id=page,
            evidence=f"{name} at {y}, {x}",
        )
        return npc, page

    def _loot_step(
        self,
        quest: int,
        quest_page: int | None,
        item: int,
        *,
        zone: str,
        event: str = "loot",
    ) -> None:
        self.db.add_quest_step(
            quest,
            1,
            "Collect 2 Hive Samples",
            zone=zone,
            match={"event": event, "item_entity_id": item, "count": 2},
            source_page_id=quest_page,
        )

    def _base(self, quest: int, current_zone: str = "The Stone Hive"):
        return tracked_quest_objective_navigation(
            self.db,
            quest,
            current_zone,
            step_order=1,
        )

    def test_remote_exact_loot_item_uses_independent_reviewed_drop_source(self):
        quest, quest_page = self._quest()
        item = self._item()
        dropper, drop_page = self._npc("A Blight Worker", self.blight, y=44.0, x=55.0)
        self._loot_step(quest, quest_page, item, zone="Blightfire Moors")
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=drop_page,
            evidence="Hive Sample is a reviewed drop from A Blight Worker.",
            data={"confidence": "reviewed_global_drop"},
        )

        base = self._base(quest)
        self.assertTrue(base.route_ready)
        self.assertEqual(base.route_choices[0].location_choice_count, 0)

        result = augment_objective_with_reviewed_item_sources(
            self.db, base, "The Stone Hive"
        )

        self.assertTrue(result.route_ready)
        self.assertEqual(len(result.route_choices), 1)
        route = result.route_choices[0]
        self.assertEqual(route.zone_name, "Blightfire Moors")
        self.assertEqual(route.location_choice_count, 1)
        self.assertEqual(route.target_labels, ("A Blight Worker (drops from)",))
        self.assertIn("reviewed source NPC", result.reason)

    def test_current_zone_exact_loot_item_upgrades_no_coordinate_to_map_source(self):
        quest, quest_page = self._quest("Local Samples")
        item = self._item("Local Sample")
        dropper, drop_page = self._npc("A Local Worker", self.stone, y=31.0, x=41.0)
        self.db.add_quest_step(
            quest,
            1,
            "Collect Local Samples",
            zone="The Stone Hive",
            match={"event": "loot", "item_entity_id": item, "count": 3},
            source_page_id=quest_page,
        )
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=drop_page,
            evidence="Local Sample is a reviewed drop from A Local Worker.",
        )

        base = self._base(quest)
        self.assertEqual(base.status, "current_zone_no_coordinate")

        result = augment_objective_with_reviewed_item_sources(
            self.db, base, "The Stone Hive"
        )

        self.assertTrue(result.map_ready)
        self.assertEqual(len(result.map_choices), 1)
        choice = result.map_choices[0]
        self.assertEqual(choice.location_entity_id, dropper)
        self.assertEqual(choice.relation, "objective_source_creature")
        self.assertEqual(choice.relation_label, "reviewed loot source")
        self.assertEqual(choice.origin, "quest_objective_reviewed_item_source")
        self.assertEqual((choice.y, choice.x), (31.0, 41.0))

    def test_step_zone_constrains_reviewed_sources_and_prevents_wrong_zone_override(self):
        quest, quest_page = self._quest("Constrained Samples")
        item = self._item("Constrained Sample")
        wrong, wrong_page = self._npc("Wrong Zone Worker", self.stone)
        self.db.add_quest_step(
            quest,
            1,
            "Collect the sample in Blightfire Moors",
            zone="Blightfire Moors",
            match={"event": "loot", "item_entity_id": item, "count": 1},
            source_page_id=quest_page,
        )
        self.db.upsert_relationship(
            item,
            wrong,
            "drops_from",
            source_page_id=wrong_page,
            evidence="The item globally drops here too.",
        )

        base = self._base(quest)
        result = augment_objective_with_reviewed_item_sources(
            self.db, base, "The Stone Hive"
        )

        self.assertEqual(result, base)
        self.assertTrue(result.route_ready)
        self.assertEqual(result.route_choices[0].zone_name, "Blightfire Moors")
        self.assertEqual(result.route_choices[0].location_choice_count, 0)
        self.assertNotIn("Wrong Zone Worker", " ".join(result.route_choices[0].target_labels))

    def test_unprovenanced_drop_does_not_upgrade_objective_navigation(self):
        quest, quest_page = self._quest("Unprovenanced Samples")
        item = self._item("Unprovenanced Sample")
        dropper, _drop_page = self._npc("Rumored Worker", self.stone)
        self.db.add_quest_step(
            quest,
            1,
            "Collect rumored samples",
            zone="The Stone Hive",
            match={"event": "loot", "item_entity_id": item, "count": 1},
            source_page_id=quest_page,
        )
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=None,
            evidence="Unreviewed rumor.",
        )

        base = self._base(quest)
        result = augment_objective_with_reviewed_item_sources(
            self.db, base, "The Stone Hive"
        )

        self.assertEqual(result, base)
        self.assertEqual(result.status, "current_zone_no_coordinate")

    def test_unresolved_step_zone_is_not_overridden_by_global_drop_graph(self):
        quest, quest_page = self._quest("Unknown Zone Samples")
        item = self._item("Unknown Zone Sample")
        dropper, drop_page = self._npc("Known Worker", self.stone)
        self.db.add_quest_step(
            quest,
            1,
            "Collect samples in an unknown place",
            zone="Unresolved Objective Zone",
            match={"event": "loot", "item_entity_id": item, "count": 1},
            source_page_id=quest_page,
        )
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=drop_page,
            evidence="Reviewed global drop.",
        )

        base = self._base(quest)
        self.assertEqual(base.status, "step_zone_unresolved")
        result = augment_objective_with_reviewed_item_sources(
            self.db, base, "The Stone Hive"
        )
        self.assertEqual(result, base)

    def test_non_loot_item_step_is_not_reinterpreted_as_drop_objective(self):
        quest, quest_page = self._quest("Receive Samples")
        item = self._item("Received Sample")
        dropper, drop_page = self._npc("Dropping Worker", self.stone)
        self.db.add_quest_step(
            quest,
            1,
            "Receive the sample",
            zone="The Stone Hive",
            match={"event": "receive_item", "item_entity_id": item, "count": 1},
            source_page_id=quest_page,
        )
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=drop_page,
            evidence="The item can drop, but this step only says receive it.",
        )

        base = self._base(quest)
        result = augment_objective_with_reviewed_item_sources(
            self.db, base, "The Stone Hive"
        )
        self.assertEqual(result, base)

    def test_step_without_source_provenance_cannot_use_global_drop_fallback(self):
        quest, _quest_page = self._quest("Unsourced Samples")
        item = self._item("Unsourced Sample")
        dropper, drop_page = self._npc("Reviewed Worker", self.stone)
        self.db.add_quest_step(
            quest,
            1,
            "Collect an unsourced sample",
            zone="The Stone Hive",
            match={"event": "loot", "item_entity_id": item, "count": 1},
            source_page_id=None,
        )
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=drop_page,
            evidence="Reviewed drop evidence exists independently.",
        )

        base = self._base(quest)
        result = augment_objective_with_reviewed_item_sources(
            self.db, base, "The Stone Hive"
        )
        self.assertEqual(result, base)


if __name__ == "__main__":
    unittest.main()
