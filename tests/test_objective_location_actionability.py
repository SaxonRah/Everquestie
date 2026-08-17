from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.quest_objective_navigation import tracked_quest_objective_navigation


class ObjectiveLocationActionabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
        self.zone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.quest_page = self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/quest.html?quest=actionable-location",
            title="Actionable Location Quest",
            entity_type="quest",
            sha256="sha-actionable-location-quest",
            plain_text="structured quest source",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key="quest:actionable-location",
        )
        self.quest = self.db.upsert_entity(
            kind="quest",
            name="Actionable Location Quest",
            external_id="quest:actionable-location",
            source_page_id=self.quest_page,
        )
        self.npc = self.db.upsert_entity(
            kind="npc",
            name="A Location Worker",
            external_id="npc:location-worker",
        )
        self.db.add_quest_step(
            self.quest,
            1,
            "Kill 1 A Location Worker",
            zone="The Stone Hive",
            match={
                "event": "kill",
                "npc": "A Location Worker",
                "npc_entity_id": self.npc,
                "count": 1,
            },
            source_page_id=self.quest_page,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tempdir.cleanup()

    def test_reviewed_step_cannot_borrow_unsourced_exact_npc_coordinate(self):
        self.db.add_location(
            self.npc,
            zone_entity_id=self.zone,
            y=11.0,
            x=21.0,
            z=1.0,
            label="legacy/manual coordinate",
            evidence="no source page",
        )

        result = tracked_quest_objective_navigation(
            self.db,
            self.quest,
            "The Stone Hive",
            step_order=1,
        )

        self.assertEqual(result.status, "current_zone_no_coordinate")
        self.assertFalse(result.map_ready)
        self.assertEqual(result.map_choices, ())

    def test_reviewed_step_and_reviewed_exact_npc_coordinate_remain_map_ready(self):
        npc_page = self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/npc.html?id=location-worker",
            title="A Location Worker",
            entity_type="npc",
            sha256="sha-location-worker",
            plain_text="A Location Worker",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key="npc:location-worker",
        )
        self.db.add_location(
            self.npc,
            zone_entity_id=self.zone,
            y=31.0,
            x=41.0,
            z=5.0,
            label="reviewed coordinate",
            source_page_id=npc_page,
            evidence="reviewed coordinate",
        )

        result = tracked_quest_objective_navigation(
            self.db,
            self.quest,
            "The Stone Hive",
            step_order=1,
        )

        self.assertTrue(result.map_ready)
        self.assertEqual(len(result.map_choices), 1)
        self.assertEqual(result.map_choices[0].location_entity_id, self.npc)
        self.assertEqual((result.map_choices[0].y, result.map_choices[0].x), (31.0, 41.0))


if __name__ == "__main__":
    unittest.main()
