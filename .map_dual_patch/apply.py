from pathlib import Path

path = Path('eqquest/mapview.py')
s = path.read_text(encoding='utf-8')


def replace_once(old: str, new: str, label: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected one match, found {count}')
    s = s.replace(old, new, 1)


def replace_method(start_name: str, next_name: str, new_text: str) -> None:
    global s
    start = s.index(f'    def {start_name}')
    end = s.index(f'    def {next_name}', start)
    s = s[:start] + new_text.rstrip() + '\n\n' + s[end:]


replace_once(
    'import json\nimport queue\n',
    'import json\nimport queue\nfrom fractions import Fraction\n',
    'Fraction import',
)
replace_once(
    'MAP_THEME_BY_LABEL = {label: key for key, label in MAP_THEME_LABELS.items()}\n',
    'MAP_THEME_BY_LABEL = {label: key for key, label in MAP_THEME_LABELS.items()}\n\n'
    '# The wall image is cached at high resolution and zoomed in Tk. These levels\n'
    '# keep zoom predictable and allow exact rational image scaling without\n'
    '# rerasterizing native EQ geometry on wheel events.\n'
    'MAP_ZOOM_LEVELS = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00, 4.00)\n',
    'zoom levels',
)

old_state = '''        # Native map geometry is rasterized off the Tk thread. The Canvas keeps
        # one image plus lightweight labels/markers instead of thousands of lines.
        self._base_map_status = ""
        self._raster_photo: tk.PhotoImage | None = None
        self._raster_generation = 0
        self._raster_render_job: str | None = None
        self._raster_requests: queue.Queue[RasterRequest] = queue.Queue(maxsize=1)
        self._raster_results: queue.Queue[tuple[str, object]] = queue.Queue()
        self._raster_thread = threading.Thread(
            target=self._raster_worker, name="EverQuestieMapRaster", daemon=True
        )
        self._raster_thread.start()
'''
new_state = '''        # Dual-layer map model. Native EQ line geometry becomes one cached, full-map
        # wall image. Pan/zoom never walks map lines again. Text/locations stay as
        # independent Canvas objects so they remain selectable and database-aware.
        self._base_map_status = ""
        self._raster_photo: tk.PhotoImage | None = None          # high-res wall source
        self._display_photo: tk.PhotoImage | None = None         # current zoom cache entry
        self._display_image_item: int | None = None
        self._wall_scaled_cache: dict[tuple[int, int], tk.PhotoImage] = {}
        self._wall_world_origin = (0.0, 0.0)
        self._wall_base_scale = 1.0
        self._wall_fit_scale = 1.0
        self._wall_render_factor = 1
        self._wall_dirty = True
        self._raster_generation = 0
        self._raster_render_job: str | None = None
        self._raster_requests: queue.Queue[RasterRequest] = queue.Queue(maxsize=1)
        self._raster_results: queue.Queue[tuple[str, object]] = queue.Queue()
        self._raster_meta: dict[int, tuple[float, float, float, int, float]] = {}
        self._raster_thread = threading.Thread(
            target=self._raster_worker, name="EverQuestieMapRaster", daemon=True
        )
        self._raster_thread.start()

        # Selectable non-wall layer + local knowledge lookup state.
        self._map_label_text_by_item: dict[int, str] = {}
        self.lookup_query = tk.StringVar()
        self.lookup_status = tk.StringVar(value="Click a map name or search the local DB.")
        self._lookup_entity_by_item: dict[str, int] = {}
        self._lookup_selected_entity: int | None = None
'''
replace_once(old_state, new_state, 'dual layer state')

replace_once(
    '                command=self._on_static_options_changed,\n',
    '                command=self._on_wall_options_changed,\n',
    'layer callback',
)
replace_once(
    '            line1, text="Map labels", variable=self.show_labels, command=self._on_static_options_changed\n',
    '            line1, text="Map labels", variable=self.show_labels, command=self._on_labels_changed\n',
    'label callback',
)

old_side = '''        side = ttk.Frame(body, padding=(8, 0, 0, 0))
        side.rowconfigure(3, weight=1)
        side.columnconfigure(0, weight=1)
        body.add(side, weight=1)
        ttk.Label(side, textvariable=self.map_status, wraplength=260, justify="left").grid(row=0, column=0, sticky="ew")
        ttk.Label(side, textvariable=self.coord_status, wraplength=260, justify="left").grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(side, text="Imported locations in this zone").grid(row=2, column=0, sticky="w", pady=(12, 2))
        self.marker_list = tk.Listbox(side, exportselection=False)
        self.marker_list.grid(row=3, column=0, sticky="nsew")
        marker_scroll = ttk.Scrollbar(side, orient="vertical", command=self.marker_list.yview)
        marker_scroll.grid(row=3, column=1, sticky="ns")
        self.marker_list.configure(yscrollcommand=marker_scroll.set)
        self.marker_list.bind("<<ListboxSelect>>", self._marker_selected)
        self._marker_ids: list[int] = []
'''
new_side = '''        side = ttk.Frame(body, padding=(8, 0, 0, 0))
        side.rowconfigure(4, weight=2)
        side.rowconfigure(5, weight=2)
        side.rowconfigure(8, weight=2)
        side.columnconfigure(0, weight=1)
        body.add(side, weight=1)
        ttk.Label(side, textvariable=self.map_status, wraplength=300, justify="left").grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(side, textvariable=self.coord_status, wraplength=300, justify="left").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        ttk.Label(side, text="Map / local database lookup").grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 2))
        lookup_row = ttk.Frame(side)
        lookup_row.grid(row=3, column=0, columnspan=2, sticky="ew")
        lookup_row.columnconfigure(0, weight=1)
        lookup_entry = ttk.Entry(lookup_row, textvariable=self.lookup_query)
        lookup_entry.grid(row=0, column=0, sticky="ew")
        lookup_entry.bind("<Return>", lambda _e: self._lookup_name(self.lookup_query.get()))
        ttk.Button(lookup_row, text="Search", command=lambda: self._lookup_name(self.lookup_query.get())).grid(row=0, column=1, padx=(4, 0))

        self.lookup_tree = ttk.Treeview(side, columns=("kind", "relation"), show="tree headings", height=8, selectmode="browse")
        self.lookup_tree.heading("#0", text="Name")
        self.lookup_tree.heading("kind", text="Type")
        self.lookup_tree.heading("relation", text="Relationship")
        self.lookup_tree.column("#0", width=160, stretch=True)
        self.lookup_tree.column("kind", width=72, stretch=False)
        self.lookup_tree.column("relation", width=105, stretch=True)
        self.lookup_tree.grid(row=4, column=0, sticky="nsew")
        lookup_scroll = ttk.Scrollbar(side, orient="vertical", command=self.lookup_tree.yview)
        lookup_scroll.grid(row=4, column=1, sticky="ns")
        self.lookup_tree.configure(yscrollcommand=lookup_scroll.set)
        self.lookup_tree.bind("<<TreeviewSelect>>", self._lookup_tree_selected)
        self.lookup_tree.bind("<Double-1>", self._open_lookup_in_knowledge)

        detail_frame = ttk.Frame(side)
        detail_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(4, 0))
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.lookup_detail = tk.Text(detail_frame, height=8, wrap="word", state="disabled")
        self.lookup_detail.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.lookup_detail.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.lookup_detail.configure(yscrollcommand=detail_scroll.set)
        lookup_actions = ttk.Frame(side)
        lookup_actions.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        ttk.Button(lookup_actions, text="Open in Knowledge", command=self._open_lookup_in_knowledge).pack(side="left")
        ttk.Label(lookup_actions, textvariable=self.lookup_status).pack(side="left", padx=(6, 0))

        ttk.Label(side, text="Imported locations in this zone").grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 2))
        self.marker_list = tk.Listbox(side, exportselection=False)
        self.marker_list.grid(row=8, column=0, sticky="nsew")
        marker_scroll = ttk.Scrollbar(side, orient="vertical", command=self.marker_list.yview)
        marker_scroll.grid(row=8, column=1, sticky="ns")
        self.marker_list.configure(yscrollcommand=marker_scroll.set)
        self.marker_list.bind("<<ListboxSelect>>", self._marker_selected)
        self.marker_list.bind("<Double-1>", self._open_lookup_in_knowledge)
        self._marker_ids: list[int] = []
        self._marker_names: list[str] = []

        self.canvas.tag_bind("map_label_clickable", "<Enter>", lambda _e: self.canvas.configure(cursor="hand2"))
        self.canvas.tag_bind("map_label_clickable", "<Leave>", lambda _e: self.canvas.configure(cursor=""))
        self.canvas.tag_bind("eqquest_overlay", "<Enter>", lambda _e: self.canvas.configure(cursor="hand2"))
        self.canvas.tag_bind("eqquest_overlay", "<Leave>", lambda _e: self.canvas.configure(cursor=""))
'''
replace_once(old_side, new_side, 'side panel')

# load_map: reset the cached wall and clickable labels.
replace_once(
    '        self.canvas.delete("all")\n        self._overlay_entity_by_item.clear()\n        self.map_file.set(str(self.zone_map.base_path))\n        self._invalidate_raster()\n',
    '        self.canvas.delete("all")\n        self._overlay_entity_by_item.clear()\n        self._map_label_text_by_item.clear()\n        self._raster_photo = None\n        self._display_photo = None\n        self._display_image_item = None\n        self._wall_scaled_cache.clear()\n        self._wall_dirty = True\n        self.map_file.set(str(self.zone_map.base_path))\n        self._invalidate_raster()\n',
    'load map reset',
)

replace_method('fit(self) -> None:', 'center_player(self)', r'''    def fit(self) -> None:
        if self.zone_map is None:
            return
        transform = self._calculate_fit_transform()
        if transform is None:
            return
        scale, offset_x, offset_y = transform
        self.scale = scale
        self.offset_x = offset_x
        self.offset_y = offset_y
        self._wall_fit_scale = scale
        self._fit_pending = False
        if self._raster_photo is None or self._wall_dirty:
            self.redraw()
        else:
            self._refresh_wall_display()
            self._draw_map_labels()
            self._redraw_overlays()
            self._redraw_position()
        self._schedule_save_view(500)''')

replace_method('center_player(self) -> None:', '_on_resize(self', r'''    def center_player(self) -> None:
        loc = self.get_location()
        if not loc:
            self.coord_status.set("No /loc has been observed yet.")
            return
        mx, my, _ = game_to_map(*loc)
        new_x = self.canvas.winfo_width() * 0.5 - mx * self.scale
        new_y = self.canvas.winfo_height() * 0.5 - my * self.scale
        self._move_view_to(new_x, new_y)
        self._schedule_save_view()''')

replace_method('_on_resize(self, _event) -> None:', '_pan_begin(self', r'''    def _on_resize(self, _event) -> None:
        if self._fit_pending:
            self.fit()
        elif self.follow_player.get() and self.zone_map is not None and self.get_location():
            self.center_player()
        elif self.zone_map is not None:
            # Resize the cached wall presentation only. Native map lines are not
            # rerasterized merely because the window changed size.
            self._refresh_wall_display()
            self._draw_map_labels()
            self._redraw_overlays()
            self._redraw_position()
        else:
            self._draw_empty_message()''')

replace_method('_pan_begin(self, event) -> None:', '_pan_move(self', r'''    def _pan_begin(self, event) -> None:
        item = self.canvas.find_withtag("current")
        if item:
            item_id = item[0]
            label = self._map_label_text_by_item.get(item_id)
            if label:
                self._lookup_name(label)
                return
            entity_id = self._overlay_entity_by_item.get(item_id)
            if entity_id is not None:
                self._show_entity_in_lookup(entity_id)
                self._center_entity(entity_id)
                return
        self._pan_start = (event.x, event.y)''')

# Pan should move the cached image and interactive layer only; no wall invalidation.
replace_once('        self._invalidate_raster()\n        self._pending_pan_dx += dx\n', '        self._pending_pan_dx += dx\n', 'pan invalidation')
replace_once('        self._pan_start = None\n        self._request_raster_render(0)\n        self._schedule_save_view(180)\n', '        self._pan_start = None\n        self._schedule_save_view(180)\n', 'pan end render')

replace_method('_zoom_at(self, sx: float, sy: float, factor: float) -> None:', '_move_view_to(self', r'''    def _zoom_at(self, sx: float, sy: float, factor: float) -> None:
        if self.zone_map is None:
            return
        if self._wall_fit_scale <= 0:
            transform = self._calculate_fit_transform()
            if transform is None:
                return
            self._wall_fit_scale = transform[0]

        current_level = self.scale / max(self._wall_fit_scale, 1e-9)
        nearest = min(range(len(MAP_ZOOM_LEVELS)), key=lambda i: abs(MAP_ZOOM_LEVELS[i] - current_level))
        if factor > 1.0:
            target_index = min(len(MAP_ZOOM_LEVELS) - 1, nearest + 1)
        else:
            target_index = max(0, nearest - 1)
        level = MAP_ZOOM_LEVELS[target_index]
        new_scale = self._wall_fit_scale * level
        old_scale = self.scale
        actual = new_scale / max(old_scale, 1e-9)
        if abs(actual - 1.0) < 1e-9:
            return

        self.scale = new_scale
        self.offset_x = sx + (self.offset_x - sx) * actual
        self.offset_y = sy + (self.offset_y - sy) * actual
        self._refresh_wall_display()
        self._draw_map_labels()
        self._redraw_overlays()
        self._redraw_position()
        self._schedule_save_view()''')

# Moving to player/entity just repositions the cached wall.
replace_once('        if dx or dy:\n            self._invalidate_raster()\n            self.canvas.move("map_content", dx, dy)\n', '        if dx or dy:\n            self.canvas.move("map_content", dx, dy)\n', 'move view invalidation')

# Imported locations become database searches, not immediate tab jumps.
replace_once(
    '        self.marker_list.delete(0, "end")\n        self._marker_ids = []\n',
    '        self.marker_list.delete(0, "end")\n        self._marker_ids = []\n        self._marker_names = []\n',
    'marker reset names',
)
replace_once(
    '            self._marker_ids.append(eid)\n',
    '            self._marker_ids.append(eid)\n            self._marker_names.append(str(row["name"]))\n',
    'marker names append',
)

replace_method('_marker_selected(self, _event) -> None:', 'focus_entity(self', r'''    def _marker_selected(self, _event) -> None:
        sel = self.marker_list.curselection()
        if not sel:
            return
        index = int(sel[0])
        eid = self._marker_ids[index]
        name = self._marker_names[index] if index < len(self._marker_names) else ""
        self._center_entity(eid)
        self._lookup_name(name, preferred_entity_id=eid)''')

replace_method('_center_entity(self, entity_id: int) -> None:', '# ------------------------------------------------------------------\n    # Map-only visual themes', r'''    def _center_entity(self, entity_id: int) -> None:
        zone = self.get_zone()
        if not zone:
            return
        for row in self.db.locations_for_entity(entity_id):
            if row["zone_name"] and row["zone_name"].casefold() != zone.casefold():
                continue
            if row["x"] is None or row["y"] is None:
                continue
            mx, my, _ = game_to_map(float(row["x"]), float(row["y"]), float(row["z"] or 0.0))
            new_x = self.canvas.winfo_width() * 0.5 - mx * self.scale
            new_y = self.canvas.winfo_height() * 0.5 - my * self.scale
            self._move_view_to(new_x, new_y)
            self._schedule_save_view()
            return

    def _lookup_candidates(self, term: str, preferred_entity_id: int | None = None):
        term = " ".join((term or "").replace("_", " ").split()).strip()
        if not term:
            return []
        rows = []
        seen: set[int] = set()
        if preferred_entity_id is not None:
            row = self.db.entity(preferred_entity_id)
            if row is not None:
                rows.append(row)
                seen.add(int(row["id"]))
        exact, _status = self.db.resolve_entity(term)
        if exact is not None and int(exact["id"]) not in seen:
            rows.append(exact)
            seen.add(int(exact["id"]))
        for row in self.db.search_entities_fts(term, limit=40):
            eid = int(row["id"])
            if eid not in seen:
                rows.append(row)
                seen.add(eid)
        return rows[:40]

    def _lookup_name(self, term: str, preferred_entity_id: int | None = None) -> None:
        term = " ".join((term or "").replace("_", " ").split()).strip()
        if not term:
            return
        self.lookup_query.set(term)
        rows = self._lookup_candidates(term, preferred_entity_id)
        self.lookup_tree.delete(*self.lookup_tree.get_children())
        self._lookup_entity_by_item.clear()
        self._lookup_selected_entity = None
        if not rows:
            self.lookup_status.set("No local DB match")
            self._set_lookup_detail(f"No local EverQuestie knowledge matches: {term}")
            return
        for row in rows:
            item = self.lookup_tree.insert("", "end", text=row["name"], values=(row["kind"], "match"))
            self._lookup_entity_by_item[item] = int(row["id"])
        first = self.lookup_tree.get_children()[0]
        self.lookup_tree.selection_set(first)
        self.lookup_tree.focus(first)
        self.lookup_tree.see(first)
        self._show_entity_info(self._lookup_entity_by_item[first], tree_item=first)
        self.lookup_status.set(f"{len(rows)} local match" + ("es" if len(rows) != 1 else ""))

    def _show_entity_in_lookup(self, entity_id: int) -> None:
        row = self.db.entity(entity_id)
        if row is None:
            return
        self.lookup_query.set(str(row["name"]))
        self.lookup_tree.delete(*self.lookup_tree.get_children())
        self._lookup_entity_by_item.clear()
        item = self.lookup_tree.insert("", "end", text=row["name"], values=(row["kind"], "selected"), open=True)
        self._lookup_entity_by_item[item] = entity_id
        self.lookup_tree.selection_set(item)
        self._show_entity_info(entity_id, tree_item=item)
        self.lookup_status.set("Selected map entity")

    def _show_entity_info(self, entity_id: int, *, tree_item: str | None = None) -> None:
        row = self.db.entity(entity_id)
        if row is None:
            return
        self._lookup_selected_entity = entity_id
        aliases = [str(r["alias"]) for r in self.db.aliases_for_entity(entity_id)]
        relationships = list(self.db.relationships_for_entity(entity_id))
        detail = self.db.entity_detail(entity_id)
        sources = list(self.db.sources_for_entity(entity_id))

        lines = [f'[{row["kind"]}] {row["name"]}']
        if row["zone"]:
            lines.append(f'Zone: {row["zone"]}')
        if row["level_min"] is not None or row["level_max"] is not None:
            lo = row["level_min"] if row["level_min"] is not None else "?"
            hi = row["level_max"] if row["level_max"] is not None else lo
            lines.append(f'Level: {lo}' if lo == hi else f'Levels: {lo}-{hi}')
        if aliases:
            lines.append('Aliases: ' + ', '.join(aliases[:12]))
        if row["notes"]:
            lines.append('')
            lines.append(str(row["notes"]))

        if detail is not None and detail["detail_text"]:
            text = str(detail["detail_text"]).strip()
            if text:
                lines.append('')
                lines.append('Details:')
                lines.append(text[:2600] + ('…' if len(text) > 2600 else ''))

        if relationships:
            grouped: dict[tuple[str, str], int] = {}
            for rel in relationships:
                if rel["direction"] == "out":
                    other_kind = str(rel["target_kind"])
                else:
                    other_kind = str(rel["source_kind"])
                key = (str(rel["relation"]), other_kind)
                grouped[key] = grouped.get(key, 0) + 1
            lines.append('')
            lines.append('Related: ' + ', '.join(
                f'{relation} {count} {kind}' for (relation, kind), count in sorted(grouped.items())
            ))
        if sources:
            lines.append(f'Sources: {len(sources)}')
        self._set_lookup_detail('\n'.join(lines))

        if tree_item is not None and not self.lookup_tree.get_children(tree_item):
            for rel in relationships[:250]:
                if rel["direction"] == "out":
                    other_id = int(rel["target_entity_id"])
                    other_kind = str(rel["target_kind"])
                    other_name = str(rel["target_name"])
                    relation = str(rel["relation"]) + " →"
                else:
                    other_id = int(rel["source_entity_id"])
                    other_kind = str(rel["source_kind"])
                    other_name = str(rel["source_name"])
                    relation = "← " + str(rel["relation"])
                child = self.lookup_tree.insert(tree_item, "end", text=other_name, values=(other_kind, relation))
                self._lookup_entity_by_item[child] = other_id
            if relationships:
                self.lookup_tree.item(tree_item, open=True)

    def _set_lookup_detail(self, text: str) -> None:
        self.lookup_detail.configure(state="normal")
        self.lookup_detail.delete("1.0", "end")
        self.lookup_detail.insert("1.0", text)
        self.lookup_detail.configure(state="disabled")

    def _lookup_tree_selected(self, _event=None) -> None:
        sel = self.lookup_tree.selection()
        if not sel:
            return
        item = sel[0]
        entity_id = self._lookup_entity_by_item.get(item)
        if entity_id is None:
            return
        self._show_entity_info(entity_id, tree_item=item)

    def _open_lookup_in_knowledge(self, _event=None) -> None:
        if self._lookup_selected_entity is not None and self.on_entity:
            self.on_entity(self._lookup_selected_entity)

    # ------------------------------------------------------------------
    # Map-only visual themes''')

# Map theme alters the cached wall, so rerender only here (not on zoom/pan).
replace_method('_on_map_theme_changed(self, _event=None) -> None:', '_apply_map_background(self', r'''    def _on_map_theme_changed(self, _event=None) -> None:
        theme_id = self._map_theme_id()
        self.db.set_meta(MAP_THEME_META, theme_id)
        self._color_cache.clear()
        self._apply_map_background()
        self._wall_dirty = True
        self._invalidate_raster()
        self.redraw()''')

# Replace the old viewport-raster block with one cached full-map wall image.
start = s.index('    def _invalidate_raster(self) -> None:\n')
end = s.index('    def _redraw_overlays(self) -> None:\n', start)
new_render = r'''    def _calculate_fit_transform(self) -> tuple[float, float, float] | None:
        if self.zone_map is None:
            return None
        bounds = self.zone_map.bounds(self._enabled_layers())
        if bounds is None:
            return None
        minx, miny, maxx, maxy = bounds
        w = max(100, self.canvas.winfo_width())
        h = max(100, self.canvas.winfo_height())
        pad = 30.0
        dx = max(1.0, maxx - minx)
        dy = max(1.0, maxy - miny)
        scale = min((w - 2 * pad) / dx, (h - 2 * pad) / dy)
        cx = (minx + maxx) * 0.5
        cy = (miny + maxy) * 0.5
        return scale, w * 0.5 - cx * scale, h * 0.5 - cy * scale

    def _wall_supersample_factor(self) -> int:
        w = max(100, self.canvas.winfo_width())
        h = max(100, self.canvas.winfo_height())
        # Keep a crisp full-map source without letting one map image consume
        # unbounded RAM. 18M RGB pixels is about 54 MB before Tk overhead.
        for factor in (4, 3, 2, 1):
            if w * h * factor * factor <= 18_000_000:
                return factor
        return 1

    def _invalidate_raster(self) -> None:
        self._raster_generation += 1

    def _raster_worker(self) -> None:
        while True:
            req = self._raster_requests.get()
            try:
                result = render_map_raster(req)
            except Exception as exc:
                self._raster_results.put(("error", (req.generation, repr(exc))))
            else:
                self._raster_results.put(("ok", result))

    def _request_raster_render(self, delay_ms: int = 0) -> None:
        if self.zone_map is None or not self._wall_dirty:
            return
        if self._raster_render_job is not None:
            try:
                self.after_cancel(self._raster_render_job)
            except tk.TclError:
                pass
        self._raster_render_job = self.after(max(0, delay_ms), self._start_raster_render)

    def _start_raster_render(self) -> None:
        self._raster_render_job = None
        if self.zone_map is None or not self._wall_dirty:
            return
        transform = self._calculate_fit_transform()
        if transform is None:
            return
        fit_scale, fit_offset_x, fit_offset_y = transform
        factor = self._wall_supersample_factor()
        render_w = max(1, self.canvas.winfo_width()) * factor
        render_h = max(1, self.canvas.winfo_height()) * factor
        base_scale = fit_scale * factor
        base_offset_x = fit_offset_x * factor
        base_offset_y = fit_offset_y * factor
        enabled_z, z, span = self._z_context()
        generation = self._raster_generation
        self._raster_meta[generation] = (
            base_scale, base_offset_x, base_offset_y, factor, fit_scale
        )
        req = RasterRequest(
            generation=generation,
            zone_map=self.zone_map,
            canvas_width=render_w,
            canvas_height=render_h,
            buffer_px=0,
            scale=base_scale,
            offset_x=base_offset_x,
            offset_y=base_offset_y,
            enabled_layers=tuple(self._enabled_layers()),
            theme_id=self._map_theme_id(),
            elevation_enabled=enabled_z,
            elevation_z=z,
            elevation_span=span,
        )
        try:
            while True:
                self._raster_requests.get_nowait()
        except queue.Empty:
            pass
        try:
            self._raster_requests.put_nowait(req)
        except queue.Full:
            pass
        if self._base_map_status:
            self.map_status.set(f"{self._base_map_status} | building cached wall image…")

    def _poll_raster_results(self) -> None:
        try:
            while True:
                kind, payload = self._raster_results.get_nowait()
                if kind == "ok":
                    result = payload
                    if isinstance(result, RasterResult) and result.generation == self._raster_generation:
                        self._install_raster_result(result)
                else:
                    generation, message = payload
                    if generation == self._raster_generation:
                        self.map_status.set(f"Map wall image failed: {message}")
        except queue.Empty:
            pass
        self.after(30, self._poll_raster_results)

    def _install_raster_result(self, result: RasterResult) -> None:
        meta = self._raster_meta.pop(result.generation, None)
        if meta is None:
            return
        try:
            photo = tk.PhotoImage(data=result.ppm, format="PPM")
        except tk.TclError as exc:
            self.map_status.set(f"Map image load failed: {exc}")
            return
        base_scale, base_offset_x, base_offset_y, factor, fit_scale = meta
        self._raster_photo = photo
        self._display_photo = None
        self._wall_scaled_cache.clear()
        self._wall_base_scale = base_scale
        self._wall_fit_scale = fit_scale
        self._wall_render_factor = factor
        self._wall_world_origin = (
            -base_offset_x / max(base_scale, 1e-9),
            -base_offset_y / max(base_scale, 1e-9),
        )
        self._wall_dirty = False
        self.canvas.delete("map_raster")
        self._display_image_item = None
        self._refresh_wall_display()
        self._draw_map_labels()
        self._redraw_overlays()
        self._redraw_position()
        if self._base_map_status:
            self.map_status.set(
                f"{self._base_map_status} | cached full-detail wall | "
                f"{result.source_lines:,} source lines | {factor}x source image"
            )

    def _scaled_wall_photo(self) -> tk.PhotoImage | None:
        if self._raster_photo is None:
            return None
        ratio = self.scale / max(self._wall_base_scale, 1e-9)
        fraction = Fraction(ratio).limit_denominator(16)
        numerator = max(1, fraction.numerator)
        denominator = max(1, fraction.denominator)
        key = (numerator, denominator)
        cached = self._wall_scaled_cache.get(key)
        if cached is not None:
            return cached
        target = tk.PhotoImage()
        try:
            target.tk.call(
                str(target), "copy", str(self._raster_photo),
                "-zoom", numerator, numerator,
                "-subsample", denominator, denominator,
            )
        except tk.TclError:
            return self._raster_photo
        self._wall_scaled_cache[key] = target
        # Bound the cache; common zoom levels stay hot without retaining every
        # historical window/fit ratio forever.
        if len(self._wall_scaled_cache) > 12:
            oldest = next(iter(self._wall_scaled_cache))
            if oldest != key:
                self._wall_scaled_cache.pop(oldest, None)
        return target

    def _refresh_wall_display(self) -> None:
        photo = self._scaled_wall_photo()
        if photo is None:
            return
        self._display_photo = photo
        world_x, world_y = self._wall_world_origin
        x, y = self._world_to_screen(world_x, world_y)
        if self._display_image_item is None:
            self._display_image_item = self.canvas.create_image(
                x, y, image=photo, anchor="nw", tags=("map_content", "map_raster")
            )
        else:
            try:
                self.canvas.itemconfigure(self._display_image_item, image=photo)
                self.canvas.coords(self._display_image_item, x, y)
            except tk.TclError:
                self._display_image_item = self.canvas.create_image(
                    x, y, image=photo, anchor="nw", tags=("map_content", "map_raster")
                )
        self.canvas.tag_lower(self._display_image_item)

    def _draw_map_labels(self, *, buffer_px: int = 80) -> None:
        self.canvas.delete("map_labels")
        self._map_label_text_by_item.clear()
        if self.zone_map is None or not self.show_labels.get():
            return
        z_context = self._z_context()
        left = -buffer_px
        top = -buffer_px
        right = self.canvas.winfo_width() + buffer_px
        bottom = self.canvas.winfo_height() + buffer_px
        for layer_no in self._enabled_layers():
            layer = self.zone_map.layers.get(layer_no)
            if layer is None:
                continue
            for point in layer.points:
                if not self._z_visible_for_context(point.z, None, z_context):
                    continue
                x, y = self._world_to_screen(point.x, point.y)
                if x < left or x > right or y < top or y > bottom:
                    continue
                font_size = {1: 8, 2: 10, 3: 12}.get(point.size, 9)
                item = self.canvas.create_text(
                    x, y,
                    text=point.display_text,
                    fill=self._themed_map_color(point.r, point.g, point.b, label=True),
                    font=("TkDefaultFont", font_size),
                    anchor="center",
                    tags=("map_content", "map_labels", "map_label_clickable"),
                )
                self._map_label_text_by_item[item] = point.display_text

    def _on_elevation_changed(self) -> None:
        loc = self.get_location()
        self._last_filter_z = float(loc[2]) if loc and self.filter_elevation.get() else None
        self._wall_dirty = True
        self._invalidate_raster()
        self._request_raster_render(0)
        self._redraw_overlays()

    def _draw_empty_message(self) -> None:
        self.canvas.delete("map_message")
        if self.zone_map is None:
            self.canvas.delete("map_raster")
            self.canvas.delete("map_labels")
            fill = "#d7d8cf" if self._map_theme_id() == MAP_THEME_STONE else "#665d4d"
            self.canvas.create_text(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                text="Choose a map pack and load the current zone.",
                fill=fill,
                tags=("map_message",),
            )

    def _rebuild_static(self) -> None:
        self._wall_dirty = True
        self._invalidate_raster()
        self._request_raster_render(0)

    def _apply_static_visibility(self) -> None:
        self._on_wall_options_changed()

    def _on_wall_options_changed(self) -> None:
        self._wall_dirty = True
        self._invalidate_raster()
        self._request_raster_render(0)
        self._draw_map_labels()

    def _on_static_options_changed(self) -> None:
        self._on_wall_options_changed()

    def _on_labels_changed(self) -> None:
        self._draw_map_labels()

'''
s = s[:start] + new_render + s[end:]

# Overlays are clickable non-wall objects.
s = s.replace('tags=("map_content", "eqquest_overlay"),', 'tags=("map_content", "eqquest_overlay", "map_selectable"),')

replace_method('redraw(self) -> None:', '_poll_state(self', r'''    def redraw(self) -> None:
        """Refresh the dual-layer map without rerasterizing for pan/zoom."""
        self._apply_map_background()
        if self.zone_map is None:
            self._draw_empty_message()
            return
        if self._wall_dirty or self._raster_photo is None:
            self._request_raster_render(0)
        else:
            self._refresh_wall_display()
        self._draw_map_labels()
        self._redraw_overlays()
        self._redraw_position()''')

# Follow-player should only move the cached wall; elevation filtering is the only
# location-driven reason to regenerate wall geometry.
s = s.replace('                self._move_view_to(new_x, new_y)\n                self._request_raster_render(250)\n', '                self._move_view_to(new_x, new_y)\n')

path.write_text(s, encoding='utf-8')
print('patched dual-layer map viewer')
