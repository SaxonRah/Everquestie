from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from eqquest.local_map_readiness import LocalMapReadiness
from eqquest.nearby import NearbyPoint
from eqquest.route_guidance_ui import RouteGuidanceFrame


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = str(value)


class NearbyLocalMapReadinessTests(unittest.TestCase):
    @staticmethod
    def _point() -> NearbyPoint:
        return NearbyPoint(
            point_type="entity",
            name="A Stone Worker",
            kind="npc",
            x=3.0,
            y=4.0,
            z=120.0,
            horizontal_distance=5.0,
            vertical_delta=120.0,
            delta_x=3.0,
            delta_y=4.0,
            source_name="Fixture Provider",
            source_version="1",
            source_key="worker",
            evidence="provider coordinate",
            entity_id=42,
        )

    @staticmethod
    def _readiness(
        status: str,
        *,
        path: Path | None = None,
        reason: str = "fixture",
    ) -> LocalMapReadiness:
        return LocalMapReadiness(
            zone_token="Stone Hive",
            canonical_zone_entity_id=400,
            canonical_zone_name="Stone Hive",
            status=status,
            reason=reason,
            path=path,
            candidates=(),
            bound_stem="",
            hinted_stem="",
        )

    def _emit_fake(self, readiness_callback):
        emitted: list[tuple] = []
        status = _Var()
        fake = SimpleNamespace(
            get_map_readiness=readiness_callback,
            status_var=status,
            on_map_target=lambda *args: emitted.append(args),
        )
        return fake, emitted, status

    def test_nearby_emit_ready_preserves_game_space_and_names_local_file(self):
        local = Path("/maps/stonehive.txt")
        fake, emitted, status = self._emit_fake(
            lambda zone: self._readiness("ready", path=local, reason="user map binding")
        )

        ok = RouteGuidanceFrame._emit_map_point(fake, "Stone Hive", self._point())
        self.assertTrue(ok)
        self.assertEqual(
            emitted,
            [("Stone Hive", 3.0, 4.0, 120.0, "A Stone Worker [npc]")],
        )
        self.assertIn("5.0 horizontal", status.value)
        self.assertIn("ΔZ +120.0", status.value)
        self.assertIn("local map: stonehive.txt", status.value)

    def test_nearby_emit_known_missing_map_refuses_handoff(self):
        fake, emitted, status = self._emit_fake(
            lambda zone: self._readiness(
                "map_missing",
                reason="no unique local map-file match",
            )
        )

        ok = RouteGuidanceFrame._emit_map_point(fake, "Stone Hive", self._point())
        self.assertFalse(ok)
        self.assertEqual(emitted, [])
        self.assertIn("Map target coordinate is confirmed for Stone Hive", status.value)
        self.assertIn("Local map missing for Stone Hive", status.value)

    def test_missing_or_failing_readiness_callback_preserves_old_safe_handoff(self):
        point = self._point()
        no_callback = SimpleNamespace(
            status_var=_Var(),
            on_map_target=lambda *args: setattr(no_callback, "emitted", args),
        )
        no_callback.emitted = None
        self.assertTrue(RouteGuidanceFrame._emit_map_point(no_callback, "Stone Hive", point))
        self.assertEqual(
            no_callback.emitted,
            ("Stone Hive", 3.0, 4.0, 120.0, "A Stone Worker [npc]"),
        )

        def failing(_zone):
            raise OSError("temporary local filesystem failure")

        failed, emitted, status = self._emit_fake(failing)
        self.assertTrue(RouteGuidanceFrame._emit_map_point(failed, "Stone Hive", point))
        self.assertEqual(len(emitted), 1)
        self.assertNotIn("local map:", status.value)

    def test_inherited_map_nearest_flows_through_readiness_override(self):
        point = self._point()
        emitted: list[tuple] = []
        status = _Var()
        fake = SimpleNamespace(
            db=object(),
            _live_current_zone=lambda: "Stone Hive",
            get_location=lambda: (0.0, 0.0, 0.0),
            get_map_readiness=lambda zone: self._readiness(
                "map_missing",
                reason="no unique local map-file match",
            ),
            status_var=status,
            on_map_target=lambda *args: emitted.append(args),
        )
        fake._emit_map_point = lambda zone, selected: RouteGuidanceFrame._emit_map_point(
            fake, zone, selected
        )

        with patch("eqquest.travel.nearby_points", return_value=([point], "linked")):
            RouteGuidanceFrame.map_nearest(fake)

        self.assertEqual(emitted, [])
        self.assertIn("Local map missing for Stone Hive", status.value)

    def test_inherited_map_selected_flows_through_readiness_override(self):
        point = self._point()
        local = Path("/maps/stonehive.txt")
        emitted: list[tuple] = []
        status = _Var()
        fake = SimpleNamespace(
            _nearby_zone="Stone Hive",
            _nearby_point_by_item={"row-1": point},
            nearby_tree=SimpleNamespace(selection=lambda: ("row-1",)),
            _live_current_zone=lambda: "Stone Hive",
            get_map_readiness=lambda zone: self._readiness("ready", path=local),
            status_var=status,
            on_map_target=lambda *args: emitted.append(args),
        )
        fake._selected_nearby_point = lambda: point
        fake._emit_map_point = lambda zone, selected: RouteGuidanceFrame._emit_map_point(
            fake, zone, selected
        )

        RouteGuidanceFrame.map_selected_nearby(fake)
        self.assertEqual(
            emitted,
            [("Stone Hive", 3.0, 4.0, 120.0, "A Stone Worker [npc]")],
        )
        self.assertIn("local map: stonehive.txt", status.value)


if __name__ == "__main__":
    unittest.main()
