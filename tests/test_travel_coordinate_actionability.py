from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.current_zone_dashboard import build_current_zone_dashboard
from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.nearby import nearby_points
from eqquest.travel_coordinate_actionability import travel_coordinate_is_actionable
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


class TravelCoordinateActionabilityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.maps = self.root / "maps"
        self.maps.mkdir()
        self.db = Database(self.root / "knowledge.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    @staticmethod
    def _connection(**overrides):
        values = {
            "usable_from_zone": True,
            "coordinate_zone_entity_id": 10,
            "x": 1.0,
            "y": 2.0,
            "z": 3.0,
            "source_kind": "map_label",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def _zone(self, name: str, zone_id: int, *, stem: str | None = None) -> int:
        data = {"map_short_name": stem} if stem else None
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=str(zone_id),
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data=data,
        )

    def test_map_label_coordinate_is_actionable_from_its_source_zone(self):
        connection = self._connection(source_kind="map_label")
        self.assertTrue(travel_coordinate_is_actionable(connection, 10))

    def test_provider_coordinate_is_not_actionable_even_when_edge_is_usable(self):
        connection = self._connection(source_kind="provider")
        self.assertFalse(travel_coordinate_is_actionable(connection, 10))

    def test_coordinate_must_belong_to_requested_zone_and_have_xy(self):
        self.assertFalse(
            travel_coordinate_is_actionable(
                self._connection(coordinate_zone_entity_id=11),
                10,
            )
        )
        self.assertFalse(
            travel_coordinate_is_actionable(
                self._connection(x=None),
                10,
            )
        )
        self.assertFalse(
            travel_coordinate_is_actionable(
                self._connection(usable_from_zone=False),
                10,
            )
        )

    def test_real_map_label_travel_point_remains_nearby_and_mappable(self):
        source = self._zone("Stone Hive", 400, stem="stonehive")
        target = self._zone("Blightfire Moors", 401, stem="blightfire")
        (self.maps / "stonehive.txt").write_text(
            "P 30,40,5,255,0,0,2,To_Blightfire_Moors\n",
            encoding="utf-8",
        )

        maps = MapCatalog(self.db)
        maps.index_root(self.maps, source_name="Brewall", source_version="2026-08")
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        maps.reconcile_all(force=True)
        stats = ZoneTravelCatalog(self.db).reconcile_from_maps(source_name="Brewall")
        self.assertEqual(stats.linked, 1)

        points, status = nearby_points(
            self.db,
            "Stone Hive",
            (0.0, 0.0, 0.0),
            include_entities=False,
        )
        self.assertEqual(status, "linked")
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].point_type, "travel")
        self.assertEqual(points[0].neighbor_zone_entity_id, target)
        self.assertEqual((points[0].x, points[0].y, points[0].z), (-30.0, -40.0, 5.0))

        dashboard, dashboard_status = build_current_zone_dashboard(self.db, "Stone Hive")
        self.assertEqual(dashboard_status, "linked")
        self.assertIsNotNone(dashboard)
        assert dashboard is not None
        exit_row = next(row for row in dashboard.exits if row.zone_entity_id == target)
        self.assertTrue(exit_row.usable)
        self.assertTrue(exit_row.source_owned_coordinate)
        self.assertEqual(dashboard.mappable_exit_count, 1)
        self.assertEqual(ZoneTravelCatalog(self.db).shortest_path(source, target), [source, target])

    def test_source_backed_provider_edge_stays_routeable_but_coordinate_is_not_actionable(self):
        source = self._zone("Stone Hive", 400)
        target = self._zone("Blightfire Moors", 401)
        page = self.db.upsert_source_page(
            url="test://provider-topology",
            title="Provider topology",
            entity_type="zone",
            sha256="provider-topology",
            plain_text="Stone Hive connects to Blightfire Moors",
            raw_html="",
            source_name="Fixture Provider",
            source_kind="fixture",
            source_key="zone:400",
            source_version="1",
        )
        catalog = ZoneTravelCatalog(self.db)
        catalog.add_provider_connection(
            source,
            target,
            connection_kind="zone_line",
            source_name="Fixture Provider",
            source_kind="provider",
            source_key="stone-to-blight",
            source_version="1",
            source_page_id=page,
            evidence="confirmed connected-zone relationship",
        )
        # Simulate a legacy/manual row that happens to contain coordinates. The source
        # page proves topology, not this exact /loc, so the point must remain non-actionable.
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=-10,y=20,z=3 WHERE source_key='stone-to-blight'"
        )
        self.db.conn.commit()

        self.assertEqual(catalog.shortest_path(source, target), [source, target])

        points, status = nearby_points(
            self.db,
            "Stone Hive",
            (0.0, 0.0, 0.0),
            include_entities=False,
        )
        self.assertEqual(status, "linked")
        self.assertEqual(points, [])

        dashboard, dashboard_status = build_current_zone_dashboard(self.db, "Stone Hive")
        self.assertEqual(dashboard_status, "linked")
        self.assertIsNotNone(dashboard)
        assert dashboard is not None
        exit_row = next(row for row in dashboard.exits if row.zone_entity_id == target)
        self.assertTrue(exit_row.usable)
        self.assertFalse(exit_row.source_owned_coordinate)
        self.assertEqual(dashboard.usable_exit_count, 1)
        self.assertEqual(dashboard.mappable_exit_count, 0)


if __name__ == "__main__":
    unittest.main()
