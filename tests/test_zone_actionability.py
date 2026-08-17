from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.route_guidance_ui import RouteGuidanceFrame
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_actionability import build_zone_actionability, zone_actionability_text
from eqquest.zone_travel import ZoneTravelCatalog


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = str(value)


class ZoneActionabilityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.a = self.db.upsert_entity(
            kind="zone",
            name="Zone A",
            external_id="3001",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.b = self.db.upsert_entity(
            kind="zone",
            name="Zone B",
            external_id="3002",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.c = self.db.upsert_entity(
            kind="zone",
            name="Zone C",
            external_id="3003",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.x = self.db.upsert_entity(
            kind="zone",
            name="Zone X",
            external_id="3099",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        catalog = ZoneTravelCatalog(self.db)

        # Two direct statements describe A→B. Only the map-label row owns an exact
        # coordinate, so it must represent the mappable canonical route direction even
        # though its source sorts later than the generic topology row.
        catalog.add_provider_connection(
            self.a,
            self.b,
            connection_kind="portal",
            bidirectional=False,
            source_name="A Missing",
            source_kind="provider",
            source_key="a-b-missing",
            evidence="direct statement without coordinate",
        )
        catalog.add_provider_connection(
            self.a,
            self.b,
            connection_kind="portal",
            bidirectional=False,
            source_name="Z Located",
            source_kind="map_label",
            source_key="a-b-located",
            evidence="direct map label with source coordinate",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=12,y=34,z=5 WHERE source_key='a-b-located'"
        )

        # C→A is explicitly two-way provider topology. A can route back to C, but this
        # row's manually populated coordinate has no coordinate-owning provenance and
        # therefore cannot become a Map target in either direction.
        catalog.add_provider_connection(
            self.c,
            self.a,
            connection_kind="zone_line",
            bidirectional=True,
            source_name="Two Way Source",
            source_kind="provider",
            source_key="c-a-two-way",
            evidence="two-way topology with unreviewed C-side coordinate",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=50,y=60,z=7 WHERE source_key='c-a-two-way'"
        )

        # X→A is one-way incoming and therefore not an exit usable from A.
        catalog.add_provider_connection(
            self.x,
            self.a,
            connection_kind="portal",
            bidirectional=False,
            source_name="Incoming Source",
            source_kind="provider",
            source_key="x-a-incoming",
            evidence="one-way incoming topology",
        )
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_projection_deduplicates_route_directions_and_preserves_actionability(self):
        view, status = build_zone_actionability(self.db, "Zone A")
        self.assertEqual(status, "linked")
        self.assertIsNotNone(view)
        assert view is not None

        self.assertEqual(view.usable_route_directions, 2)
        self.assertEqual(view.mappable_route_directions, 1)
        by_neighbor = {
            direction.neighbor_zone_name: direction for direction in view.route_directions
        }
        self.assertEqual(set(by_neighbor), {"Zone B", "Zone C"})

        to_b = by_neighbor["Zone B"]
        self.assertTrue(to_b.mappable)
        self.assertEqual(to_b.source_name, "Z Located")
        self.assertEqual(to_b.source_kind, "map_label")
        self.assertEqual(to_b.evidence_count, 2)
        self.assertEqual((to_b.x, to_b.y, to_b.z), (12.0, 34.0, 5.0))
        self.assertEqual(to_b.loc_text, "Y=34 X=12 Z=5")

        to_c = by_neighbor["Zone C"]
        self.assertFalse(to_c.mappable)
        self.assertTrue(to_c.uses_reverse_evidence)
        self.assertEqual(to_c.coordinate_owner_entity_id, self.c)
        self.assertEqual((to_c.x, to_c.y, to_c.z), (None, None, None))

    def test_text_separates_mappable_reverse_and_incoming_only_evidence(self):
        text = zone_actionability_text(self.db, "Zone A")
        self.assertIn("Route map actionability:", text)
        self.assertIn("Mappable exits: 1/2 usable canonical route direction(s)", text)
        self.assertIn("→ Zone B | portal | map target available | Y=34 X=12 Z=5", text)
        self.assertIn("source: Z Located", text)
        self.assertIn("2 evidence rows", text)
        self.assertIn("→ Zone C | zone line | no source-side coordinate", text)
        self.assertIn("selected topology evidence is stored from the opposite zone", text)

        actionability = text.split("Route map actionability:", 1)[1]
        self.assertNotIn("Zone X", actionability)
        # The base canonical context still preserves the incoming-only evidence.
        self.assertIn("← Zone X", text)
        self.assertIn("incoming only", text)

    def test_provider_xy_does_not_create_a_mappable_direct_exit(self):
        # The C→A provider row has X/Y populated, but C itself must still see that
        # direct route as topology-only because the provider fact does not own /loc.
        view, status = build_zone_actionability(self.db, "Zone C")
        self.assertEqual(status, "linked")
        self.assertIsNotNone(view)
        assert view is not None
        to_a = next(row for row in view.route_directions if row.neighbor_zone_entity_id == self.a)
        self.assertFalse(to_a.uses_reverse_evidence)
        self.assertFalse(to_a.mappable)
        self.assertEqual((to_a.x, to_a.y, to_a.z), (None, None, None))

    def test_zone_with_no_usable_routes_reports_zero_actionability(self):
        view, status = build_zone_actionability(self.db, "Zone X")
        self.assertEqual(status, "linked")
        self.assertEqual(view.usable_route_directions, 1)
        # X→A is direct but coordinate-less, so it is usable but not mappable.
        self.assertEqual(view.mappable_route_directions, 0)
        self.assertFalse(view.route_directions[0].mappable)

        isolated = self.db.upsert_entity(
            kind="zone",
            name="Isolated Zone",
            external_id="3010",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        empty, status = build_zone_actionability(self.db, "Isolated Zone")
        self.assertEqual(status, "linked")
        self.assertEqual(empty.usable_route_directions, 0)
        self.assertEqual(empty.mappable_route_directions, 0)
        self.assertIn(
            "No confirmed route direction is usable from this zone.",
            zone_actionability_text(self.db, "Isolated Zone"),
        )

    def test_packaged_zone_overview_status_exposes_mappable_exit_count_headlessly(self):
        rendered: list[str] = []
        status = _Var()
        fake = SimpleNamespace(
            db=self.db,
            status_var=status,
            _clear_nearby_points=lambda: None,
            _selected_or_current_zone=lambda: "Zone A",
            _set_result=lambda text: rendered.append(text),
        )

        RouteGuidanceFrame.show_zone_context(fake)
        self.assertEqual(len(rendered), 1)
        self.assertIn("Mappable exits: 1/2", rendered[0])
        self.assertIn("2 usable route direction(s)", status.value)
        self.assertIn("1 mappable exit(s)", status.value)

    def test_finalized_runtime_exposes_same_zone_actionability_read_only(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="zone-actionability-test",
        )
        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            view, status = build_zone_actionability(runtime, "Zone A")
            self.assertEqual(status, "linked")
            self.assertEqual(view.usable_route_directions, 2)
            self.assertEqual(view.mappable_route_directions, 1)
            by_neighbor = {
                direction.neighbor_zone_name: direction
                for direction in view.route_directions
            }
            self.assertEqual(by_neighbor["Zone B"].source_name, "Z Located")
            self.assertTrue(by_neighbor["Zone B"].mappable)
            self.assertFalse(by_neighbor["Zone C"].mappable)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE zone_travel_edges SET x=999")
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
