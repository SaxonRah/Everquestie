from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.locations import (
    location_evidence_for_entity,
    location_evidence_for_term,
    where_text,
)
from eqquest.map_catalog import MapCatalog
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog


class UnifiedLocationEvidenceTests(unittest.TestCase):
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

    def _build_linked_map(self) -> tuple[int, int]:
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="South Qeynos",
            external_id="1",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "qeynos"},
        )
        npc_id = self.db.upsert_entity(
            kind="npc",
            name="Guard Hezlan",
            zone="South Qeynos",
        )
        (self.maps / "qeynos.txt").write_text(
            "P 10,20,3,255,0,0,2,Guard_Hezlan\n",
            encoding="utf-8",
        )
        catalog = MapCatalog(self.db)
        catalog.index_root(self.maps, source_name="Brewall", source_version="2026-08")
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        stats = catalog.reconcile_all(force=True)
        self.assertEqual(stats["linked"], 1)
        return zone_id, npc_id

    def _add_provider_location(self, zone_id: int, npc_id: int) -> None:
        source_id = self.db.upsert_source_page(
            url="test://npc-location",
            title="Test NPC location",
            entity_type="npc",
            sha256="location-source",
            plain_text="Guard Hezlan location",
            raw_html="",
            source_name="Test Provider",
            source_kind="fixture",
            source_key="npc:guard-hezlan",
            source_version="1",
        )
        self.db.add_location(
            npc_id,
            zone_entity_id=zone_id,
            y=222.0,
            x=111.0,
            z=7.0,
            label="spawn point",
            source_page_id=source_id,
            evidence="provider coordinate",
        )

    def test_provider_and_map_locations_share_one_read_api(self):
        zone_id, npc_id = self._build_linked_map()
        self._add_provider_location(zone_id, npc_id)

        locations = location_evidence_for_entity(self.db, npc_id)
        self.assertEqual(len(locations), 2)
        provider = next(row for row in locations if row.evidence_type == "entity_location")
        mapped = next(row for row in locations if row.evidence_type == "map_label")

        self.assertEqual((provider.x, provider.y, provider.z), (111.0, 222.0, 7.0))
        self.assertEqual(provider.zone_entity_id, zone_id)
        self.assertEqual(provider.zone_name, "South Qeynos")
        self.assertEqual(provider.source_name, "Test Provider")

        # Native map coordinates reverse both horizontal signs in normalized game
        # coordinates. EQ displays those coordinates as /loc Y, X, Z.
        self.assertEqual((mapped.x, mapped.y, mapped.z), (-10.0, -20.0, 3.0))
        self.assertEqual(mapped.loc_text, "Y=-20 X=-10 Z=3")
        self.assertEqual(mapped.zone_entity_id, zone_id)
        self.assertEqual(mapped.zone_name, "South Qeynos")
        self.assertEqual(mapped.source_name, "Brewall")
        self.assertEqual(mapped.source_version, "2026-08")
        self.assertEqual(mapped.label, "Guard_Hezlan")

    def test_where_text_exposes_both_sources_with_provenance(self):
        zone_id, npc_id = self._build_linked_map()
        self._add_provider_location(zone_id, npc_id)

        rendered = where_text(self.db, npc_id, current_zone="South Qeynos")
        self.assertIn("WHERE | [npc] Guard Hezlan", rendered)
        self.assertIn("Y=222 X=111 Z=7", rendered)
        self.assertIn("Test Provider 1", rendered)
        self.assertIn("Y=-20 X=-10 Z=3", rendered)
        self.assertIn("Brewall 2026-08", rendered)
        self.assertIn("Current zone: South Qeynos", rendered)

    def test_ambiguous_map_rows_are_never_promoted_to_location_truth(self):
        _zone_id, npc_id = self._build_linked_map()
        self.db.conn.execute(
            "UPDATE map_labels SET link_status='ambiguous', linked_entity_id=?",
            (npc_id,),
        )
        self.db.conn.commit()

        locations = location_evidence_for_entity(self.db, npc_id)
        self.assertFalse(any(row.evidence_type == "map_label" for row in locations))
        self.assertNotIn("Brewall", where_text(self.db, npc_id))

    def test_term_resolution_refuses_ambiguous_identity(self):
        self.db.upsert_entity(kind="npc", name="a guard", external_id="1")
        self.db.upsert_entity(kind="npc", name="a guard", external_id="2")
        entity, status, locations = location_evidence_for_term(self.db, "a guard", kind="npc")
        self.assertIsNone(entity)
        self.assertEqual(status, "ambiguous")
        self.assertEqual(locations, [])

    def test_finalized_runtime_exposes_same_map_location_read_only(self):
        zone_id, npc_id = self._build_linked_map()
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.working,
            snapshot,
            snapshot_version="location-test",
        )

        # Close the builder before opening the packaged runtime to mirror release use.
        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            entity = runtime.entity_by_namespaced_external_id("eqclient:zone", "1")
            self.assertIsNotNone(entity)
            self.assertEqual(int(entity["id"]), zone_id)

            locations = location_evidence_for_entity(runtime, npc_id)
            mapped = [row for row in locations if row.evidence_type == "map_label"]
            self.assertEqual(len(mapped), 1)
            self.assertEqual(mapped[0].zone_name, "South Qeynos")
            self.assertEqual((mapped[0].x, mapped[0].y, mapped[0].z), (-10.0, -20.0, 3.0))
            self.assertIn("Brewall 2026-08", where_text(runtime, npc_id))
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE map_labels SET raw_text='mutated'")
        finally:
            runtime.close()
            # tearDown expects an open object, so replace it with a harmless DB handle.
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
