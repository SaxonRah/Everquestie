from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.objective_reviewed_item_sources import (
    quest_objective_navigation_with_reviewed_sources,
)


class ZoneOpportunityReviewedSourcesTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
        self.zone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
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
            source_version="zone-opportunity-source-test",
        )

    def test_untracked_zone_opportunity_loot_step_gets_same_reviewed_source_map_result(self):
        quest_page = self._page("quest/local", "Local Collection", "quest")
        item_page = self._page("item/local", "Local Sample", "item")
        npc_page = self._page("npc/local", "A Local Worker", "npc")
        quest = self.db.upsert_entity(
            kind="quest",
            name="Local Collection",
            external_id="quest:local-collection",
            source_page_id=quest_page,
        )
        item = self.db.upsert_entity(
            kind="item",
            name="Local Sample",
            external_id="item:local-sample",
            source_page_id=item_page,
        )
        npc = self.db.upsert_entity(
            kind="npc",
            name="A Local Worker",
            external_id="npc:local-worker",
            source_page_id=npc_page,
        )
        self.db.add_quest_step(
            quest,
            7,
            "Collect three Local Samples",
            zone="The Stone Hive",
            match={"event": "loot", "item_entity_id": item, "count": 3},
            source_page_id=quest_page,
        )
        self.db.add_location(
            npc,
            zone_entity_id=self.zone,
            y=31.0,
            x=41.0,
            z=5.0,
            label="known location",
            source_page_id=npc_page,
            evidence="A Local Worker at 31, 41",
        )
        self.db.upsert_relationship(
            item,
            npc,
            "drops_from",
            source_page_id=npc_page,
            evidence="Local Sample is a reviewed drop from A Local Worker.",
        )

        # Zone Opportunities are intentionally untracked. The shared public objective
        # navigator must still accept an explicitly selected step_order and apply the
        # same reviewed source rules used by tracked Guidance.
        self.assertFalse(self.db.is_quest_tracked(quest))
        result = quest_objective_navigation_with_reviewed_sources(
            self.db,
            quest,
            "The Stone Hive",
            step_order=7,
        )

        self.assertTrue(result.map_ready)
        self.assertEqual(len(result.map_choices), 1)
        choice = result.map_choices[0]
        self.assertEqual(choice.location_entity_id, npc)
        self.assertEqual(choice.origin, "quest_objective_reviewed_item_source")
        self.assertEqual(choice.relation_label, "reviewed loot source")
        self.assertEqual((choice.y, choice.x), (31.0, 41.0))

    def test_installer_binds_zone_opportunity_module_to_shared_public_navigator(self):
        from eqquest import app as app_module
        from eqquest import zone_opportunities_ui as zone_ui
        from eqquest.objective_reviewed_item_sources_ui import (
            install_objective_reviewed_item_sources_ui,
        )
        from eqquest.packaged_ui_policy import install_packaged_ui_policy

        install_packaged_ui_policy()
        install_objective_reviewed_item_sources_ui()

        self.assertTrue(
            getattr(
                app_module.EverQuestieApp,
                "_everquestie_objective_reviewed_item_sources_ui",
                False,
            )
        )
        self.assertIs(
            zone_ui.tracked_quest_objective_navigation,
            quest_objective_navigation_with_reviewed_sources,
        )

        before = zone_ui.tracked_quest_objective_navigation
        install_objective_reviewed_item_sources_ui()
        self.assertIs(zone_ui.tracked_quest_objective_navigation, before)


if __name__ == "__main__":
    unittest.main()
