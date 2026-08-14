from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.route_guidance import build_route_guidance
from eqquest.route_guidance_ui import RouteGuidanceFrame
from eqquest.zone_travel import ZoneTravelCatalog


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class RouteGuidanceUITests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
        self.a = self.db.upsert_entity(
            kind="zone",
            name="Zone A",
            external_id="1001",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.b = self.db.upsert_entity(
            kind="zone",
            name="Zone B",
            external_id="1002",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.c = self.db.upsert_entity(
            kind="zone",
            name="Zone C",
            external_id="1003",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.x = self.db.upsert_entity(
            kind="zone",
            name="Zone X",
            external_id="1099",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        catalog = ZoneTravelCatalog(self.db)
        catalog.add_provider_connection(
            self.a,
            self.b,
            connection_kind="zone_line",
            bidirectional=True,
            source_name="Topology Source",
            source_kind="provider",
            source_key="A-B",
            evidence="two-way zone line",
        )
        catalog.add_provider_connection(
            self.b,
            self.c,
            connection_kind="portal",
            bidirectional=False,
            source_name="Portal Source",
            source_kind="provider",
            source_key="B-C",
            evidence="one-way portal",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=10,y=20,z=3 WHERE source_key='A-B'"
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=30,y=40,z=5 WHERE source_key='B-C'"
        )
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _fake(self, guidance, live_zone: str):
        emitted: list[tuple] = []
        status = _Var()
        fake = SimpleNamespace(
            db=self.db,
            _route_guidance=guidance,
            _live_current_zone=lambda: live_zone,
            status_var=status,
            on_map_target=lambda *args: emitted.append(args),
        )
        return fake, emitted, status

    def test_map_next_hop_emits_source_owned_game_coordinate_without_player_loc(self):
        guidance = build_route_guidance(self.db, "Zone A", "Zone C")
        fake, emitted, status = self._fake(guidance, "Zone A")

        # There is intentionally no get_location callback on the fake. Route map
        # guidance owns no player-position dependency.
        RouteGuidanceFrame.map_next_hop(fake)
        self.assertEqual(
            emitted,
            [("Zone A", 10.0, 20.0, 3.0, "zone line to Zone B")],
        )
        self.assertIn("Map next hop", status.value)
        self.assertIn("Topology Source", status.value)

    def test_cached_route_advances_to_next_hop_after_zone_change(self):
        guidance = build_route_guidance(self.db, "Zone A", "Zone C")
        fake, emitted, status = self._fake(guidance, "Zone B")

        RouteGuidanceFrame.map_next_hop(fake)
        self.assertEqual(
            emitted,
            [("Zone B", 30.0, 40.0, 5.0, "portal to Zone C")],
        )
        self.assertIn("Portal Source", status.value)

    def test_reverse_two_way_route_refuses_opposite_side_coordinate(self):
        guidance = build_route_guidance(self.db, "Zone B", "Zone A")
        fake, emitted, status = self._fake(guidance, "Zone B")

        RouteGuidanceFrame.map_next_hop(fake)
        self.assertEqual(emitted, [])
        self.assertIn("stored coordinate belongs to Zone A", status.value)
        self.assertIn("will not map", status.value)

    def test_arrived_and_off_route_states_never_emit_map_target(self):
        guidance = build_route_guidance(self.db, "Zone A", "Zone C")

        arrived, emitted, status = self._fake(guidance, "Zone C")
        RouteGuidanceFrame.map_next_hop(arrived)
        self.assertEqual(emitted, [])
        self.assertIn("destination reached", status.value)

        off_route, emitted, status = self._fake(guidance, "Zone X")
        RouteGuidanceFrame.map_next_hop(off_route)
        self.assertEqual(emitted, [])
        self.assertIn("not on the cached route", status.value)

    def test_map_next_hop_requires_confirmed_cached_route(self):
        fake, emitted, status = self._fake(None, "Zone A")
        RouteGuidanceFrame.map_next_hop(fake)
        self.assertEqual(emitted, [])
        self.assertIn("Find a confirmed route", status.value)

    def test_find_route_uses_coordinate_owner_safe_renderer_and_caches_guidance(self):
        rendered: list[str] = []
        status = _Var()
        fake = SimpleNamespace(
            db=self.db,
            from_var=_Var("Zone B"),
            to_var=_Var("Zone A"),
            status_var=status,
            _route_guidance=None,
            _clear_nearby_points=lambda: None,
            use_current_zone=lambda: None,
            _set_result=lambda text: rendered.append(text),
        )

        RouteGuidanceFrame.find_route(fake)
        self.assertIsNotNone(fake._route_guidance)
        self.assertTrue(fake._route_guidance.ok)
        self.assertIn("stored /loc belongs to Zone A", rendered[0])
        self.assertIn("no source-zone coordinate is known", rendered[0])
        self.assertNotIn("source-zone /loc: 20.0, 10.0, 3.0", rendered[0])
        self.assertIn("Confirmed canonical route found", status.value)


if __name__ == "__main__":
    unittest.main()
