from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.local_map_readiness import LocalMapReadiness
from eqquest.route_guidance import build_route_guidance
from eqquest.route_guidance_ui import RouteGuidanceFrame
from eqquest.runtime_policy import install_runtime_policy
from eqquest.zone_travel import ZoneTravelCatalog


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = str(value)


class LocalMapReadinessUITests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.a = self.db.upsert_entity(
            kind="zone",
            name="Zone A",
            external_id="4101",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.b = self.db.upsert_entity(
            kind="zone",
            name="Zone B",
            external_id="4102",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        ZoneTravelCatalog(self.db).add_provider_connection(
            self.a,
            self.b,
            connection_kind="portal",
            bidirectional=False,
            source_name="Topology Source",
            source_kind="provider",
            source_key="a-b",
            evidence="source-owned portal coordinate",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=12,y=34,z=5 WHERE source_key='a-b'"
        )
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    @staticmethod
    def _readiness(
        status: str,
        *,
        path: Path | None = None,
        reason: str = "fixture",
    ) -> LocalMapReadiness:
        return LocalMapReadiness(
            zone_token="Zone A",
            canonical_zone_entity_id=4101,
            canonical_zone_name="Zone A",
            status=status,
            reason=reason,
            path=path,
            candidates=(),
            bound_stem="",
            hinted_stem="",
        )

    def _route_fake(self, readiness_callback):
        guidance = build_route_guidance(self.db, "Zone A", "Zone B")
        emitted: list[tuple] = []
        status = _Var()
        fake = SimpleNamespace(
            db=self.db,
            _route_guidance=guidance,
            _live_current_zone=lambda: "Zone A",
            get_map_readiness=readiness_callback,
            status_var=status,
            on_map_target=lambda *args: emitted.append(args),
        )
        return fake, emitted, status

    def test_zone_overview_appends_local_map_readiness_without_replacing_knowledge(self):
        rendered: list[str] = []
        status = _Var()
        local_path = self.root / "maps" / "zonea.txt"
        readiness = self._readiness(
            "ready",
            path=local_path,
            reason="shipped canonical zone/map binding",
        )
        fake = SimpleNamespace(
            db=self.db,
            get_map_readiness=lambda zone: readiness,
            status_var=status,
            _clear_nearby_points=lambda: None,
            _selected_or_current_zone=lambda: "Zone A",
            _set_result=lambda text: rendered.append(text),
        )

        RouteGuidanceFrame.show_zone_context(fake)
        self.assertEqual(len(rendered), 1)
        self.assertIn("Route map actionability:", rendered[0])
        self.assertIn("Local map readiness:", rendered[0])
        self.assertIn("Local map ready for Zone A: zonea.txt", rendered[0])
        self.assertIn("local map ready", status.value)

    def test_map_next_hop_refuses_known_missing_local_map_before_handoff(self):
        fake, emitted, status = self._route_fake(
            lambda zone: self._readiness(
                "map_missing",
                reason="no unique local map-file match",
            )
        )

        RouteGuidanceFrame.map_next_hop(fake)
        self.assertEqual(emitted, [])
        self.assertIn("Next hop coordinate is confirmed for Zone A", status.value)
        self.assertIn("Local map missing for Zone A", status.value)

    def test_map_next_hop_ready_preserves_game_space_handoff_and_names_local_file(self):
        local_path = self.root / "maps" / "zonea.txt"
        fake, emitted, status = self._route_fake(
            lambda zone: self._readiness(
                "ready",
                path=local_path,
                reason="user map binding",
            )
        )

        RouteGuidanceFrame.map_next_hop(fake)
        self.assertEqual(
            emitted,
            [("Zone A", 12.0, 34.0, 5.0, "portal to Zone B")],
        )
        self.assertIn("local map: zonea.txt", status.value)
        self.assertIn("Topology Source", status.value)

    def test_readiness_callback_failure_is_supplemental_and_does_not_break_navigation(self):
        def unavailable(_zone):
            raise OSError("temporary filesystem failure")

        fake, emitted, status = self._route_fake(unavailable)
        RouteGuidanceFrame.map_next_hop(fake)
        self.assertEqual(
            emitted,
            [("Zone A", 12.0, 34.0, 5.0, "portal to Zone B")],
        )
        self.assertIn("Map next hop", status.value)

    def test_runtime_map_owner_reads_its_root_and_explicit_user_binding_headlessly(self):
        install_runtime_policy()
        from eqquest import mapview as mapview_module

        zone = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "planeofknowledge"},
        )
        self.assertGreater(zone, 0)
        local = self.root / "combined-pack"
        local.mkdir()
        expected = local / "poknowledge.txt"
        expected.write_text("P 1,2,3,255,0,0,2,Test\n", encoding="utf-8")
        (local / "planeofknowledge.txt").write_text(
            "P 1,2,3,255,0,0,2,Test\n",
            encoding="utf-8",
        )
        self.db.set_meta(
            mapview_module._binding_key("The Plane of Knowledge"),
            "poknowledge",
        )
        fake_viewer = SimpleNamespace(
            db=self.db,
            map_root=_Var(str(local)),
        )

        readiness = mapview_module.MapViewerFrame.local_map_readiness(
            fake_viewer,
            "The Plane of Knowledge",
        )
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.path, expected)
        self.assertEqual(readiness.reason, "user map binding")

    def test_packaged_load_current_zone_uses_same_readiness_projection_headlessly(self):
        install_runtime_policy()
        from eqquest import mapview as mapview_module

        self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            external_id="400",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        local = self.root / "stone-pack"
        local.mkdir()
        expected = local / "stonehive.txt"
        expected.write_text("P 1,2,3,255,0,0,2,Test\n", encoding="utf-8")
        loaded: list[Path] = []
        status = _Var()
        fake_viewer = SimpleNamespace(
            db=self.db,
            get_zone=lambda: "Stone Hive",
            map_root=_Var(str(local)),
            map_status=status,
            _base_map_status="Loaded stonehive",
            _packaged_runtime=lambda: True,
            load_map=lambda path: loaded.append(Path(path)),
            _refresh_overlay_cache=lambda **_kwargs: None,
            _refresh_marker_list=lambda: None,
        )
        fake_viewer.local_map_readiness = lambda zone: (
            mapview_module.MapViewerFrame.local_map_readiness(fake_viewer, zone)
        )

        mapview_module.MapViewerFrame.load_current_zone(fake_viewer)
        self.assertEqual(loaded, [expected])
        self.assertIn("legacy unique filename fallback", status.value)


if __name__ == "__main__":
    unittest.main()
