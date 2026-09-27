from __future__ import annotations

import unittest

from eqquest.mapview import MapViewerFrame


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _MapPollHarness:
    def __init__(self):
        self.zone = "South Qeynos"
        self.location = None
        self._last_zone = "North Qeynos"
        self._last_location = None
        self._last_filter_z = None
        self._trail = [(1.0, 2.0, 3.0)]
        self._next_overlay_refresh = float("inf")
        self.manual_zone = _Var()
        self.map_root = _Var(r"C:\maps")
        self.zone_map = object()
        self.follow_player = _Var(False)
        self.filter_elevation = _Var(False)
        self.loaded = 0
        self.overlay_forced = 0
        self.marker_refreshes = 0
        self.after_calls = []

    def get_zone(self):
        return self.zone

    def get_location(self):
        return self.location

    def _refresh_overlay_cache(self, force=False):
        if force:
            self.overlay_forced += 1
        return False

    def _refresh_marker_list(self):
        self.marker_refreshes += 1

    def load_current_zone(self):
        self.loaded += 1

    def _redraw_overlays(self):
        pass

    def _append_trail_location(self, _loc):
        pass

    def _redraw_position(self):
        pass

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))

    def _poll_state(self):
        return MapViewerFrame._poll_state(self)


class MapLiveZoneRefreshTests(unittest.TestCase):
    def test_zone_change_loads_new_map_and_rearms_poll(self):
        harness = _MapPollHarness()

        MapViewerFrame._poll_state(harness)

        self.assertEqual(harness._last_zone, "South Qeynos")
        self.assertEqual(harness.manual_zone.get(), "South Qeynos")
        self.assertEqual(harness.loaded, 1)
        self.assertEqual(harness.overlay_forced, 1)
        self.assertEqual(harness.marker_refreshes, 1)
        self.assertEqual(len(harness.after_calls), 1)
        self.assertEqual(harness.after_calls[0][0], 250)

    def test_second_zone_change_loads_again(self):
        harness = _MapPollHarness()
        MapViewerFrame._poll_state(harness)

        harness.zone = "West Freeport"
        MapViewerFrame._poll_state(harness)

        self.assertEqual(harness._last_zone, "West Freeport")
        self.assertEqual(harness.manual_zone.get(), "West Freeport")
        self.assertEqual(harness.loaded, 2)
        self.assertEqual(len(harness.after_calls), 2)


if __name__ == "__main__":
    unittest.main()
