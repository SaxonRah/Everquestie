from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_map_choices import knowledge_map_choices
from eqquest.location_actionability import location_is_actionable
from eqquest.locations import LocationEvidence, location_evidence_for_entity
from eqquest.nearby import nearby_points


class LocationActionabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
        self.zone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
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
            source_version="actionability-test",
        )

    def _npc(self, name: str, external_id: str) -> int:
        return self.db.upsert_entity(
            kind="npc",
            name=name,
            external_id=external_id,
        )

    def _sourced_location(
        self,
        npc: int,
        *,
        key: str,
        y: float = 10.0,
        x: float = 20.0,
    ) -> int:
        page = self._page(key, key, "npc")
        self.db.add_location(
            npc,
            zone_entity_id=self.zone,
            y=y,
            x=x,
            z=5.0,
            label="reviewed coordinate",
            source_page_id=page,
            evidence="reviewed coordinate",
        )
        return page

    def test_unsourced_direct_location_remains_visible_but_not_actionable(self):
        npc = self._npc("Visible Rumor", "npc:visible-rumor")
        self.db.add_location(
            npc,
            zone_entity_id=self.zone,
            y=11.0,
            x=21.0,
            z=1.0,
            label="legacy/manual coordinate",
            evidence="no source page",
        )

        evidence = location_evidence_for_entity(self.db, npc)
        self.assertEqual(len(evidence), 1)
        self.assertTrue(evidence[0].navigable)
        self.assertIsNone(evidence[0].source_page_id)
        self.assertFalse(location_is_actionable(evidence[0]))

        result = knowledge_map_choices(self.db, npc, "The Stone Hive")
        self.assertEqual(result.status, "no_navigable_location")
        self.assertEqual(result.choices, ())
        self.assertIn("reviewed provenance", result.reason)

    def test_source_backed_direct_location_is_actionable(self):
        npc = self._npc("Reviewed Scout", "npc:reviewed-scout")
        self._sourced_location(npc, key="npc/reviewed-scout", y=12.0, x=22.0)

        result = knowledge_map_choices(self.db, npc, "The Stone Hive")

        self.assertTrue(result.ready)
        self.assertEqual(len(result.choices), 1)
        self.assertEqual(result.choices[0].location_entity_id, npc)
        self.assertEqual((result.choices[0].y, result.choices[0].x), (12.0, 22.0))

    def test_linked_map_label_has_independent_actionable_provenance(self):
        row = LocationEvidence(
            entity_id=1,
            zone_entity_id=self.zone,
            zone_name="The Stone Hive",
            x=20.0,
            y=10.0,
            z=5.0,
            label="Map point",
            evidence_type="map_label",
            source_name="Brewall",
            source_version="2026-08",
            source_key="stonehive.txt",
            source_page_id=None,
            evidence="linked map label",
            map_label_id=99,
        )
        self.assertTrue(row.navigable)
        self.assertTrue(location_is_actionable(row))

        malformed = LocationEvidence(
            entity_id=1,
            zone_entity_id=self.zone,
            zone_name="The Stone Hive",
            x=20.0,
            y=10.0,
            z=5.0,
            label="Unlinked map-like point",
            evidence_type="map_label",
            source_name="Brewall",
            source_version="2026-08",
            source_key="stonehive.txt",
            source_page_id=None,
            evidence="missing linked map label id",
            map_label_id=None,
        )
        self.assertFalse(location_is_actionable(malformed))

    def test_unsourced_related_item_relationship_cannot_borrow_reviewed_npc_location(self):
        npc = self._npc("Reviewed Dropper", "npc:reviewed-dropper")
        self._sourced_location(npc, key="npc/reviewed-dropper")
        item = self.db.upsert_entity(
            kind="item", name="Rumored Sample", external_id="item:rumored-sample"
        )
        self.db.upsert_relationship(
            item,
            npc,
            "drops_from",
            evidence="synthetic relation without source provenance",
        )

        result = knowledge_map_choices(self.db, item, "The Stone Hive")

        self.assertFalse(result.ready)
        self.assertEqual(result.choices, ())

    def test_reviewed_quest_relationship_cannot_borrow_unsourced_npc_location(self):
        quest_page = self._page("quest/reviewed-contact", "Reviewed Contact", "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name="Reviewed Contact",
            external_id="quest:reviewed-contact",
            source_page_id=quest_page,
        )
        npc = self._npc("Unsourced Coordinate NPC", "npc:unsourced-coordinate")
        self.db.add_location(
            npc,
            zone_entity_id=self.zone,
            y=13.0,
            x=23.0,
            label="unreviewed coordinate",
            evidence="no source page",
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "started_by",
            source_page_id=quest_page,
            evidence="Quest Started By: Unsourced Coordinate NPC",
        )

        result = knowledge_map_choices(self.db, quest, "The Stone Hive")

        self.assertFalse(result.ready)
        self.assertEqual(result.choices, ())

    def test_unsourced_quest_relationship_cannot_borrow_reviewed_npc_location(self):
        quest = self.db.upsert_entity(
            kind="quest",
            name="Rumored Contact",
            external_id="quest:rumored-contact",
        )
        npc = self._npc("Reviewed Coordinate NPC", "npc:reviewed-coordinate")
        self._sourced_location(npc, key="npc/reviewed-coordinate")
        self.db.upsert_relationship(
            quest,
            npc,
            "started_by",
            evidence="synthetic starter without source provenance",
        )

        result = knowledge_map_choices(self.db, quest, "The Stone Hive")

        self.assertFalse(result.ready)
        self.assertEqual(result.choices, ())

    def test_nearby_skips_unsourced_entity_coordinate_but_keeps_reviewed_one(self):
        reviewed = self._npc("Reviewed Nearby", "npc:nearby-reviewed")
        rumored = self._npc("Rumored Nearby", "npc:nearby-rumored")
        self._sourced_location(reviewed, key="npc/nearby-reviewed", y=30.0, x=40.0)
        self.db.add_location(
            rumored,
            zone_entity_id=self.zone,
            y=3.0,
            x=4.0,
            z=0.0,
            label="closer but unreviewed",
            evidence="no source page",
        )

        points, status = nearby_points(
            self.db,
            "The Stone Hive",
            (0.0, 0.0, 0.0),
            include_travel=False,
        )

        self.assertEqual(status, "linked")
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].entity_id, reviewed)
        self.assertNotEqual(points[0].entity_id, rumored)


if __name__ == "__main__":
    unittest.main()
