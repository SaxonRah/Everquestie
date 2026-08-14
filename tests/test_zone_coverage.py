from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_coverage import ZoneCoverageCatalog, zone_coverage_audit_text
from eqquest.zone_travel import ZoneTravelCatalog


class ZoneCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zones(self) -> tuple[int, int, int]:
        client_source = self.db.upsert_source_page(
            url="eqclient://Resources/ZoneNames.txt",
            title="ZoneNames",
            entity_type="zone",
            sha256="zones",
            plain_text="fixture",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/ZoneNames.txt",
        )
        stone = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            source_page_id=client_source,
            source_url="eqclient://Resources/ZoneNames.txt",
            external_id="396",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            level_min=40,
            level_max=70,
        )
        mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            source_page_id=client_source,
            source_url="eqclient://Resources/ZoneNames.txt",
            external_id="397",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        future = self.db.upsert_entity(
            kind="zone",
            name="Future Provider Zone",
            external_id="future-1",
            external_namespace="futuremirror:zone",
            merge_by_name=True,
        )
        return stone, mesa, future

    def test_summary_projects_identity_map_and_travel_coverage(self):
        stone, mesa, future = self._zones()
        MapCatalog(self.db)
        ZoneMapCatalog(self.db).ensure_schema()
        self.db.conn.execute(
            """
            INSERT INTO zone_map_bindings(
                source_name,source_version,map_stem,zone_entity_id,zone_name,
                status,reason,catalog_version,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            ("Brewall", "1", "stonehive", stone, "Stone Hive", "linked", "fixture", "1", "now"),
        )
        self.db.conn.commit()
        ZoneTravelCatalog(self.db).add_provider_connection(
            stone,
            mesa,
            source_name="Fixture",
            source_kind="provider",
            source_key="stone-to-mesa",
            evidence="fixture edge",
        )

        summary = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(summary.zones, 3)
        self.assertEqual(summary.client_identity, 2)
        self.assertEqual(summary.level_data, 1)
        self.assertEqual(summary.mapped, 1)
        self.assertEqual(summary.travel_connected, 2)
        self.assertEqual(summary.isolated, 1)
        self.assertEqual(summary.route_directions_linked, 1)
        self.assertEqual(summary.route_directions_mappable, 0)
        self.assertEqual(summary.route_directions_unmappable, 1)
        self.assertEqual(summary.travel_edges_with_source_coordinates, 0)
        self.assertEqual(summary.travel_edges_without_source_coordinates, 1)
        self.assertEqual(summary.zones_with_mappable_route_exit, 0)
        self.assertEqual(summary.zones_with_route_but_no_mappable_exit, ("Stone Hive",))
        self.assertEqual(summary.zones_without_client_identity, ("Future Provider Zone",))
        self.assertIn("Goru'kar Mesa", summary.zones_without_maps)
        self.assertEqual(summary.zones_without_travel, ("Future Provider Zone",))

        rows = {row.name: row for row in ZoneCoverageCatalog(self.db).rows()}
        self.assertEqual(rows["Stone Hive"].travel_outgoing, 1)
        self.assertEqual(rows["Goru'kar Mesa"].travel_incoming, 1)
        self.assertEqual(rows["Stone Hive"].route_outgoing, 1)
        self.assertEqual(rows["Stone Hive"].route_outgoing_mappable, 0)
        self.assertEqual(rows["Goru'kar Mesa"].route_outgoing, 0)
        self.assertGreaterEqual(rows["Stone Hive"].source_count, 1)

    def test_bidirectional_route_counts_two_directions_but_only_source_side_coordinate(self):
        stone, mesa, future = self._zones()
        catalog = ZoneTravelCatalog(self.db)
        catalog.add_provider_connection(
            stone,
            mesa,
            connection_kind="zone_line",
            bidirectional=True,
            source_name="Two Way Fixture",
            source_kind="provider",
            source_key="stone-mesa-two-way",
            evidence="one stored row usable both ways",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=10,y=20,z=3 WHERE source_key='stone-mesa-two-way'"
        )
        self.db.conn.commit()

        first = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(first.travel_edges_linked, 1)
        self.assertEqual(first.route_directions_linked, 2)
        self.assertEqual(first.route_directions_mappable, 1)
        self.assertEqual(first.route_directions_unmappable, 1)
        self.assertEqual(first.zones_with_mappable_route_exit, 1)
        self.assertEqual(first.zones_with_route_but_no_mappable_exit, ("Goru'kar Mesa",))

        rows = {row.name: row for row in ZoneCoverageCatalog(self.db).rows()}
        self.assertEqual((rows["Stone Hive"].route_outgoing, rows["Stone Hive"].route_outgoing_mappable), (1, 1))
        self.assertEqual((rows["Goru'kar Mesa"].route_outgoing, rows["Goru'kar Mesa"].route_outgoing_mappable), (1, 0))

        # Independent reverse evidence with a Mesa-owned coordinate closes the
        # actionability gap without creating a third canonical route direction.
        catalog.add_provider_connection(
            mesa,
            stone,
            connection_kind="zone_line",
            bidirectional=False,
            source_name="Reverse Fixture",
            source_kind="provider",
            source_key="mesa-stone-direct",
            evidence="independent reverse-side coordinate",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=30,y=40,z=5 WHERE source_key='mesa-stone-direct'"
        )
        self.db.conn.commit()

        second = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(second.travel_edges_linked, 2)
        self.assertEqual(second.travel_edges_with_source_coordinates, 2)
        self.assertEqual(second.route_directions_linked, 2)
        self.assertEqual(second.route_directions_mappable, 2)
        self.assertEqual(second.route_directions_unmappable, 0)
        self.assertEqual(second.zones_with_mappable_route_exit, 2)
        self.assertEqual(second.zones_with_route_but_no_mappable_exit, ())

    def test_audit_names_gaps_instead_of_inventing_zone_facts(self):
        stone, mesa, future = self._zones()
        ZoneTravelCatalog(self.db).add_provider_connection(
            stone,
            mesa,
            source_name="Fixture",
            source_kind="provider",
            source_key="stone-to-mesa",
            evidence="fixture edge",
        )
        text = zone_coverage_audit_text(self.db)
        self.assertIn("Zone coverage v2", text)
        self.assertIn("Canonical zones: 3", text)
        self.assertIn("EQ-client identities: 2/3", text)
        self.assertIn("Future Provider Zone", text)
        self.assertIn("Zones without confirmed map binding", text)
        self.assertIn("Canonical route directions: linked=1, mappable=0", text)
        self.assertIn("confirmed outgoing route but no mappable source coordinate", text)
        self.assertIn("Stone Hive", text)

    def test_snapshot_persists_release_coverage_and_runtime_can_query_it(self):
        self._zones()
        self.db.close()
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"
        report = create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="zone-coverage-test",
        )
        self.assertEqual(report.zone_coverage["coverage_version"], "2")
        self.assertEqual(report.zone_coverage["zones"], 3)
        self.assertEqual(report.zone_coverage["client_identity"], 2)
        self.assertEqual(report.zone_coverage["route_directions_linked"], 0)
        self.assertEqual(report.zone_coverage["route_directions_mappable"], 0)

        runtime = RuntimeDatabase(snapshot, state)
        try:
            summary = ZoneCoverageCatalog(runtime).summary()
            self.assertEqual(summary.zones, 3)
            self.assertEqual(summary.client_identity, 2)
            self.assertEqual(summary.route_directions_linked, 0)
            self.assertTrue(runtime.get_meta("zone_catalog_coverage", ""))
            with self.assertRaisesRegex(RuntimeError, "builder-only"):
                ZoneCoverageCatalog(runtime).compile_summary()
        finally:
            runtime.close()

        self.db = Database(self.root / "throwaway.sqlite3")


if __name__ == "__main__":
    unittest.main()
