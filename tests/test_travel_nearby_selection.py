from __future__ import annotations

from dataclasses import replace
import unittest

from eqquest.nearby import NearbyPoint
from eqquest.travel import TravelFrame


class _StatusRecorder:
    def __init__(self):
        self.value = ""

    def set(self, value: str) -> None:
        self.value = str(value)


class _FrameRecorder:
    def __init__(self):
        self.visible = False

    def grid(self, *args, **kwargs):
        self.visible = True

    def grid_remove(self):
        self.visible = False


class _TreeRecorder:
    def __init__(self):
        self.rows: dict[str, tuple] = {}
        self.order: list[str] = []
        self._selection: tuple[str, ...] = ()
        self._focus = ""
        self.seen = ""

    def get_children(self):
        return tuple(self.order)

    def delete(self, iid):
        iid = str(iid)
        self.rows.pop(iid, None)
        if iid in self.order:
            self.order.remove(iid)
        self._selection = tuple(value for value in self._selection if value != iid)
        if self._focus == iid:
            self._focus = ""

    def insert(self, _parent, _index, *, iid, values):
        iid = str(iid)
        self.rows[iid] = tuple(values)
        self.order.append(iid)
        return iid

    def selection_set(self, iid):
        self._selection = (str(iid),)

    def selection(self):
        return self._selection

    def focus(self, iid=None):
        if iid is not None:
            self._focus = str(iid)
        return self._focus

    def see(self, iid):
        self.seen = str(iid)


class _FakeTravel:
    _clear_nearby_points = TravelFrame._clear_nearby_points
    _set_nearby_points = TravelFrame._set_nearby_points
    _selected_nearby_point = TravelFrame._selected_nearby_point
    _emit_map_point = TravelFrame._emit_map_point
    _live_current_zone = TravelFrame._live_current_zone
    _nearby_map_label = staticmethod(TravelFrame._nearby_map_label)
    _nearby_row_values = staticmethod(TravelFrame._nearby_row_values)
    map_selected_nearby = TravelFrame.map_selected_nearby

    def __init__(self, *, zone: str = "Stone Hive"):
        self.current_zone = zone
        self.get_zone = lambda: self.current_zone
        self.nearby_tree = _TreeRecorder()
        self.nearby_frame = _FrameRecorder()
        self._nearby_points_by_item: dict[str, NearbyPoint] = {}
        self._nearby_zone = ""
        self.status_var = _StatusRecorder()
        self.emitted: list[tuple] = []
        self.on_map_target = lambda *args: self.emitted.append(args)


class SelectableNearbyTests(unittest.TestCase):
    @staticmethod
    def _point(
        name: str,
        *,
        distance: float,
        x: float,
        y: float,
        z: float | None,
        source: str,
        point_type: str = "entity",
        kind: str = "npc",
    ) -> NearbyPoint:
        return NearbyPoint(
            point_type=point_type,
            name=name,
            kind=kind,
            x=x,
            y=y,
            z=z,
            horizontal_distance=distance,
            vertical_delta=(z - 10.0 if z is not None else None),
            delta_x=x,
            delta_y=y,
            source_name=source,
            source_version="1",
            source_key=f"fixture:{name}",
            evidence="fixture point",
            entity_id=1 if point_type == "entity" else None,
            neighbor_zone_entity_id=2 if point_type == "travel" else None,
        )

    def test_nearby_table_preserves_rank_order_source_and_game_loc(self):
        first = self._point(
            "A Stone Worker",
            distance=5.0,
            x=3.0,
            y=4.0,
            z=120.0,
            source="Fixture Provider",
        )
        second = self._point(
            "Blightfire Moors",
            distance=50.0,
            x=-30.0,
            y=-40.0,
            z=5.0,
            source="Brewall",
            point_type="travel",
            kind="zone_line",
        )
        fake = _FakeTravel()

        fake._set_nearby_points("Stone Hive", [first, second])

        self.assertTrue(fake.nearby_frame.visible)
        self.assertEqual(fake.nearby_tree.order, ["nearby:1", "nearby:2"])
        self.assertIs(fake._nearby_points_by_item["nearby:1"], first)
        self.assertIs(fake._nearby_points_by_item["nearby:2"], second)
        self.assertEqual(fake.nearby_tree.selection(), ("nearby:1",))
        self.assertEqual(fake.nearby_tree.focus(), "nearby:1")

        first_values = fake.nearby_tree.rows["nearby:1"]
        self.assertEqual(first_values[0], "5.0")
        self.assertEqual(first_values[1], "+110.0")
        self.assertEqual(first_values[2], "npc")
        self.assertEqual(first_values[3], "A Stone Worker")
        self.assertEqual(first_values[4], "Y=4 X=3 Z=120")
        self.assertEqual(first_values[5], "Fixture Provider 1")

        second_values = fake.nearby_tree.rows["nearby:2"]
        self.assertEqual(second_values[2], "travel: zone line")
        self.assertEqual(second_values[4], "Y=-40 X=-30 Z=5")

    def test_map_selected_emits_exact_cached_game_space_point(self):
        first = self._point(
            "A Stone Worker",
            distance=5.0,
            x=3.0,
            y=4.0,
            z=120.0,
            source="Fixture Provider",
        )
        second = self._point(
            "A Stone Worker",
            distance=22.4,
            x=-10.0,
            y=-20.0,
            z=3.0,
            source="Brewall",
        )
        fake = _FakeTravel()
        fake._set_nearby_points("Stone Hive", [first, second])
        fake.nearby_tree.selection_set("nearby:2")

        fake.map_selected_nearby()

        self.assertEqual(fake.emitted, [
            ("Stone Hive", -10.0, -20.0, 3.0, "A Stone Worker [npc]")
        ])
        self.assertIn("Map target: A Stone Worker [npc]", fake.status_var.value)
        # The cached point remains the Brewall game-space evidence; selection does not
        # rerank, deduplicate, or apply native map sign conversion.
        self.assertIs(fake._nearby_points_by_item["nearby:2"], second)

    def test_selection_expires_when_live_zone_changes(self):
        point = self._point(
            "A Stone Worker",
            distance=5.0,
            x=3.0,
            y=4.0,
            z=120.0,
            source="Fixture Provider",
        )
        fake = _FakeTravel()
        fake._set_nearby_points("Stone Hive", [point])
        fake.current_zone = "Blightfire Moors"

        fake.map_selected_nearby()

        self.assertEqual(fake.emitted, [])
        self.assertEqual(fake._nearby_points_by_item, {})
        self.assertEqual(fake._nearby_zone, "")
        self.assertFalse(fake.nearby_frame.visible)
        self.assertIn("expired because the current zone changed", fake.status_var.value)

    def test_missing_selection_does_not_default_to_an_unselected_row(self):
        point = self._point(
            "A Stone Worker",
            distance=5.0,
            x=3.0,
            y=4.0,
            z=120.0,
            source="Fixture Provider",
        )
        fake = _FakeTravel()
        fake._set_nearby_points("Stone Hive", [point])
        fake.nearby_tree._selection = ()
        fake.nearby_tree._focus = ""

        fake.map_selected_nearby()

        self.assertEqual(fake.emitted, [])
        self.assertIn("Select a nearby confirmed point first", fake.status_var.value)


if __name__ == "__main__":
    unittest.main()
