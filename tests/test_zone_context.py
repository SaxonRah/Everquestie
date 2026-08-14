from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_context import build_zone_context, zone_context_text
from eqquest.zone_travel import ZoneTravelCatalog


class ZoneContextTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.maps = self.root / "maps"
        self.maps.mkdir()
        self.working = self.root / "working.sqlite3"
        self.db = Database(self.working)

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _fixture(self) -> tuple[int, int, int, int]:
        stone_hive = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            external_id="400",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "stonehive", "expansion": "The Serpent's Spine"},
        )
        blightfire = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="401",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "blightfire"},
        )
        nexus = self.db.upsert_entity(
            kind="zone",
            name="The Nexus",
            external_id="152",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        npc = self.db.upsert_entity(
            kind="npc",
            name="A Stone Worker",
            zone="Stone Hive",
            merge_by_name=True,
        )

        (self.maps / "stonehive.txt").write_text(
            "\n".join(
                (
                    "P 10,20,3,255,0,0,2,A_Stone_Worker",
                    "P 30,40,5,255,0,0,2,To_Blightfire_Moors",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        map_catalog = MapCatalog(self.db)
        map_catalog.index_root(
            self.maps,
            source_name="Brewall",
            source_version="2026-08",
        )
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        linked = map_catalog.reconcile_all(force=True)
        self.assertGreaterEqual(linked["linked"], 1)
        travel = ZoneTravelCatalog(self.db)
        travel_stats = travel.reconcile_from_maps(source_name="Brewall")
        self.assertEqual(travel_stats.linked, 1)
        travel.add_provider_connection(
            nexus,
            stone_hive,
            connection_kind="portal",
            bidirectional=False,
            source_name="Topology Provider",
            source_kind="provider",
            source_key="nexus-to-stone-hive",
            evidence="directed portal into Stone Hive",
        )

        source_page = self.db.upsert_source_page(
            url="test://stone-worker-location",
            title="Stone worker location",
            entity_type="npc",
            sha256="stone-worker-location",
            plain_text="A Stone Worker spawn",
            raw_html="",
            source_name="Fixture Provider",
            source_kind="fixture",
            source_key="npc:a-stone-worker",
            source_version="1",
        )
        self.db.add_location(
            npc,
            zone_entity_id=stone_hive,
            x=111.0,
            y=222.0,
            z=7.0,
            label="spawn point",
            source_page_id=source_page,
            evidence="provider spawn coordinate",
        )
        return stone_hive, blightfire, nexus, npc

    def test_context_projects_identity_maps_travel_and_location_sources(self):
        stone_hive, blightfire, nexus, npc = self._fixture()

        context, status = build_zone_context(self.db, "400")
        self.assertEqual(status, "linked")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.identity.entity_id, stone_hive)
        self.assertEqual(context.identity.name, "Stone Hive")
        self.assertEqual(context.resolution_kind, "client_id")
        self.assertEqual(context.data["expansion"], "The Serpent's Spine")

        self.assertEqual(len(context.maps), 1)
        self.assertEqual(context.maps[0].source_name, "Brewall")
        self.assertEqual(context.maps[0].map_stem, "stonehive")

        by_neighbor = {row.neighbor_zone_entity_id: row for row in context.connections}
        self.assertEqual(set(by_neighbor), {blightfire, nexus})
        self.assertEqual(by_neighbor[blightfire].direction, "outgoing")
        self.assertTrue(by_neighbor[blightfire].usable_from_zone)
        self.assertEqual(by_neighbor[nexus].direction, "incoming")
        self.assertFalse(by_neighbor[nexus].usable_from_zone)

        npc_rows = [row for row in context.locations if row.entity_id == npc]
        self.assertEqual(len(npc_rows), 2)
        self.assertEqual(
            {row.location.evidence_type for row in npc_rows},
            {"entity_location", "map_label"},
        )
        provider = next(
            row.location for row in npc_rows if row.location.evidence_type == "entity_location"
        )
        mapped = next(
            row.location for row in npc_rows if row.location.evidence_type == "map_label"
        )
        self.assertEqual((provider.x, provider.y, provider.z), (111.0, 222.0, 7.0))
        self.assertEqual((mapped.x, mapped.y, mapped.z), (-10.0, -20.0, 3.0))
        self.assertEqual(mapped.source_name, "Brewall")
        self.assertEqual(context.entity_count, 1)

    def test_ambiguous_zone_token_returns_no_context(self):
        north = self.db.upsert_entity(kind="zone", name="North Freeport", merge_by_name=True)
        south = self.db.upsert_entity(kind="zone", name="South Freeport", merge_by_name=True)
        self.db.add_alias(north, "Freeport", alias_type="provider_alias")
        self.db.add_alias(south, "Freeport", alias_type="provider_alias")

        context, status = build_zone_context(self.db, "Freeport")
        self.assertIsNone(context)
        self.assertEqual(status, "ambiguous")
        self.assertIn("ambiguous canonical zone identity", zone_context_text(self.db, "Freeport"))

    def test_context_text_is_source_aware_and_navigation_oriented(self):
        self._fixture()
        text = zone_context_text(self.db, "stonehive")
        self.assertIn("ZONE | Stone Hive", text)
        self.assertIn("Map bindings:", text)
        self.assertIn("Brewall 2026-08: stonehive", text)
        self.assertIn("Travel connections:", text)
        self.assertIn("→ Blightfire Moors", text)
        self.assertIn("← The Nexus", text)
        self.assertIn("incoming only", text)
        self.assertIn("Confirmed located entities: 1", text)
        self.assertIn("[npc] A Stone Worker", text)
        self.assertIn("Fixture Provider 1", text)
        self.assertIn("Brewall 2026-08", text)

    def test_finalized_runtime_exposes_same_zone_context_read_only(self):
        stone_hive, blightfire, nexus, npc = self._fixture()
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.working,
            snapshot,
            snapshot_version="zone-context-test",
        )

        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            context, status = build_zone_context(runtime, "stonehive")
            self.assertEqual(status, "linked")
            self.assertIsNotNone(context)
            assert context is not None
            self.assertEqual(context.identity.entity_id, stone_hive)
            self.assertEqual(
                {row.neighbor_zone_entity_id for row in context.connections},
                {blightfire, nexus},
            )
            self.assertEqual({row.entity_id for row in context.locations}, {npc})
            self.assertEqual(
                {row.location.evidence_type for row in context.locations},
                {"entity_location", "map_label"},
            )
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entities SET name='mutated' WHERE id=?", (stone_hive,))
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
