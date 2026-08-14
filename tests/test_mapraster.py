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
        self.assertEqual(themed_map_rgb(MAP_THEME_STONE, 255, 0, 0), (235, 2, 6))
        self.assertEqual(themed_map_rgb(MAP_THEME_PARCHMENT, 255, 0, 0), (255, 2, 0))

    def test_themed_colors_preserve_source_separation(self) -> None:
        primaries = ((255, 0, 0), (0, 255, 0), (0, 0, 255))
        for theme in (MAP_THEME_STONE, MAP_THEME_PARCHMENT):
            themed = [themed_map_rgb(theme, *rgb) for rgb in primaries]
            distances = []
            for index, left in enumerate(themed):
                for right in themed[index + 1:]:
                    distances.append(sum(abs(a - b) for a, b in zip(left, right)))
            self.assertGreater(min(distances), 400)

    def test_theme_temperature_bias_is_directional(self) -> None:
        stone_gray = themed_map_rgb(MAP_THEME_STONE, 120, 120, 120)
        parchment_gray = themed_map_rgb(MAP_THEME_PARCHMENT, 120, 120, 120)
        self.assertGreater(stone_gray[2], stone_gray[0])
        self.assertGreater(parchment_gray[0], parchment_gray[2])

    def test_exact_zoom_rasters_exist_at_requested_sizes(self) -> None:
        layer = MapLayer(0, Path('diagonal.txt'))
        layer.lines.append(MapLine(0, 0, 0, 31, 31, 0, 255, 0, 0))
        zone = ZoneMap('diagonal', Path('.'), {0: layer})
        req = RasterRequest(
            generation=9,
            zone_map=zone,
            canvas_width=128,
            canvas_height=128,
            buffer_px=0,
            scale=4.0,
            offset_x=0.0,
            offset_y=0.0,
            enabled_layers=(0,),
            theme_id=MAP_THEME_STONE,
            line_width=4,
            exact_levels=((0.5, 0.125), (0.75, 0.1875), (1.0, 0.25), (4.0, 1.0)),
        )
        result = render_map_raster(req)
        levels = [level for level, _ppm in result.exact_rasters]
        self.assertEqual(levels, [0.5, 0.75, 1.0, 4.0])
        sizes = []
        for _level, ppm in result.exact_rasters:
            _magic, dims, _maximum, _pixels = ppm.split(b'\n', 3)
            sizes.append(tuple(map(int, dims.split())))
        self.assertEqual(sizes, [(16, 16), (24, 24), (32, 32), (128, 128)])


if __name__ == '__main__':
    unittest.main()
