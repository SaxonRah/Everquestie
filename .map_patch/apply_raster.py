from pathlib import Path

path = Path('eqquest/mapview.py')
s = path.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected one match, found {count}')
    s = s.replace(old, new, 1)


def replace_block(start_marker: str, end_marker: str, new: str, label: str) -> None:
    global s
    start = s.find(start_marker)
    if start < 0:
        raise SystemExit(f'{label}: start marker missing')
    end = s.find(end_marker, start)
    if end < 0:
        raise SystemExit(f'{label}: end marker missing')
    s = s[:start] + new + s[end:]


replace_once(
    'import colorsys\nimport heapq\nimport json\nimport time\nimport tkinter as tk\n',
    'import json\nimport queue\nimport threading\nimport time\nimport tkinter as tk\n',
    'imports',
)
replace_once('from .mapindex import SpatialMapIndex, bbox_intersects\n', '', 'remove mapindex import')
replace_once(
    'from .db import Database\n',
    'from .db import Database\n'
    'from .mapraster import (\n'
    '    RasterRequest,\n'
    '    RasterResult,\n'
    '    map_background_rgb,\n'
    '    render_map_raster,\n'
    '    themed_map_rgb,\n'
    ')\n',
    'mapraster import',
)

mix_start = s.find('def _mix_rgb(')
if mix_start >= 0:
    mix_end = s.find('\n\nclass MapViewerFrame', mix_start)
    if mix_end < 0:
        raise SystemExit('mix helper end missing')
    s = s[:mix_start] + s[mix_end + 2:]

replace_once(
    '        # Only a buffered viewport worth of native map objects is kept in Tk.\n'
    '        # Good/Brewall maps can contain tens of thousands of segments; keeping\n'
    '        # all of them alive makes even Canvas.move() expensive on Windows Tk.\n'
    '        self._spatial_index: SpatialMapIndex | None = None\n'
    '        self._static_render_bounds: tuple[float, float, float, float] | None = None\n'
    '        self._static_refresh_job: str | None = None\n'
    '        self._base_map_status = ""\n\n'
    '        self._build()\n'
    '        self._apply_map_background()\n'
    '        self.after(250, self._poll_state)\n',
    '        # Native map geometry is rasterized off the Tk thread. The Canvas keeps\n'
    '        # one image plus lightweight labels/markers instead of thousands of lines.\n'
    '        self._base_map_status = ""\n'
    '        self._raster_photo: tk.PhotoImage | None = None\n'
    '        self._raster_generation = 0\n'
    '        self._raster_render_job: str | None = None\n'
    '        self._raster_requests: queue.Queue[RasterRequest] = queue.Queue(maxsize=1)\n'
    '        self._raster_results: queue.Queue[tuple[str, object]] = queue.Queue()\n'
    '        self._raster_thread = threading.Thread(\n'
    '            target=self._raster_worker, name="EverQuestieMapRaster", daemon=True\n'
    '        )\n'
    '        self._raster_thread.start()\n\n'
    '        self._build()\n'
    '        self._apply_map_background()\n'
    '        self.after(30, self._poll_raster_results)\n'
    '        self.after(250, self._poll_state)\n',
    'raster state',
)

replace_once(
    '        self.map_file.set(str(self.zone_map.base_path))\n'
    '        self._spatial_index = SpatialMapIndex(self.zone_map)\n'
    '        self._static_render_bounds = None\n'
    '        counts = []\n',
    '        self.map_file.set(str(self.zone_map.base_path))\n'
    '        self._invalidate_raster()\n'
    '        counts = []\n',
    'load map raster reset',
)

replace_once(
    '        self.offset_x += dx\n'
    '        self.offset_y += dy\n'
    '        self._pending_pan_dx += dx\n',
    '        self.offset_x += dx\n'
    '        self.offset_y += dy\n'
    '        self._invalidate_raster()\n'
    '        self._pending_pan_dx += dx\n',
    'pan invalidation',
)
replace_once(
    '        if dx or dy:\n'
    '            self.canvas.move("map_content", dx, dy)\n'
    '            self._schedule_static_refresh_if_needed(90)\n',
    '        if dx or dy:\n'
    '            self.canvas.move("map_content", dx, dy)\n',
    'pan move canvas',
)
replace_once(
    '        self._pan_start = None\n'
    '        self._schedule_static_refresh(0)\n'
    '        self._schedule_save_view(180)\n',
    '        self._pan_start = None\n'
    '        self._request_raster_render(0)\n'
    '        self._schedule_save_view(180)\n',
    'pan end raster',
)

old_zoom = '''        self.scale = new_scale\n        self.offset_x = sx + (self.offset_x - sx) * actual\n        self.offset_y = sy + (self.offset_y - sy) * actual\n        self.canvas.scale("map_content", sx, sy, actual, actual)\n        # Keep wheel interaction cheap: scale the current buffered display list\n        # immediately, then repopulate the viewport after wheel input settles.\n        self._schedule_static_refresh(90)\n        self._schedule_save_view()\n'''
new_zoom = '''        self.scale = new_scale\n        self.offset_x = sx + (self.offset_x - sx) * actual\n        self.offset_y = sy + (self.offset_y - sy) * actual\n        # Canvas image items cannot be smoothly scaled by canvas.scale(). Keep the\n        # last raster visible while wheel input is active, then replace it once the\n        # wheel settles. No thousands-of-object transform occurs here.\n        self._invalidate_raster()\n        self._request_raster_render(85)\n        self._schedule_save_view()\n'''
replace_once(old_zoom, new_zoom, 'zoom raster')

replace_once(
    '        if dx or dy:\n'
    '            self.canvas.move("map_content", dx, dy)\n'
    '            self._schedule_static_refresh_if_needed(60)\n',
    '        if dx or dy:\n'
    '            self._invalidate_raster()\n'
    '            self.canvas.move("map_content", dx, dy)\n',
    'move view raster',
)
replace_once(
    '        self._move_view_to(new_x, new_y)\n'
    '        self._schedule_save_view()\n',
    '        self._move_view_to(new_x, new_y)\n'
    '        self._request_raster_render(60)\n'
    '        self._schedule_save_view()\n',
    'center player raster',
)
# _center_entity contains the same two lines later; replace the remaining occurrence.
replace_once(
    '            self._move_view_to(new_x, new_y)\n'
    '            self._schedule_save_view()\n'
    '            return\n',
    '            self._move_view_to(new_x, new_y)\n'
    '            self._request_raster_render(60)\n'
    '            self._schedule_save_view()\n'
    '            return\n',
    'center entity raster',
)

old_resize = '''    def _on_resize(self, _event) -> None:\n        if self._fit_pending:\n            self.fit()\n        elif self.follow_player.get() and self.zone_map is not None and self.get_location():\n            self.center_player()\n        elif self.zone_map is not None:\n            self._schedule_static_refresh(80)\n        else:\n            self._draw_empty_message()\n\n'''
new_resize = '''    def _on_resize(self, _event) -> None:\n        if self._fit_pending:\n            self.fit()\n        elif self.follow_player.get() and self.zone_map is not None and self.get_location():\n            self.center_player()\n        elif self.zone_map is not None:\n            self._invalidate_raster()\n            self._request_raster_render(100)\n        else:\n            self._draw_empty_message()\n\n'''
replace_once(old_resize, new_resize, 'resize raster')

# Replace the old viewport-culling machinery with the off-thread raster pipeline.
replace_block(
    '    def _viewport_world_bounds(self, margin_px: float = 0.0)',
    '    def _on_elevation_changed(self) -> None:',
    '''    def _invalidate_raster(self) -> None:\n        self._raster_generation += 1\n\n    def _raster_worker(self) -> None:\n        while True:\n            req = self._raster_requests.get()\n            try:\n                result = render_map_raster(req)\n            except Exception as exc:\n                self._raster_results.put(("error", (req.generation, repr(exc))))\n            else:\n                self._raster_results.put(("ok", result))\n\n    def _request_raster_render(self, delay_ms: int = 0) -> None:\n        if self.zone_map is None:\n            return\n        if self._raster_render_job is not None:\n            try:\n                self.after_cancel(self._raster_render_job)\n            except tk.TclError:\n                pass\n        self._raster_render_job = self.after(max(0, delay_ms), self._start_raster_render)\n\n    def _start_raster_render(self) -> None:\n        self._raster_render_job = None\n        if self.zone_map is None:\n            return\n        enabled_z, z, span = self._z_context()\n        req = RasterRequest(\n            generation=self._raster_generation,\n            zone_map=self.zone_map,\n            canvas_width=max(1, self.canvas.winfo_width()),\n            canvas_height=max(1, self.canvas.winfo_height()),\n            buffer_px=220,\n            scale=self.scale,\n            offset_x=self.offset_x,\n            offset_y=self.offset_y,\n            enabled_layers=tuple(self._enabled_layers()),\n            theme_id=self._map_theme_id(),\n            elevation_enabled=enabled_z,\n            elevation_z=z,\n            elevation_span=span,\n        )\n        # Keep only the newest queued request. A render already in progress may finish,\n        # but its generation is discarded if the view changed in the meantime.\n        try:\n            while True:\n                self._raster_requests.get_nowait()\n        except queue.Empty:\n            pass\n        try:\n            self._raster_requests.put_nowait(req)\n        except queue.Full:\n            pass\n        if self._base_map_status:\n            self.map_status.set(f"{self._base_map_status} | rendering full-detail map…")\n\n    def _poll_raster_results(self) -> None:\n        try:\n            while True:\n                kind, payload = self._raster_results.get_nowait()\n                if kind == "ok":\n                    result = payload\n                    if isinstance(result, RasterResult) and result.generation == self._raster_generation:\n                        self._install_raster_result(result)\n                else:\n                    generation, message = payload\n                    if generation == self._raster_generation:\n                        self.map_status.set(f"Map raster failed: {message}")\n        except queue.Empty:\n            pass\n        self.after(30, self._poll_raster_results)\n\n    def _install_raster_result(self, result: RasterResult) -> None:\n        try:\n            photo = tk.PhotoImage(data=result.ppm, format="PPM")\n        except tk.TclError as exc:\n            self.map_status.set(f"Map image load failed: {exc}")\n            return\n        self.canvas.delete("map_raster")\n        self.canvas.delete("map_labels")\n        self._raster_photo = photo\n        item = self.canvas.create_image(\n            result.image_x,\n            result.image_y,\n            image=photo,\n            anchor="nw",\n            tags=("map_content", "map_raster"),\n        )\n        self.canvas.tag_lower(item)\n        self._draw_map_labels(buffer_px=220)\n        self._redraw_overlays()\n        self._redraw_position()\n        if self._base_map_status:\n            self.map_status.set(\n                f"{self._base_map_status} | full-detail raster | "\n                f"{result.viewport_lines:,} visible / {result.source_lines:,} source lines"\n            )\n\n    def _draw_map_labels(self, *, buffer_px: int = 0) -> None:\n        self.canvas.delete("map_labels")\n        if self.zone_map is None or not self.show_labels.get():\n            return\n        z_context = self._z_context()\n        left = -buffer_px\n        top = -buffer_px\n        right = self.canvas.winfo_width() + buffer_px\n        bottom = self.canvas.winfo_height() + buffer_px\n        for layer_no in self._enabled_layers():\n            layer = self.zone_map.layers.get(layer_no)\n            if layer is None:\n                continue\n            for point in layer.points:\n                if not self._z_visible_for_context(point.z, None, z_context):\n                    continue\n                x, y = self._world_to_screen(point.x, point.y)\n                if x < left or x > right or y < top or y > bottom:\n                    continue\n                font_size = {1: 8, 2: 10, 3: 12}.get(point.size, 9)\n                self.canvas.create_text(\n                    x,\n                    y,\n                    text=point.display_text,\n                    fill=self._themed_map_color(point.r, point.g, point.b, label=True),\n                    font=("TkDefaultFont", font_size),\n                    anchor="center",\n                    tags=("map_content", "map_labels"),\n                )\n\n''',
    'raster helpers',
)

replace_once(
    '    def _on_elevation_changed(self) -> None:\n'
    '        loc = self.get_location()\n'
    '        self._last_filter_z = float(loc[2]) if loc and self.filter_elevation.get() else None\n'
    '        self._rebuild_static()\n'
    '        self._redraw_overlays()\n',
    '    def _on_elevation_changed(self) -> None:\n'
    '        loc = self.get_location()\n'
    '        self._last_filter_z = float(loc[2]) if loc and self.filter_elevation.get() else None\n'
    '        self._invalidate_raster()\n'
    '        self._request_raster_render(0)\n'
    '        self._redraw_overlays()\n',
    'elevation raster',
)

# Replace theme-color implementation with the same pure mapping used by raster worker.
replace_block(
    '    def _apply_map_background(self) -> None:',
    '    def _overlay_palette(self) -> dict[str, str]:',
    '''    def _apply_map_background(self) -> None:\n        r, g, b = map_background_rgb(self._map_theme_id())\n        self.canvas.configure(background=_hex_color(r, g, b))\n\n    def _themed_map_color(self, r: int, g: int, b: int, *, label: bool = False) -> str:\n        theme_id = self._map_theme_id()\n        key = (theme_id, r, g, b, label)\n        cached = self._color_cache.get(key)\n        if cached is not None:\n            return cached\n        rgb = themed_map_rgb(theme_id, r, g, b, label=label)\n        color = _hex_color(*rgb)\n        self._color_cache[key] = color\n        return color\n\n''',
    'theme mapping',
)

# The static vector builder is now a compatibility shim that schedules a raster.
replace_block(
    '    def _rebuild_static(self) -> None:',
    '    def _redraw_overlays(self) -> None:',
    '''    def _rebuild_static(self) -> None:\n        self._invalidate_raster()\n        self._request_raster_render(0)\n\n    def _apply_static_visibility(self) -> None:\n        self._on_static_options_changed()\n\n    def _on_static_options_changed(self) -> None:\n        self._invalidate_raster()\n        self._request_raster_render(0)\n\n''',
    'replace static vector renderer',
)

old_redraw = '''    def redraw(self) -> None:\n        """Full rebuild for map/content option changes, never used for pan/zoom."""\n        self.canvas.delete("all")\n        self._overlay_entity_by_item.clear()\n        self._apply_map_background()\n        if self.zone_map is None:\n            self._draw_empty_message()\n            return\n        self._rebuild_static()\n        self._redraw_overlays()\n        self._redraw_position()\n'''
new_redraw = '''    def redraw(self) -> None:\n        """Request a full-detail raster; dynamic overlays remain lightweight."""\n        self._apply_map_background()\n        if self.zone_map is None:\n            self._draw_empty_message()\n            return\n        self._invalidate_raster()\n        self._request_raster_render(0)\n        self._redraw_overlays()\n        self._redraw_position()\n'''
replace_once(old_redraw, new_redraw, 'redraw raster')

# Follow-player moves only one current image during movement and refreshes the raster
# after movement settles, rather than rebuilding the native map for each /loc.
replace_once(
    '                self._move_view_to(new_x, new_y)\n\n'
    '            # Normal /loc updates touch only the small trail/player objects. The\n',
    '                self._move_view_to(new_x, new_y)\n'
    '                self._request_raster_render(250)\n\n'
    '            # Normal /loc updates touch only the small trail/player objects. The\n',
    'follow player raster',
)

# Make the empty state clear any old map image/labels if a map is unloaded.
replace_once(
    '    def _draw_empty_message(self) -> None:\n'
    '        self.canvas.delete("map_message")\n'
    '        if self.zone_map is None:\n',
    '    def _draw_empty_message(self) -> None:\n'
    '        self.canvas.delete("map_message")\n'
    '        if self.zone_map is None:\n'
    '            self.canvas.delete("map_raster")\n'
    '            self.canvas.delete("map_labels")\n',
    'empty raster clear',
)

path.write_text(s, encoding='utf-8')
