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

    def _compile_map_travel(
        self,
        filename: str,
        label: str,
        *,
        source_name: str = "Coverage Map Fixture",
        coordinate: tuple[float, float, float] = (-10.0, -20.0, 3.0),
    ) -> ZoneTravelCatalog:
        maps_root = self.root / "maps"
        maps_root.mkdir(exist_ok=True)
        x, y, z = coordinate
        (maps_root / filename).write_text(
            f"P {x:g},{y:g},{z:g},255,0,0,2,{label}\n",
            encoding="utf-8",
        )
        maps = MapCatalog(self.db)
        maps.index_root(maps_root, source_name=source_name, source_version="1")
        ZoneMapCatalog(self.db).reconcile(source_name=source_name)
        maps.reconcile_all(force=True)
        catalog = ZoneTravelCatalog(self.db)
        catalog.reconcile_from_maps(source_name=source_name)
        return catalog

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
        self.assertEqual(summary.route_zones, 2)
        self.assertEqual(summary.route_weak_components, 1)
        self.assertEqual(summary.largest_weak_route_component, 2)
        self.assertEqual(summary.route_strong_components, 2)
        self.assertEqual(summary.largest_strong_route_component, 1)
        self.assertEqual(summary.route_sink_zones, ("Goru'kar Mesa",))
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
        source_name = "Two Way Map Fixture"
        catalog = self._compile_map_travel(
            "stonehive.txt",
            "To_Goru'kar_Mesa",
            source_name=source_name,
            coordinate=(-10.0, -20.0, 3.0),
        )
        edge = self.db.conn.execute(
            """
            SELECT id,label_id FROM zone_travel_edges
            WHERE source_kind='map_label' AND source_zone_entity_id=? AND target_zone_entity_id=?
            """,
            (stone, mesa),
        ).fetchone()
        self.assertIsNotNone(edge)
        self.assertIsNotNone(edge["label_id"])
        # The coordinate still belongs only to Stone Hive even when another source
        # proves this transition is usable in both directions.
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET bidirectional=1 WHERE id=?",
            (int(edge["id"]),),
        )
        self.db.conn.commit()

        first = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(first.travel_edges_linked, 1)
        self.assertEqual(first.travel_edges_with_source_coordinates, 1)
        self.assertEqual(first.route_directions_linked, 2)
        self.assertEqual(first.route_directions_mappable, 1)
        self.assertEqual(first.route_directions_unmappable, 1)
        self.assertEqual(first.zones_with_mappable_route_exit, 1)
        self.assertEqual(first.zones_with_route_but_no_mappable_exit, ("Goru'kar Mesa",))
        self.assertEqual(first.route_zones, 2)
        self.assertEqual(first.route_weak_components, 1)
        self.assertEqual(first.route_strong_components, 1)
        self.assertEqual(first.largest_strong_route_component, 2)
        self.assertEqual(first.route_sink_zones, ())

        rows = {row.name: row for row in ZoneCoverageCatalog(self.db).rows()}
        self.assertEqual((rows["Stone Hive"].route_outgoing, rows["Stone Hive"].route_outgoing_mappable), (1, 1))
        self.assertEqual((rows["Goru'kar Mesa"].route_outgoing, rows["Goru'kar Mesa"].route_outgoing_mappable), (1, 0))

        # Independent reverse map evidence with a Mesa-owned coordinate closes the
        # actionability gap without creating a third canonical route direction.
        self._compile_map_travel(
            "gorukarmesa.txt",
            "To_Stone_Hive",
            source_name=source_name,
            coordinate=(-30.0, -40.0, 5.0),
        )

        second = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(second.travel_edges_linked, 2)
        self.assertEqual(second.travel_edges_with_source_coordinates, 2)
        self.assertEqual(second.route_directions_linked, 2)
        self.assertEqual(second.route_directions_mappable, 2)
        self.assertEqual(second.route_directions_unmappable, 0)
        self.assertEqual(second.zones_with_mappable_route_exit, 2)
        self.assertEqual(second.zones_with_route_but_no_mappable_exit, ())
        self.assertEqual(second.route_strong_components, 1)
        self.assertEqual(second.largest_strong_route_component, 2)

    def test_provider_xy_is_not_counted_as_source_owned_coordinate(self):
        stone, mesa, future = self._zones()
        catalog = ZoneTravelCatalog(self.db)
        catalog.add_provider_connection(
            stone,
            mesa,
            source_name="Provider Fixture",
            source_kind="provider",
            source_key="provider-with-xy",
            evidence="topology only",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=10,y=20,z=3 WHERE source_key='provider-with-xy'"
        )
        self.db.conn.commit()

        summary = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(summary.travel_edges_linked, 1)
        self.assertEqual(summary.travel_edges_with_source_coordinates, 0)
        self.assertEqual(summary.travel_edges_without_source_coordinates, 1)
        self.assertEqual(summary.route_directions_linked, 1)
        self.assertEqual(summary.route_directions_mappable, 0)
        self.assertEqual(summary.zones_with_route_but_no_mappable_exit, ("Stone Hive",))

    def test_map_label_kind_without_label_record_is_not_counted_as_mappable(self):
        stone, mesa, future = self._zones()
        catalog = ZoneTravelCatalog(self.db)
        catalog.add_provider_connection(
            stone,
            mesa,
            source_name="Spoofed Map Kind",
            source_kind="map_label",
            source_key="map-kind-without-record",
            evidence="topology row merely claims map-label kind",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=10,y=20,z=3 WHERE source_key='map-kind-without-record'"
        )
        self.db.conn.commit()

        edge = self.db.conn.execute(
            "SELECT label_id FROM zone_travel_edges WHERE source_key='map-kind-without-record'"
        ).fetchone()
        self.assertIsNotNone(edge)
        self.assertIsNone(edge["label_id"])

        summary = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(summary.travel_edges_linked, 1)
        self.assertEqual(summary.travel_edges_with_source_coordinates, 0)
        self.assertEqual(summary.travel_edges_without_source_coordinates, 1)
        self.assertEqual(summary.route_directions_linked, 1)
        self.assertEqual(summary.route_directions_mappable, 0)
        self.assertEqual(summary.zones_with_route_but_no_mappable_exit, ("Stone Hive",))

    def test_route_graph_components_separate_islands_and_directionality(self):
        stone, mesa, future = self._zones()
        fourth = self.db.upsert_entity(
            kind="zone",
            name="Fourth Provider Zone",
            external_id="future-2",
            external_namespace="futuremirror:zone",
            merge_by_name=True,
        )
        catalog = ZoneTravelCatalog(self.db)
        catalog.add_provider_connection(
            stone,
            mesa,
            source_name="Fixture",
            source_kind="provider",
            source_key="island-a",
            evidence="one-way island A",
        )
        catalog.add_provider_connection(
            future,
            fourth,
            bidirectional=True,
            source_name="Fixture",
            source_kind="provider",
            source_key="island-b",
            evidence="two-way island B",
        )

        summary = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(summary.route_zones, 4)
        self.assertEqual(summary.route_weak_components, 2)
        self.assertEqual(summary.largest_weak_route_component, 2)
        self.assertEqual(summary.route_strong_components, 3)
        self.assertEqual(summary.largest_strong_route_component, 2)
        self.assertEqual(summary.route_sink_zones, ("Goru'kar Mesa",))

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
        self.assertIn("Zone coverage v3", text)
        self.assertIn("Canonical zones: 3", text)
        self.assertIn("EQ-client identities: 2/3", text)
        self.assertIn("Future Provider Zone", text)
        self.assertIn("Zones without confirmed map binding", text)
        self.assertIn("Canonical route directions: linked=1, mappable=0", text)
        self.assertIn("Route graph: zones=2/3, weak components=1", text)
        self.assertIn("largest mutually reachable component=1", text)
        self.assertIn("confirmed outgoing route but no mappable reviewed source coordinate", text)
        self.assertIn("Directed route sinks", text)
        self.assertIn("Stone Hive", text)
        self.assertIn("Goru'kar Mesa", text)

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
        self.assertEqual(report.zone_coverage["coverage_version"], "3")
        self.assertEqual(report.zone_coverage["zones"], 3)
        self.assertEqual(report.zone_coverage["client_identity"], 2)
        self.assertEqual(report.zone_coverage["route_directions_linked"], 0)
        self.assertEqual(report.zone_coverage["route_directions_mappable"], 0)
        self.assertEqual(report.zone_coverage["route_zones"], 0)
        self.assertEqual(report.zone_coverage["route_weak_components"], 0)
        self.assertEqual(report.zone_coverage["route_strong_components"], 0)

        runtime = RuntimeDatabase(snapshot, state)
        try:
            summary = ZoneCoverageCatalog(runtime).summary()
            self.assertEqual(summary.zones, 3)
            self.assertEqual(summary.client_identity, 2)
            self.assertEqual(summary.route_directions_linked, 0)
            self.assertEqual(summary.route_zones, 0)
            self.assertTrue(runtime.get_meta("zone_catalog_coverage", ""))
            with self.assertRaisesRegex(RuntimeError, "builder-only"):
                ZoneCoverageCatalog(runtime).compile_summary()
        finally:
            runtime.close()

        self.db = Database(self.root / "throwaway.sqlite3")


if __name__ == "__main__":
    unittest.main()
