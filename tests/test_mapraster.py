from pathlib import Path
import unittest

from eqquest.eqmap import MapLayer, MapLine, ZoneMap
from eqquest.mapraster import (
    MAP_THEME_PARCHMENT,
    MAP_THEME_STONE,
    RasterRequest,
    map_background_rgb,
    render_map_raster,
    themed_map_rgb,
)


class MapRasterTests(unittest.TestCase):
    def _zone(self, count: int = 3000) -> ZoneMap:
        layer = MapLayer(0, Path('synthetic.txt'))
        for index in range(count):
            y = float(index % 300)
            layer.lines.append(
                MapLine(-50.0, y, 0.0, 150.0, y, 0.0, 255, 255, 255)
            )
        return ZoneMap('synthetic', Path('.'), {0: layer})

    def test_raster_keeps_all_visible_lines_without_budget(self) -> None:
        zone = self._zone(3000)
        req = RasterRequest(
            generation=7,
            zone_map=zone,
            canvas_width=100,
            canvas_height=300,
            buffer_px=0,
            scale=1.0,
            offset_x=0.0,
            offset_y=0.0,
            enabled_layers=(0,),
            theme_id=MAP_THEME_STONE,
        )
        result = render_map_raster(req)
        self.assertEqual(result.generation, 7)
        self.assertEqual(result.source_lines, 3000)
        self.assertEqual(result.viewport_lines, 3000)
        self.assertEqual(result.buffered_lines, 3000)
        self.assertTrue(result.ppm.startswith(b'P6\n100 300\n255\n'))

    def test_theme_palette_is_stable(self) -> None:
        self.assertEqual(map_background_rgb(MAP_THEME_STONE), (43, 53, 66))
        self.assertEqual(map_background_rgb(MAP_THEME_PARCHMENT), (217, 207, 173))
        self.assertEqual(themed_map_rgb(MAP_THEME_STONE, 255, 0, 0), (179, 131, 101))
        self.assertEqual(themed_map_rgb(MAP_THEME_PARCHMENT, 255, 0, 0), (125, 65, 50))


if __name__ == '__main__':
    unittest.main()
