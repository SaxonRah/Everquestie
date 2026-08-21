from __future__ import annotations

import unittest

from eqquest.mapview import (
    MAP_RASTER_ZOOM_LEVELS,
    MAP_RASTER_ZOOM_MAX,
    MAP_ZOOM_LEVELS,
)


class MapZoomPolicyTests(unittest.TestCase):
    def test_deep_zoom_exceeds_bounded_full_map_raster_cache(self):
        self.assertEqual(
            max(MAP_RASTER_ZOOM_LEVELS),
            MAP_RASTER_ZOOM_MAX,
        )
        self.assertLess(
            MAP_RASTER_ZOOM_MAX,
            max(MAP_ZOOM_LEVELS),
        )
        self.assertGreaterEqual(
            max(MAP_ZOOM_LEVELS),
            24.0,
        )
        self.assertTrue(
            all(
                level <= MAP_RASTER_ZOOM_MAX
                for level in MAP_RASTER_ZOOM_LEVELS
            )
        )


if __name__ == "__main__":
    unittest.main()
