from __future__ import annotations

import json
import math
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .db import Database
from .eqmap import (
    ZoneMap,
    discover_base_maps,
    game_to_map,
    load_zone_map,
    normalize_map_name,
    resolve_map_for_zone,
)


MAP_ROOT_META = "map_root"
MAP_BIND_PREFIX = "map_binding::"
MAP_VIEW_PREFIX = "map_view::"


def _hex_color(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _binding_key(zone_name: str) -> str:
    return MAP_BIND_PREFIX + normalize_map_name(zone_name)


class MapViewerFrame(ttk.Frame):
    """Native EverQuest vector map viewer with EverQuestie knowledge overlays."""

    def __init__(
        self,
        master,
        *,
        db: Database,
        get_zone: Callable[[], str | None],
        get_location: Callable[[], tuple[float, float, float] | None],
        set_zone: Callable[[str], None] | None = None,
        on_entity: Callable[[int], None] | None = None,
    ):
        super().__init__(master, padding=8)
        self.db = db
        self.get_zone = get_zone
        self.get_location = get_location
        self.set_zone_callback = set_zone
        self.on_entity = on_entity

        self.map_root = tk.StringVar(value=self.db.get_meta(MAP_ROOT_META, ""))
        self.manual_zone = tk.StringVar()
        self.map_file = tk.StringVar()
        self.map_status = tk.StringVar(value="Choose a Brewall/Good/EverQuest map folder.")
        self.coord_status = tk.StringVar(value="")
        self.layer_vars = {i: tk.BooleanVar(value=True) for i in range(4)}
        self.show_labels = tk.BooleanVar(value=True)
        self.show_player = tk.BooleanVar(value=True)
        self.show_trail = tk.BooleanVar(value=True)
        self.follow_player = tk.BooleanVar(value=False)
        self.show_knowledge = tk.BooleanVar(value=True)
        self.show_quest = tk.BooleanVar(value=True)
        self.filter_elevation = tk.BooleanVar(value=False)
        self.elevation_span = tk.DoubleVar(value=150.0)

        self.zone_map: ZoneMap | None = None
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._fit_pending = False
        self._pan_start: tuple[int, int] | None = None
        self._overlay_entity_by_item: dict[int, int] = {}
        self._last_zone: str | None = None
        self._last_location: tuple[float, float, float] | None = None
        self._trail: list[tuple[float, float, float]] = []
        self._trail_limit = 250

        self._build()
        self.after(250, self._poll_state)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        zone_row = ttk.Frame(self)
        zone_row.grid(row=0, column=0, sticky="ew")
        zone_row.columnconfigure(1, weight=1)
        ttk.Label(zone_row, text="Zone:").grid(row=0, column=0, sticky="w")
        zone_entry = ttk.Entry(zone_row, textvariable=self.manual_zone)
        zone_entry.grid(row=0, column=1, sticky="ew", padx=6)
        zone_entry.bind("<Return>", lambda _e: self.set_manual_zone())
        ttk.Button(zone_row, text="Set zone", command=self.set_manual_zone).grid(row=0, column=2)
        ttk.Label(zone_row, text="(or /g Zone: <name>)").grid(row=0, column=3, sticky="w", padx=(8, 0))

        row = ttk.Frame(self)
        row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        row.columnconfigure(1, weight=1)
        ttk.Label(row, text="Map pack:").grid(row=0, column=0, sticky="w")
        ttk.Entry(row, textvariable=self.map_root).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(row, text="Browse…", command=self.choose_map_root).grid(row=0, column=2)
        ttk.Button(row, text="Current zone", command=self.load_current_zone).grid(row=0, column=3, padx=(6, 0))
        ttk.Button(row, text="Open map…", command=self.choose_map_file).grid(row=0, column=4, padx=(6, 0))
        ttk.Button(row, text="Bind zone", command=self.bind_current_zone).grid(row=0, column=5, padx=(6, 0))
        ttk.Button(row, text="Fit", command=self.fit).grid(row=0, column=6, padx=(6, 0))
        ttk.Button(row, text="Player", command=self.center_player).grid(row=0, column=7, padx=(6, 0))

        options = ttk.Frame(self)
        options.grid(row=2, column=0, sticky="ew", pady=(6, 6))
        ttk.Label(options, text="Layers:").pack(side="left")
        for i, name in enumerate(("Base", "1", "2", "3")):
            ttk.Checkbutton(options, text=name, variable=self.layer_vars[i], command=self.redraw).pack(side="left", padx=(4, 0))
        ttk.Checkbutton(options, text="Map labels", variable=self.show_labels, command=self.redraw).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(options, text="Player", variable=self.show_player, command=self.redraw).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(options, text="/loc trail", variable=self.show_trail, command=self.redraw).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(options, text="Follow player", variable=self.follow_player).pack(side="left", padx=(8, 0))
        ttk.Button(options, text="Clear trail", command=self.clear_trail).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(options, text="Knowledge", variable=self.show_knowledge, command=self.redraw).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(options, text="Tracked quest", variable=self.show_quest, command=self.redraw).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(options, text="Near current Z ±", variable=self.filter_elevation, command=self.redraw).pack(side="left", padx=(12, 0))
        span = ttk.Spinbox(options, from_=25, to=1000, increment=25, width=6, textvariable=self.elevation_span, command=self.redraw)
        span.pack(side="left", padx=(3, 0))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.grid(row=3, column=0, sticky="nsew")

        canvas_frame = ttk.Frame(body)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        body.add(canvas_frame, weight=4)

        self.canvas = tk.Canvas(canvas_frame, background="#f7f7f7", highlightthickness=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<ButtonPress-1>", self._pan_begin)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-1>", self._pan_end)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_at(e.x, e.y, 1.12))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1/1.12))
        self.canvas.bind("<Motion>", self._motion)

        side = ttk.Frame(body, padding=(8, 0, 0, 0))
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

    def set_manual_zone(self) -> None:
        zone = self.manual_zone.get().strip()
        if not zone:
            return
        if self.set_zone_callback is not None:
            self.set_zone_callback(zone)
        self.load_current_zone()

    def choose_map_root(self) -> None:
        initial = self.map_root.get().strip() or None
        folder = filedialog.askdirectory(title="Choose Brewall/Good/EverQuest map pack", initialdir=initial)
        if not folder:
            return
        self.set_map_root(folder)
        self.load_current_zone()

    def set_map_root(self, folder: str | Path) -> None:
        root = str(Path(folder))
        self.map_root.set(root)
        self.db.set_meta(MAP_ROOT_META, root)
        count = len(discover_base_maps(root))
        self.map_status.set(f"Map pack: {Path(root).name} | {count} base map files")

    def suggest_root_from_log(self, log_path: str | Path) -> None:
        """Infer EverQuest/maps from an eqlog path, without overriding a chosen pack."""
        if self.map_root.get().strip():
            return
        p = Path(log_path)
        # .../EverQuest/Logs/eqlog_x.txt -> .../EverQuest/maps
        if p.parent.name.casefold() == "logs":
            maps = p.parent.parent / "maps"
            if maps.is_dir():
                # Prefer known custom map subdirectories if exactly one is obvious.
                subdirs = [d for d in maps.iterdir() if d.is_dir() and ("good" in d.name.casefold() or "brewall" in d.name.casefold())]
                if len(subdirs) == 1:
                    self.set_map_root(subdirs[0])
                else:
                    self.set_map_root(maps)

    def choose_map_file(self) -> None:
        root = self.map_root.get().strip() or None
        path = filedialog.askopenfilename(
            title="Choose EverQuest map file",
            initialdir=root,
            filetypes=[("EverQuest map", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.load_map(path)

    def load_map(self, path: str | Path) -> None:
        try:
            self.zone_map = load_zone_map(path)
        except Exception as exc:
            messagebox.showerror("Map load failed", str(exc))
            return
        self.map_file.set(str(self.zone_map.base_path))
        counts = []
        for layer, data in sorted(self.zone_map.layers.items()):
            counts.append(f"L{layer}:{len(data.lines)} lines/{len(data.points)} labels")
        self.map_status.set(f"{self.zone_map.stem} | " + " | ".join(counts))
        self._fit_pending = True
        self._refresh_marker_list()
        self.after_idle(lambda: None if self._restore_view() else self.fit())

    def load_current_zone(self) -> None:
        zone = self.get_zone()
        root = self.map_root.get().strip()
        if not zone:
            self.map_status.set("Current zone is not known from the log yet.")
            return
        if not root or not Path(root).is_dir():
            self.map_status.set("Choose a map pack folder first.")
            return

        bound = self.db.get_meta(_binding_key(zone), "")
        hinted = None
        zone_row, _ = self.db.resolve_entity(zone, "zone")
        if zone_row is not None:
            try:
                data = json.loads(zone_row["data_json"] or "{}")
            except Exception:
                data = {}
            hinted = data.get("map_short_name") or data.get("short_name")

        path = resolve_map_for_zone(zone, root, bound_stem=bound, hinted_stem=hinted)
        if path is None:
            self.map_status.set(
                f"No unique map-file match for {zone}. Open the correct .txt once, then press Bind zone."
            )
            self._refresh_marker_list()
            return
        self.load_map(path)

    def bind_current_zone(self) -> None:
        zone = self.get_zone()
        if not zone or self.zone_map is None:
            self.map_status.set("Load a map while the current zone is known before binding it.")
            return
        self.db.set_meta(_binding_key(zone), self.zone_map.stem)
        self.map_status.set(f"Bound {zone} -> {self.zone_map.stem}.txt")

    def _enabled_layers(self) -> list[int]:
        return [i for i, var in self.layer_vars.items() if var.get()]

    def _z_visible(self, z0: float, z1: float | None = None) -> bool:
        if not self.filter_elevation.get():
            return True
        loc = self.get_location()
        if not loc:
            return True
        z = loc[2]
        span = max(1.0, float(self.elevation_span.get()))
        if z1 is None:
            return abs(z0 - z) <= span
        lo, hi = sorted((z0, z1))
        return not (hi < z - span or lo > z + span)

    def _world_to_screen(self, mx: float, my: float) -> tuple[float, float]:
        # Match the EverQuest in-game map orientation: native map Y increases
        # downward on screen, so we do not invert the vertical axis here.
        return self.offset_x + mx * self.scale, self.offset_y + my * self.scale

    def _screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.offset_x) / self.scale, (sy - self.offset_y) / self.scale

    def _view_key(self, zone: str | None = None) -> str | None:
        zone = (zone or self.get_zone() or self.manual_zone.get()).strip()
        if not zone:
            return None
        return MAP_VIEW_PREFIX + normalize_map_name(zone)

    def _save_view(self) -> None:
        if self.zone_map is None or self.follow_player.get():
            return
        key = self._view_key()
        if not key:
            return
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        center_x, center_y = self._screen_to_world(w * 0.5, h * 0.5)
        self.db.set_meta(
            key,
            json.dumps({"scale": self.scale, "center_x": center_x, "center_y": center_y}),
        )

    def _restore_view(self) -> bool:
        key = self._view_key()
        if not key:
            return False
        raw = self.db.get_meta(key, "")
        if not raw:
            return False
        try:
            data = json.loads(raw)
            scale = float(data["scale"])
            center_x = float(data["center_x"])
            center_y = float(data["center_y"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False
        self.scale = max(0.01, min(50.0, scale))
        w = max(100, self.canvas.winfo_width())
        h = max(100, self.canvas.winfo_height())
        self.offset_x = w * 0.5 - center_x * self.scale
        self.offset_y = h * 0.5 - center_y * self.scale
        self._fit_pending = False
        self.redraw()
        return True

    def clear_trail(self) -> None:
        self._trail.clear()
        loc = self.get_location()
        if loc:
            self._trail.append(loc)
        self.redraw()

    def _append_trail_location(self, loc: tuple[float, float, float] | None) -> None:
        if loc is None:
            return
        if self._trail and self._trail[-1] == loc:
            return
        self._trail.append(loc)
        if len(self._trail) > self._trail_limit:
            del self._trail[: len(self._trail) - self._trail_limit]

    def fit(self) -> None:
        if self.zone_map is None:
            return
        bounds = self.zone_map.bounds(self._enabled_layers())
        if bounds is None:
            return
        minx, miny, maxx, maxy = bounds
        w = max(100, self.canvas.winfo_width())
        h = max(100, self.canvas.winfo_height())
        pad = 30
        dx = max(1.0, maxx - minx)
        dy = max(1.0, maxy - miny)
        self.scale = min((w - 2 * pad) / dx, (h - 2 * pad) / dy)
        cx = (minx + maxx) * 0.5
        cy = (miny + maxy) * 0.5
        self.offset_x = w * 0.5 - cx * self.scale
        self.offset_y = h * 0.5 - cy * self.scale
        self._fit_pending = False
        self.redraw()

    def center_player(self) -> None:
        loc = self.get_location()
        if not loc:
            self.coord_status.set("No /loc has been observed yet.")
            return
        mx, my, _ = game_to_map(*loc)
        self.offset_x = self.canvas.winfo_width() * 0.5 - mx * self.scale
        self.offset_y = self.canvas.winfo_height() * 0.5 - my * self.scale
        self.redraw()

    def _on_resize(self, _event) -> None:
        if self._fit_pending:
            self.fit()
        else:
            self.redraw()

    def _pan_begin(self, event) -> None:
        # Entity overlay click wins over map panning.
        item = self.canvas.find_withtag("current")
        if item and item[0] in self._overlay_entity_by_item:
            entity_id = self._overlay_entity_by_item[item[0]]
            if self.on_entity:
                self.on_entity(entity_id)
            self._center_entity(entity_id)
            return
        self._pan_start = (event.x, event.y)

    def _pan_move(self, event) -> None:
        if self._pan_start is None:
            return
        dx = event.x - self._pan_start[0]
        dy = event.y - self._pan_start[1]
        self.offset_x += dx
        self.offset_y += dy
        self._pan_start = (event.x, event.y)
        self.redraw()

    def _pan_end(self, _event) -> None:
        self._pan_start = None
        self._save_view()

    def _wheel(self, event) -> None:
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, sx: float, sy: float, factor: float) -> None:
        if self.zone_map is None:
            return
        wx, wy = self._screen_to_world(sx, sy)
        self.scale = max(0.01, min(50.0, self.scale * factor))
        self.offset_x = sx - wx * self.scale
        self.offset_y = sy - wy * self.scale
        self.redraw()
        self._save_view()

    def _motion(self, event) -> None:
        if self.zone_map is None:
            self.coord_status.set("")
            return
        mx, my = self._screen_to_world(event.x, event.y)
        gx, gy, _ = (-mx, -my, 0.0)
        self.coord_status.set(f"Cursor /loc approx: Y {gy:.1f}, X {gx:.1f}")

    def _quest_related_ids(self) -> set[int]:
        related: set[int] = set()
        frontier: list[int] = []
        for quest in self.db.tracked_quests():
            qid = int(quest["id"])
            related.add(qid)
            for rel in self.db.relationships_for_entity(qid):
                other = int(rel["target_entity_id"] if rel["direction"] == "out" else rel["source_entity_id"])
                if other not in related:
                    related.add(other)
                    frontier.append(other)
        # One extra hop catches quest item -> drops_from NPC and similar useful edges.
        for eid in frontier:
            for rel in self.db.relationships_for_entity(eid):
                other = int(rel["target_entity_id"] if rel["direction"] == "out" else rel["source_entity_id"])
                related.add(other)
        return related

    def _locations_here(self):
        zone = self.get_zone()
        if not zone:
            return []
        return list(self.db.locations_in_zone(zone))

    def _refresh_marker_list(self) -> None:
        rows = self._locations_here()
        self.marker_list.delete(0, "end")
        self._marker_ids = []
        quest_ids = self._quest_related_ids()
        for row in rows:
            eid = int(row["entity_id"])
            star = "★ " if eid in quest_ids else ""
            coords = []
            if row["y"] is not None:
                coords.append(f"Y {row['y']:g}")
            if row["x"] is not None:
                coords.append(f"X {row['x']:g}")
            self.marker_list.insert("end", f"{star}[{row['kind']}] {row['name']}  {' '.join(coords)}")
            self._marker_ids.append(eid)

    def _marker_selected(self, _event) -> None:
        sel = self.marker_list.curselection()
        if not sel:
            return
        eid = self._marker_ids[int(sel[0])]
        self._center_entity(eid)
        if self.on_entity:
            self.on_entity(eid)

    def focus_entity(self, entity_id: int) -> None:
        """Center the best known location for an entity without changing source data."""
        self._center_entity(entity_id)

    def _center_entity(self, entity_id: int) -> None:
        zone = self.get_zone()
        if not zone:
            return
        for row in self.db.locations_for_entity(entity_id):
            if row["zone_name"] and row["zone_name"].casefold() != zone.casefold():
                continue
            if row["x"] is None or row["y"] is None:
                continue
            mx, my, _ = game_to_map(float(row["x"]), float(row["y"]), float(row["z"] or 0.0))
            self.offset_x = self.canvas.winfo_width() * 0.5 - mx * self.scale
            self.offset_y = self.canvas.winfo_height() * 0.5 - my * self.scale
            self.redraw()
            return

    def redraw(self) -> None:
        self.canvas.delete("all")
        self._overlay_entity_by_item.clear()
        if self.zone_map is None:
            self.canvas.create_text(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                text="Choose a map pack and load the current zone.",
                fill="#666666",
            )
            return

        # Native map geometry/labels.
        for layer_no in self._enabled_layers():
            layer = self.zone_map.layers.get(layer_no)
            if not layer:
                continue
            for line in layer.lines:
                if not self._z_visible(line.z0, line.z1):
                    continue
                x0, y0 = self._world_to_screen(line.x0, line.y0)
                x1, y1 = self._world_to_screen(line.x1, line.y1)
                color = _hex_color(line.r, line.g, line.b)
                # Pure white community-map strokes vanish on our light canvas.
                if line.r > 245 and line.g > 245 and line.b > 245:
                    color = "#999999"
                self.canvas.create_line(x0, y0, x1, y1, fill=color, width=1)

            if self.show_labels.get():
                for point in layer.points:
                    if not self._z_visible(point.z):
                        continue
                    x, y = self._world_to_screen(point.x, point.y)
                    color = _hex_color(point.r, point.g, point.b)
                    if point.r > 245 and point.g > 245 and point.b > 245:
                        color = "#666666"
                    font_size = {1: 8, 2: 10, 3: 12}.get(point.size, 9)
                    self.canvas.create_text(x, y, text=point.display_text, fill=color, font=("TkDefaultFont", font_size), anchor="center")

        # EverQuestie knowledge overlays use game /loc coordinates -> native map coordinates.
        quest_ids = self._quest_related_ids()
        rows = self._locations_here() if self.show_knowledge.get() or self.show_quest.get() else []
        for row in rows:
            if row["x"] is None or row["y"] is None:
                continue
            eid = int(row["entity_id"])
            is_quest = eid in quest_ids
            if is_quest and not self.show_quest.get():
                continue
            if not is_quest and not self.show_knowledge.get():
                continue
            z = float(row["z"] or 0.0)
            if not self._z_visible(z):
                continue
            mx, my, _ = game_to_map(float(row["x"]), float(row["y"]), z)
            x, y = self._world_to_screen(mx, my)
            radius = 6 if is_quest else 4
            fill = "#ffbf00" if is_quest else "#1f6feb"
            outline = "#111111"
            item = self.canvas.create_oval(x-radius, y-radius, x+radius, y+radius, fill=fill, outline=outline, width=2, tags=("eqquest_overlay",))
            self._overlay_entity_by_item[item] = eid
            if is_quest:
                text_item = self.canvas.create_text(x + radius + 3, y, text=row["name"], anchor="w", fill="#7a4b00", font=("TkDefaultFont", 9, "bold"), tags=("eqquest_overlay",))
                self._overlay_entity_by_item[text_item] = eid

        # Successive /loc observations form a historical trail.  No interpolation
        # is attempted: these are only positions actually emitted by the EQ log.
        if self.show_trail.get() and len(self._trail) >= 2:
            points: list[float] = []
            for loc in self._trail:
                mx, my, _ = game_to_map(*loc)
                sx, sy = self._world_to_screen(mx, my)
                points.extend((sx, sy))
            if len(points) >= 4:
                self.canvas.create_line(*points, fill="#39a85b", width=2, tags=("eqquest_trail",))

        # Last observed /loc. This is intentionally described as last-known rather
        # than continuous position: EverQuestie never reads game memory.
        if self.show_player.get():
            loc = self.get_location()
            if loc:
                mx, my, _ = game_to_map(*loc)
                x, y = self._world_to_screen(mx, my)
                size = 8
                player = self.canvas.create_polygon(
                    x, y-size,
                    x+size, y+size,
                    x, y+size/2,
                    x-size, y+size,
                    fill="#14a44d", outline="#0b5d2a", width=2,
                )
                self.canvas.create_text(x + 11, y - 10, text="last /loc", anchor="w", fill="#0b5d2a", font=("TkDefaultFont", 9, "bold"))

    def _poll_state(self) -> None:
        zone = self.get_zone()
        loc = self.get_location()
        if zone != self._last_zone:
            self._last_zone = zone
            self._trail.clear()
            self._last_location = None
            self._refresh_marker_list()
            if zone:
                self.manual_zone.set(zone)
            if zone and self.map_root.get().strip():
                self.load_current_zone()
        if loc != self._last_location:
            self._last_location = loc
            self._append_trail_location(loc)
            if self.follow_player.get() and loc and self.zone_map is not None:
                mx, my, _ = game_to_map(*loc)
                self.offset_x = self.canvas.winfo_width() * 0.5 - mx * self.scale
                self.offset_y = self.canvas.winfo_height() * 0.5 - my * self.scale
            self.redraw()
        self.after(250, self._poll_state)
