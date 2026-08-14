from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

from .eqmap import ZoneMap


Cell = tuple[int, int]
WorldBounds = tuple[float, float, float, float]


@dataclass(slots=True)
class LayerSpatialIndex:
    line_cells: dict[Cell, list[int]] = field(default_factory=dict)
    point_cells: dict[Cell, list[int]] = field(default_factory=dict)
    broad_lines: list[int] = field(default_factory=list)


class SpatialMapIndex:
    """Small in-memory grid index over immutable EQ map geometry.

    Tk Canvas slows down sharply when thousands of off-screen objects remain alive.
    This index lets the viewer keep only the current viewport plus a safety margin on
    the canvas. It stores integer references back into ZoneMap rather than copying map
    records.
    """

    def __init__(self, zone_map: ZoneMap, *, target_cells_across: int = 40) -> None:
        self.zone_map = zone_map
        self.bounds = zone_map.bounds()
        self.cell_size = self._choose_cell_size(target_cells_across)
        self.layers: dict[int, LayerSpatialIndex] = {}
        self._build()

    def _choose_cell_size(self, target_cells_across: int) -> float:
        if self.bounds is None:
            return 256.0
        minx, miny, maxx, maxy = self.bounds
        span = max(maxx - minx, maxy - miny, 1.0)
        target = max(8, int(target_cells_across))
        # Keep ordinary EQ zones near a few hundred world units per bucket while
        # still adapting to unusually tiny or huge maps.
        return max(32.0, min(4096.0, span / target))

    def _cell(self, x: float, y: float) -> Cell:
        size = self.cell_size
        return math.floor(x / size), math.floor(y / size)

    def _build(self) -> None:
        size = self.cell_size
        for layer_no, layer in self.zone_map.layers.items():
            index = LayerSpatialIndex()
            for line_no, line in enumerate(layer.lines):
                x0, x1 = sorted((line.x0, line.x1))
                y0, y1 = sorted((line.y0, line.y1))
                cx0, cy0 = math.floor(x0 / size), math.floor(y0 / size)
                cx1, cy1 = math.floor(x1 / size), math.floor(y1 / size)
                cell_count = (cx1 - cx0 + 1) * (cy1 - cy0 + 1)
                # A very long line would otherwise be duplicated into hundreds of
                # buckets. Keep those in a tiny always-considered side list.
                if cell_count > 96:
                    index.broad_lines.append(line_no)
                    continue
                for cx in range(cx0, cx1 + 1):
                    for cy in range(cy0, cy1 + 1):
                        index.line_cells.setdefault((cx, cy), []).append(line_no)

            for point_no, point in enumerate(layer.points):
                index.point_cells.setdefault(self._cell(point.x, point.y), []).append(point_no)
            self.layers[layer_no] = index

    def _cells_for_bounds(self, bounds: WorldBounds) -> Iterable[Cell]:
        minx, miny, maxx, maxy = bounds
        size = self.cell_size
        cx0, cy0 = math.floor(minx / size), math.floor(miny / size)
        cx1, cy1 = math.floor(maxx / size), math.floor(maxy / size)
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                yield cx, cy

    def query_layer(self, layer_no: int, bounds: WorldBounds) -> tuple[set[int], set[int]]:
        index = self.layers.get(layer_no)
        if index is None:
            return set(), set()
        lines = set(index.broad_lines)
        points: set[int] = set()
        for cell in self._cells_for_bounds(bounds):
            lines.update(index.line_cells.get(cell, ()))
            points.update(index.point_cells.get(cell, ()))
        return lines, points


def bbox_intersects(a: WorldBounds, b: WorldBounds) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])
