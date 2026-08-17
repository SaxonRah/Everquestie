from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.route_guidance import build_route_guidance
from eqquest.route_guidance_ui import RouteGuidanceFrame
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_coverage import ZoneCoverageCatalog
from eqquest.zone_travel import ZoneTravelCatalog


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class RouteGuidanceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.a = self.db.upsert_entity(
            kind="zone",
            name="Zone A",
            external_id="2001",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "zonea"},
        )
        self.b = self.db.upsert_entity(
            kind="zone",
            name="Zone B",
            external_id="2002",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "zoneb"},
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _add(
        self,
        source_id: int,
        target_id: int,
        *,
        source_name: str,
        source_key: str,
        source_kind: str = "provider",
        bidirectional: bool = False,
        coordinate: tuple[float, float, float] | None = None,
    ) -> None:
        ZoneTravelCatalog(self.db).add_provider_connection(
            source_id,
            target_id,
            connection_kind="portal",
            bidirectional=bidirectional,
            source_name=source_name,
            source_kind=source_kind,
            source_key=source_key,
            evidence=f"evidence from {source_name}",
        )
        if coordinate is not None:
            x, y, z = coordinate
            self.db.conn.execute(
                "UPDATE zone_travel_edges SET x=?,y=?,z=? WHERE source_key=?",
                (x, y, z, source_key),
            )
            self.db.conn.commit()

    def _add_real_map_edge(
        self,
        *,
        source_name: str = "Z Located",
        coordinate: tuple[float, float, float] = (12.0, 34.0, 5.0),
    ) -> None:
        x, y, z = coordinate
        maps_root = self.root / "maps"
        maps_root.mkdir(exist_ok=True)
        (maps_root / "zonea.txt").write_text(
            f"P {-x:g},{-y:g},{z:g},255,0,0,2,To_Zone_B\n",
            encoding="utf-8",
        )
        maps = MapCatalog(self.db)
        maps.index_root(maps_root, source_name=source_name, source_version="test")
        ZoneMapCatalog(self.db).reconcile(source_name=source_name)
        maps.reconcile_all(force=True)
        ZoneTravelCatalog(self.db).reconcile_from_maps(source_name=source_name)

    def test_source_owned_map_coordinate_beats_coordinate_less_direct_row(self):
        self._add(
            self.a,
            self.b,
            source_name="A Missing",
            source_key="direct-missing",
        )
        self._add_real_map_edge()

        guidance = build_route_guidance(self.db, "Zone A", "Zone B")
        hop = guidance.hops[0]
        self.assertEqual(hop.evidence_source, "Z Located")
        self.assertEqual(hop.source_coordinate, (12.0, 34.0, 5.0))
        self.assertIsNotNone(hop.coordinate_source_record_id)
        self.assertFalse(hop.uses_reverse_evidence)

        coverage = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(coverage.route_directions_linked, 1)
        self.assertEqual(coverage.route_directions_mappable, 1)

    def test_provider_xy_never_becomes_actionable_coordinate(self):
        self._add(
            self.a,
            self.b,
            source_name="A Provider Located",
            source_key="provider-located",
            coordinate=(12.0, 34.0, 5.0),
        )

        guidance = build_route_guidance(self.db, "Zone A", "Zone B")
        hop = guidance.hops[0]
        self.assertEqual(hop.evidence_source, "A Provider Located")
        self.assertIsNone(hop.source_coordinate)
        self.assertIsNone(hop.coordinate_source_record_id)

        coverage = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(coverage.route_directions_linked, 1)
        self.assertEqual(coverage.route_directions_mappable, 0)
        self.assertEqual(coverage.travel_edges_with_source_coordinates, 0)
        self.assertEqual(coverage.travel_edges_without_source_coordinates, 1)

    def test_map_label_kind_without_label_record_is_not_coordinate_provenance(self):
        self._add(
            self.a,
            self.b,
            source_name="Spoofed Map Kind",
            source_key="spoofed-map-kind",
            source_kind="map_label",
            coordinate=(12.0, 34.0, 5.0),
        )

        row = self.db.conn.execute(
            "SELECT label_id FROM zone_travel_edges WHERE source_key='spoofed-map-kind'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row["label_id"])

        guidance = build_route_guidance(self.db, "Zone A", "Zone B")
        hop = guidance.hops[0]
        self.assertEqual(hop.evidence_source, "Spoofed Map Kind")
        self.assertIsNone(hop.source_coordinate)
        self.assertIsNone(hop.coordinate_source_record_id)

        coverage = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(coverage.route_directions_linked, 1)
        self.assertEqual(coverage.route_directions_mappable, 0)
        self.assertEqual(coverage.travel_edges_with_source_coordinates, 0)
        self.assertEqual(coverage.travel_edges_without_source_coordinates, 1)

    def test_map_next_hop_uses_actionable_direct_evidence(self):
        self._add(
            self.a,
            self.b,
            source_name="A Missing",
            source_key="direct-missing",
        )
        self._add_real_map_edge()
        guidance = build_route_guidance(self.db, "Zone A", "Zone B")
        emitted: list[tuple] = []
        fake = SimpleNamespace(
            db=self.db,
            _route_guidance=guidance,
            _live_current_zone=lambda: "Zone A",
            status_var=_Status(),
            on_map_target=lambda *args: emitted.append(args),
        )

        RouteGuidanceFrame.map_next_hop(fake)
        self.assertEqual(
            emitted,
            [("Zone A", 12.0, 34.0, 5.0, "travel to Zone B")],
        )
        self.assertIn("Z Located", fake.status_var.value)

    def test_map_next_hop_refuses_provider_coordinate(self):
        self._add(
            self.a,
            self.b,
            source_name="Provider Located",
            source_key="provider-located",
            coordinate=(12.0, 34.0, 5.0),
        )
        guidance = build_route_guidance(self.db, "Zone A", "Zone B")
        emitted: list[tuple] = []
        fake = SimpleNamespace(
            db=self.db,
            _route_guidance=guidance,
            _live_current_zone=lambda: "Zone A",
            status_var=_Status(),
            on_map_target=lambda *args: emitted.append(args),
        )

        RouteGuidanceFrame.map_next_hop(fake)
        self.assertEqual(emitted, [])
        self.assertIn("no confirmed source-zone coordinate", fake.status_var.value)

    def test_direct_without_coordinate_beats_reverse_provider_coordinate(self):
        self._add(
            self.a,
            self.b,
            source_name="Z Direct Missing",
            source_key="direct-missing",
        )
        self._add(
            self.b,
            self.a,
            source_name="A Reverse Located",
            source_key="reverse-located",
            bidirectional=True,
            coordinate=(50.0, 60.0, 7.0),
        )

        guidance = build_route_guidance(self.db, "Zone A", "Zone B")
        hop = guidance.hops[0]
        self.assertEqual(hop.evidence_source, "Z Direct Missing")
        self.assertFalse(hop.uses_reverse_evidence)
        self.assertEqual(hop.coordinate_owner_entity_id, self.a)
        self.assertIsNone(hop.source_coordinate)

        coverage = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(coverage.route_directions_linked, 2)
        self.assertEqual(coverage.route_directions_mappable, 0)
        rows = {row.name: row for row in ZoneCoverageCatalog(self.db).rows()}
        self.assertEqual(rows["Zone A"].route_outgoing_mappable, 0)
        self.assertEqual(rows["Zone B"].route_outgoing_mappable, 0)

    def test_finalized_runtime_preserves_actionable_evidence_choice_read_only(self):
        self._add(
            self.a,
            self.b,
            source_name="A Missing",
            source_key="direct-missing",
        )
        self._add_real_map_edge()
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="route-actionable-evidence-test",
        )
        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            guidance = build_route_guidance(runtime, "Zone A", "Zone B")
            hop = guidance.hops[0]
            self.assertEqual(hop.evidence_source, "Z Located")
            self.assertEqual(hop.source_coordinate, (12.0, 34.0, 5.0))
            self.assertIsNotNone(hop.coordinate_source_record_id)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE zone_travel_edges SET x=999")
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
