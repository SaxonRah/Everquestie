from __future__ import annotations

from dataclasses import dataclass
import colorsys

from .eqmap import ZoneMap


MAP_THEME_ORIGINAL = "original"
MAP_THEME_STONE = "stone"
MAP_THEME_PARCHMENT = "parchment"

RGB = tuple[int, int, int]


def _mix_rgb(a: RGB, b: RGB, amount: float) -> RGB:
    t = max(0.0, min(1.0, amount))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def map_background_rgb(theme_id: str) -> RGB:
    return {
        MAP_THEME_ORIGINAL: (247, 247, 247),
        MAP_THEME_STONE: (43, 53, 66),
        MAP_THEME_PARCHMENT: (217, 207, 173),
    }.get(theme_id, (43, 53, 66))


def _clamp8(value: float) -> int:
    return max(0, min(255, int(round(value))))


def themed_map_rgb(theme_id: str, r: int, g: int, b: int, *, label: bool = False) -> RGB:
    """Keep native EQ map colors distinct while giving them a light theme bias.

    Stone and parchment are background-driven themes. Saturated source colors
    retain their native hue relationships; only a gentle cool/warm temperature
    shift is applied. Near-neutral colors receive readability corrections.
    """
    if theme_id == MAP_THEME_ORIGINAL:
        if r > 245 and g > 245 and b > 245:
            return (102, 102, 102) if label else (153, 153, 153)
        return r, g, b

    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    _hue, sat, value = colorsys.rgb_to_hsv(rf, gf, bf)

    if theme_id == MAP_THEME_STONE:
        if sat < 0.08 and value < 0.35:
            lift = 135.0 + value * 110.0
            return (_clamp8(lift * 0.86), _clamp8(lift * 0.94), _clamp8(lift))
        if sat < 0.08 and value > 0.94:
            return (210, 218, 228) if label else (195, 208, 222)
        if label:
            return (
                _clamp8(r * 0.97),
                _clamp8(g * 1.00 + 1),
                _clamp8(b * 1.04 + 3),
            )
        return (
            _clamp8(r * 0.92),
            _clamp8(g * 0.99 + 2),
            _clamp8(b * 1.08 + 6),
        )

    if sat < 0.08 and value > 0.90:
        return (108, 96, 72) if label else (122, 109, 82)
    if sat < 0.08 and value < 0.12:
        return (62, 52, 38)
    if label:
        return (
            _clamp8(r * 1.03 + 3),
            _clamp8(g * 1.00 + 1),
            _clamp8(b * 0.96),
        )
    return (
        _clamp8(r * 1.06 + 5),
        _clamp8(g * 1.01 + 2),
        _clamp8(b * 0.92),
    )

@dataclass(slots=True, frozen=True)
class RasterRequest:
    generation: int
    zone_map: ZoneMap
    canvas_width: int
    canvas_height: int
    buffer_px: int
    scale: float
    offset_x: float
    offset_y: float
    enabled_layers: tuple[int, ...]
    theme_id: str
    elevation_enabled: bool = False
    elevation_z: float = 0.0
    elevation_span: float = 150.0
    # Width is expressed in raster pixels. A supersampled cached wall must scale
    # its stroke width with the supersample factor; otherwise Tk's later subsample
    # operation can simply skip 1-pixel lines and turn them into dots/dashes.
    line_width: int = 1
    # Exact display levels built once from the original vectors.
    # Entries are (display_level, ratio_to_this_request).
    exact_levels: tuple[tuple[float, float], ...] = ()


@dataclass(slots=True)
class RasterResult:
    generation: int
    ppm: bytes
    image_x: int
    image_y: int
    image_width: int
    image_height: int
    viewport_lines: int
    buffered_lines: int
    source_lines: int
    # (display zoom level, PPM bytes), independently rasterized from vectors.
    exact_rasters: tuple[tuple[float, bytes], ...] = ()


def _z_visible(z0: float, z1: float, req: RasterRequest) -> bool:
    if not req.elevation_enabled:
        return True
    lo, hi = sorted((z0, z1))
    return not (
        hi < req.elevation_z - req.elevation_span
        or lo > req.elevation_z + req.elevation_span
    )


def _clip_line(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width: int,
    height: int,
) -> tuple[float, float, float, float] | None:
    """Liang-Barsky clip against the raster rectangle."""
    dx = x1 - x0
    dy = y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0, width - 1 - x0, y0, height - 1 - y0)
    u0 = 0.0
    u1 = 1.0
    for pi, qi in zip(p, q):
        if pi == 0.0:
            if qi < 0.0:
                return None
            continue
        t = qi / pi
        if pi < 0.0:
            if t > u1:
                return None
            if t > u0:
                u0 = t
        else:
            if t < u0:
                return None
            if t < u1:
                u1 = t
    return x0 + u0 * dx, y0 + u0 * dy, x0 + u1 * dx, y0 + u1 * dy


def _intersects_rect(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> bool:
    if max(x0, x1) < left or min(x0, x1) > right:
        return False
    if max(y0, y1) < top or min(y0, y1) > bottom:
        return False
    # Bounding-box overlap is sufficient for the status counter; actual drawing is
    # still clipped exactly by _clip_line.
    return True


def _draw_line(
    pixels: bytearray,
    width: int,
    height: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    color: RGB,
    *,
    line_width: int = 1,
) -> bool:
    clipped = _clip_line(x0, y0, x1, y1, width, height)
    if clipped is None:
        return False

    ix0, iy0, ix1, iy1 = (int(round(value)) for value in clipped)
    dx_abs = abs(ix1 - ix0)
    dy_abs = abs(iy1 - iy0)
    dx = dx_abs
    sx = 1 if ix0 < ix1 else -1
    dy = -dy_abs
    sy = 1 if iy0 < iy1 else -1
    error = dx + dy
    r, g, b = color
    stroke = max(1, int(line_width))
    stroke_start = -(stroke // 2)
    stroke_stop = stroke_start + stroke
    # Paint across the minor axis. This costs O(stroke) rather than an O(stroke²)
    # square brush while giving a continuous stroke that survives downsampling.
    vertical_stroke = dx_abs >= dy_abs

    while True:
        if vertical_stroke:
            for offset in range(stroke_start, stroke_stop):
                py = iy0 + offset
                if 0 <= ix0 < width and 0 <= py < height:
                    index = (py * width + ix0) * 3
                    pixels[index] = r
                    pixels[index + 1] = g
                    pixels[index + 2] = b
        else:
            for offset in range(stroke_start, stroke_stop):
                px = ix0 + offset
                if 0 <= px < width and 0 <= iy0 < height:
                    index = (iy0 * width + px) * 3
                    pixels[index] = r
                    pixels[index + 1] = g
                    pixels[index + 2] = b

        if ix0 == ix1 and iy0 == iy1:
            break
        twice = error * 2
        if twice >= dy:
            error += dy
            ix0 += sx
        if twice <= dx:
            error += dx
            iy0 += sy
    return True


def render_map_raster(req: RasterRequest) -> RasterResult:
    """Rasterize every native map line that can affect the buffered viewport.

    There is deliberately no line budget, deduplication, or adaptive level of detail.
    Off-screen clipping is lossless because those pixels cannot be seen. The returned
    PPM can be installed as one Tk PhotoImage, replacing thousands of Canvas line
    objects with a single movable object.
    """
    buffer_px = max(0, int(req.buffer_px))
    width = max(1, int(req.canvas_width) + buffer_px * 2)
    height = max(1, int(req.canvas_height) + buffer_px * 2)
    background = bytes(map_background_rgb(req.theme_id))
    pixels = bytearray(background * (width * height))

    color_cache: dict[tuple[int, int, int], RGB] = {}
    source_lines = 0
    viewport_lines = 0
    buffered_lines = 0
    view_left = float(buffer_px)
    view_top = float(buffer_px)
    view_right = float(buffer_px + req.canvas_width - 1)
    view_bottom = float(buffer_px + req.canvas_height - 1)

    for layer_no in req.enabled_layers:
        layer = req.zone_map.layers.get(layer_no)
        if layer is None:
            continue
        source_lines += len(layer.lines)
        for line in layer.lines:
            if not _z_visible(line.z0, line.z1, req):
                continue
            x0 = req.offset_x + line.x0 * req.scale + buffer_px
            y0 = req.offset_y + line.y0 * req.scale + buffer_px
            x1 = req.offset_x + line.x1 * req.scale + buffer_px
            y1 = req.offset_y + line.y1 * req.scale + buffer_px

            if _intersects_rect(
                x0,
                y0,
                x1,
                y1,
                view_left,
                view_top,
                view_right,
                view_bottom,
            ):
                viewport_lines += 1

            key = (line.r, line.g, line.b)
            color = color_cache.get(key)
            if color is None:
                color = themed_map_rgb(req.theme_id, *key)
                color_cache[key] = color
            if _draw_line(
                pixels,
                width,
                height,
                x0,
                y0,
                x1,
                y1,
                color,
                line_width=req.line_width,
            ):
                buffered_lines += 1

    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    ppm = header + bytes(pixels)
    exact_rasters: list[tuple[float, bytes]] = []
    for zoom_level, ratio in req.exact_levels:
        zoom_level = float(zoom_level)
        ratio = float(ratio)
        if ratio <= 0.0:
            continue
        if abs(ratio - 1.0) < 1e-12:
            exact_rasters.append((zoom_level, ppm))
            continue
        exact_req = RasterRequest(
            generation=req.generation,
            zone_map=req.zone_map,
            canvas_width=max(1, int(round(req.canvas_width * ratio))),
            canvas_height=max(1, int(round(req.canvas_height * ratio))),
            buffer_px=max(0, int(round(req.buffer_px * ratio))),
            scale=req.scale * ratio,
            offset_x=req.offset_x * ratio,
            offset_y=req.offset_y * ratio,
            enabled_layers=req.enabled_layers,
            theme_id=req.theme_id,
            elevation_enabled=req.elevation_enabled,
            elevation_z=req.elevation_z,
            elevation_span=req.elevation_span,
            line_width=max(1, int(round(req.line_width * ratio))),
            exact_levels=(),
        )
        exact_result = render_map_raster(exact_req)
        exact_rasters.append((zoom_level, exact_result.ppm))

    return RasterResult(
        generation=req.generation,
        ppm=ppm,
        image_x=-buffer_px,
        image_y=-buffer_px,
        image_width=width,
        image_height=height,
        viewport_lines=viewport_lines,
        buffered_lines=buffered_lines,
        source_lines=source_lines,
        exact_rasters=tuple(exact_rasters),
    )
