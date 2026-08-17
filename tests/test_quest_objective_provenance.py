from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.quest_objective_navigation import tracked_quest_objective_navigation


class QuestObjectiveProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
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

    def tearDown(self) -> None:
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
            source_version="objective-provenance-test",
        )

    def _quest(self, name: str) -> tuple[int, int]:
        page = self._page(f"quest/{name}", name, "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name=name,
            external_id=f"quest:{name}",
            source_page_id=page,
        )
        return quest, page

    def _npc(self, name: str, zone_id: int, *, y: float = 10.0, x: float = 20.0) -> int:
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
        return npc

    def test_unprovenanced_npc_step_cannot_borrow_safe_npc_location(self):
        quest, _quest_page = self._quest("Unsourced Kill")
        npc = self._npc("A Known Worker", self.stone)
        self.db.add_quest_step(
            quest,
            1,
            "Kill 1 A Known Worker",
            zone="The Stone Hive",
            match={
                "event": "kill",
                "npc": "A Known Worker",
                "npc_entity_id": npc,
                "count": 1,
            },
            source_page_id=None,
        )

        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )

        self.assertEqual(result.status, "step_unprovenanced")
        self.assertFalse(result.map_ready)
        self.assertFalse(result.route_ready)
        self.assertEqual(result.objective_text, "Kill 1 A Known Worker")
        self.assertIn("no reviewed source provenance", result.reason)

    def test_unprovenanced_zone_only_step_cannot_create_travel_route(self):
        quest, _quest_page = self._quest("Unsourced Destination")
        self.db.add_quest_step(
            quest,
            1,
            "Investigate Blightfire Moors",
            zone="Blightfire Moors",
            match={},
            source_page_id=None,
        )

        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )

        self.assertEqual(result.status, "step_unprovenanced")
        self.assertFalse(result.route_ready)
        self.assertEqual(result.route_choices, ())

    def test_sourced_step_does_not_use_unprovenanced_relationship_by_evidence(self):
        quest, quest_page = self._quest("Mixed Evidence Kill")
        npc = self._npc("Rumored Worker", self.stone)
        description = "Kill 1 Rumored Worker"
        self.db.add_quest_step(
            quest,
            1,
            description,
            zone="The Stone Hive",
            match={"event": "kill", "npc": "Rumored Worker", "count": 1},
            source_page_id=quest_page,
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "objective_kill",
            evidence=description,
            source_page_id=None,
        )

        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )

        self.assertEqual(result.status, "current_zone_no_coordinate")
        self.assertFalse(result.map_ready)
        self.assertEqual(result.map_choices, ())

    def test_sourced_compiled_npc_id_remains_actionable_without_duplicate_relationship(self):
        quest, quest_page = self._quest("Compiled Exact Kill")
        npc = self._npc("Compiled Worker", self.stone, y=31.0, x=41.0)
        self.db.add_quest_step(
            quest,
            1,
            "Kill 1 Compiled Worker",
            zone="The Stone Hive",
            match={
                "event": "kill",
                "npc": "Compiled Worker",
                "npc_entity_id": npc,
                "count": 1,
            },
            source_page_id=quest_page,
        )

        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )

        self.assertTrue(result.map_ready)
        self.assertEqual(len(result.map_choices), 1)
        self.assertEqual(result.map_choices[0].location_entity_id, npc)
        self.assertEqual((result.map_choices[0].y, result.map_choices[0].x), (31.0, 41.0))


if __name__ == "__main__":
    unittest.main()
