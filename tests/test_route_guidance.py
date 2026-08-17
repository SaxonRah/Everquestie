from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.route_guidance import (
    build_route_guidance,
    next_hop_for_zone,
    route_guidance_text,
)
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


class RouteGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.maps = self.root / "maps"
        self.maps.mkdir()
        self.db = Database(self.root / "working.sqlite3")
        self.a = self.db.upsert_entity(
            kind="zone",
            name="Zone A",
            external_id="1001",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "zonea"},
        )
        self.b = self.db.upsert_entity(
            kind="zone",
            name="Zone B",
            external_id="1002",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "zoneb"},
        )
        self.c = self.db.upsert_entity(
            kind="zone",
            name="Zone C",
            external_id="1003",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "zonec"},
        )
        self.off_route = self.db.upsert_entity(
            kind="zone",
            name="Zone X",
            external_id="1099",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.db.add_alias(self.b, "Middle Zone", alias_type="provider_alias")

        # Provider topology proves A↔B so the reverse route remains available without
        # borrowing the A-side map coordinate.
        catalog = ZoneTravelCatalog(self.db)
        catalog.add_provider_connection(
            self.a,
            self.b,
            connection_kind="zone_line",
            bidirectional=True,
            source_name="Topology Source",
            source_kind="provider",
            source_key="A-B-provider",
            evidence="two-way zone line topology",
        )
        catalog.add_provider_connection(
            self.b,
            self.c,
            connection_kind="portal",
            bidirectional=False,
            source_name="Portal Source",
            source_kind="provider",
            source_key="B-C-provider",
            evidence="one-way portal topology",
        )

        # Real map labels own the exact source-zone coordinates used by Map next hop.
        (self.maps / "zonea.txt").write_text(
            "P -10,-20,3,255,0,0,2,To_Zone_B\n",
            encoding="utf-8",
        )
        (self.maps / "zoneb.txt").write_text(
            "P -30,-40,5,255,0,0,2,To_Zone_C\n",
            encoding="utf-8",
        )
        maps = MapCatalog(self.db)
        maps.index_root(self.maps, source_name="Brewall", source_version="test")
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        maps.reconcile_all(force=True)
        ZoneTravelCatalog(self.db).reconcile_from_maps(source_name="Brewall")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_direct_hop_exposes_source_owned_game_coordinate(self):
        guidance = build_route_guidance(self.db, "Zone A", "Zone C")
        self.assertTrue(guidance.ok)
        self.assertEqual(len(guidance.hops), 2)
        first = guidance.hops[0]
        self.assertEqual((first.source_entity_id, first.target_entity_id), (self.a, self.b))
        self.assertEqual(first.coordinate_owner_entity_id, self.a)
        self.assertEqual(first.source_coordinate, (10.0, 20.0, 3.0))
        self.assertEqual(first.map_label, "travel to Zone B")
        self.assertEqual(first.evidence_source, "Brewall")

    def test_reverse_bidirectional_hop_never_reuses_opposite_side_coordinate(self):
        guidance = build_route_guidance(self.db, "Zone B", "Zone A")
        self.assertTrue(guidance.ok)
        hop = guidance.hops[0]
        self.assertTrue(hop.uses_reverse_evidence)
        self.assertEqual(hop.coordinate_owner_entity_id, self.a)
        self.assertEqual(hop.coordinate_owner_name, "Zone A")
        self.assertIsNone(hop.source_coordinate)

        text = route_guidance_text(self.db, guidance)
        self.assertIn("no reviewed source-zone coordinate is present", text)
        self.assertNotIn("source-zone /loc: 20.0, 10.0, 3.0", text)

    def test_guidance_text_marks_only_safe_source_coordinates_as_map_targets(self):
        guidance = build_route_guidance(self.db, "Zone A", "Zone C")
        text = route_guidance_text(self.db, guidance)
        self.assertIn("1. Zone A → Zone B", text)
        self.assertIn("source-zone /loc: 20.0, 10.0, 3.0", text)
        self.assertIn("2. Zone B → Zone C", text)
        self.assertIn("source-zone /loc: 40.0, 30.0, 5.0", text)

    def test_next_hop_tracks_live_canonical_zone_along_route(self):
        guidance = build_route_guidance(self.db, "Zone A", "Zone C")

        first, status = next_hop_for_zone(self.db, guidance, "1001")
        self.assertEqual(status, "linked")
        self.assertEqual((first.source_entity_id, first.target_entity_id), (self.a, self.b))

        second, status = next_hop_for_zone(self.db, guidance, "Middle Zone")
        self.assertEqual(status, "linked")
        self.assertEqual((second.source_entity_id, second.target_entity_id), (self.b, self.c))
        self.assertEqual(second.source_coordinate, (30.0, 40.0, 5.0))

        arrived, status = next_hop_for_zone(self.db, guidance, "Zone C")
        self.assertIsNone(arrived)
        self.assertEqual(status, "arrived")

    def test_off_route_or_unknown_live_zone_does_not_guess(self):
        guidance = build_route_guidance(self.db, "Zone A", "Zone C")
        hop, status = next_hop_for_zone(self.db, guidance, "Zone X")
        self.assertIsNone(hop)
        self.assertEqual(status, "off_route")

        hop, status = next_hop_for_zone(self.db, guidance, "Definitely Not A Zone")
        self.assertIsNone(hop)
        self.assertEqual(status, "zone_unknown")

    def test_unconfirmed_route_preserves_existing_failure_text(self):
        guidance = build_route_guidance(self.db, "Zone C", "Zone A")
        self.assertFalse(guidance.ok)
        self.assertEqual(guidance.hops, ())
        self.assertIn("No confirmed route", route_guidance_text(self.db, guidance))

    def test_finalized_runtime_exposes_same_next_hop_read_only(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="route-guidance-test",
        )
        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            guidance = build_route_guidance(runtime, "Zone A", "Zone C")
            hop, status = next_hop_for_zone(runtime, guidance, "Zone B")
            self.assertEqual(status, "linked")
            self.assertEqual(hop.source_coordinate, (30.0, 40.0, 5.0))
            self.assertEqual(hop.evidence_source, "Brewall")
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE zone_travel_edges SET x=999")
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
