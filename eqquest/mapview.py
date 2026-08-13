from __future__ import annotations

import colorsys
import json
import time
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
MAP_THEME_META = "map_theme"

MAP_THEME_ORIGINAL = "original"
MAP_THEME_STONE = "stone"
MAP_THEME_PARCHMENT = "parchment"
MAP_THEME_LABELS = {
    MAP_THEME_STONE: "Classic EQ Stone",
    MAP_THEME_PARCHMENT: "Parchment",
    MAP_THEME_ORIGINAL: "Original map colors",
}
MAP_THEME_BY_LABEL = {label: key for key, label in MAP_THEME_LABELS.items()}


def _hex_color(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _binding_key(zone_name: str) -> str:
    return MAP_BIND_PREFIX + normalize_map_name(zone_name)


def _mix_rgb(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, amount))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


class MapViewerFrame(ttk.Frame):
    """Native EverQuest vector map viewer with fast persistent canvas objects.

    Native map geometry is constructed only when map content/display options change.
    Pan and zoom operate on existing Tk canvas items, while player/trail/knowledge
    overlays are updated independently. This keeps Good/Brewall maps responsive even
    when a zone contains many thousands of vector records.
    """

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

        stored_map_theme = self.db.get_meta(MAP_THEME_META, MAP_THEME_STONE)
        if stored_map_theme not in MAP_THEME_LABELS:
            stored_map_theme = MAP_THEME_STONE
        self.map_theme = tk.StringVar(value=MAP_THEME_LABELS[stored_map_theme])

        self.zone_map: ZoneMap | None = None
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._fit_pending = False
        self._pan_start: tuple[int, int] | None = None
        self._pending_pan_dx = 0.0
        self._pending_pan_dy = 0.0
        self._pan_job: str | None = None
        self._view_save_job: str | None = None
        self._overlay_entity_by_item: dict[int, int] = {}
        self._last_zone: str | None = None
        self._last_location: tuple[float, float, float] | None = None
        self._last_filter_z: float | None = None
        self._trail: list[tuple[float, float, float]] = []
        self._trail_limit = 250

        # DB-backed overlay data is intentionally cached. Panning/zooming never
        # performs SQLite graph/location queries.
        self._cached_zone: str | None = None
        self._cached_locations: list = []
        self._cached_quest_ids: set[int] = set()
        self._cached_overlay_signature: tuple = ()
        self._next_overlay_refresh = 0.0

        # Theme color conversion is deterministic and reused for every native RGB.
        self._color_cache: dict[tuple[str, int, int, int, bool], str] = {}

        self._build()
        self._apply_map_background()
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

        line1 = ttk.Frame(options)
        line1.pack(fill="x")
        ttk.Label(line1, text="Layers:").pack(side="left")
        for i, name in enumerate(("Base", "1", "2", "3")):
            ttk.Checkbutton(
                line1,
                text=name,
                variable=self.layer_vars[i],
                command=self._apply_static_visibility,
            ).pack(side="left", padx=(4, 0))
        ttk.Checkbutton(
            line1, text="Map labels", variable=self.show_labels, command=self._apply_static_visibility
        ).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(
            line1, text="Knowledge", variable=self.show_knowledge, command=self._redraw_overlays
        ).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(
            line1, text="Tracked quest", variable=self.show_quest, command=self._redraw_overlays
        ).pack(side="left", padx=(8, 0))

        line2 = ttk.Frame(options)
        line2.pack(fill="x", pady=(4, 0))
        ttk.Label(line2, text="Map style:").pack(side="left")
        theme_box = ttk.Combobox(
            line2,
            textvariable=self.map_theme,
            values=list(MAP_THEME_LABELS.values()),
            state="readonly",
            width=19,
        )
        theme_box.pack(side="left", padx=(4, 10))
        theme_box.bind("<<ComboboxSelected>>", self._on_map_theme_changed)
        ttk.Checkbutton(line2, text="Player", variable=self.show_player, command=self._redraw_position).pack(side="left")
        ttk.Checkbutton(line2, text="/loc trail", variable=self.show_trail, command=self._redraw_position).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(line2, text="Follow player", variable=self.follow_player).pack(side="left", padx=(8, 0))
        ttk.Button(line2, text="Clear trail", command=self.clear_trail).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(
            line2, text="Near current Z ±", variable=self.filter_elevation, command=self._on_elevation_changed
        ).pack(side="left", padx=(12, 0))
        span = ttk.Spinbox(
            line2,
            from_=25,
            to=1000,
            increment=25,
            width=6,
            textvariable=self.elevation_span,
            command=self._on_elevation_changed,
        )
        span.pack(side="left", padx=(3, 0))
        span.bind("<Return>", lambda _e: self._on_elevation_changed())
        span.bind("<FocusOut>", lambda _e: self._on_elevation_changed())

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
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at(e.x, e.y, 1 / 1.12))
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
        if p.parent.name.casefold() == "logs":
            maps = p.parent.parent / "maps"
            if maps.is_dir():
                subdirs = [
                    d
                    for d in maps.iterdir()
                    if d.is_dir() and ("good" in d.name.casefold() or "brewall" in d.name.casefold())
                ]
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
        self.canvas.delete("all")
        self._overlay_entity_by_item.clear()
        self.map_file.set(str(self.zone_map.base_path))
        counts = []
        for layer, data in sorted(self.zone_map.layers.items()):
            counts.append(f"L{layer}:{len(data.lines)} lines/{len(data.points)} labels")
        self.map_status.set(f"{self.zone_map.stem} | " + " | ".join(counts))
        self._fit_pending = True
        self._refresh_overlay_cache(force=True)
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
            self._refresh_overlay_cache(force=True)
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

    def _world_to_screen(self, mx: float, my: float) -> tuple[float, float]:
        return self.offset_x + mx * self.scale, self.offset_y + my * self.scale

    def _screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return (sx - self.offset_x) / self.scale, (sy - self.offset_y) / self.scale

    def _view_key(self, zone: str | None = None) -> str | None:
        zone = (zone or self.get_zone() or self.manual_zone.get()).strip()
        if not zone:
            return None
        return MAP_VIEW_PREFIX + normalize_map_name(zone)

    def _save_view(self) -> None:
        self._view_save_job = None
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

    def _schedule_save_view(self, delay_ms: int = 350) -> None:
        if self._view_save_job is not None:
            try:
                self.after_cancel(self._view_save_job)
            except tk.TclError:
                pass
        self._view_save_job = self.after(delay_ms, self._save_view)

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
        self._redraw_position()

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
        self._schedule_save_view(500)

    def center_player(self) -> None:
        loc = self.get_location()
        if not loc:
            self.coord_status.set("No /loc has been observed yet.")
            return
        mx, my, _ = game_to_map(*loc)
        new_x = self.canvas.winfo_width() * 0.5 - mx * self.scale
        new_y = self.canvas.winfo_height() * 0.5 - my * self.scale
        self._move_view_to(new_x, new_y)
        self._schedule_save_view()

    def _on_resize(self, _event) -> None:
        if self._fit_pending:
            self.fit()
        elif self.follow_player.get() and self.zone_map is not None and self.get_location():
            self.center_player()
        elif self.zone_map is None:
            self._draw_empty_message()

    def _pan_begin(self, event) -> None:
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
        self._pending_pan_dx += dx
        self._pending_pan_dy += dy
        self._pan_start = (event.x, event.y)
        if self._pan_job is None:
            # Coalesce high-rate mouse motion into roughly one canvas operation/frame.
            self._pan_job = self.after(8, self._flush_pan)

    def _flush_pan(self) -> None:
        if self._pan_job is not None:
            self._pan_job = None
        dx, dy = self._pending_pan_dx, self._pending_pan_dy
        self._pending_pan_dx = 0.0
        self._pending_pan_dy = 0.0
        if dx or dy:
            self.canvas.move("map_content", dx, dy)

    def _pan_end(self, _event) -> None:
        if self._pan_job is not None:
            try:
                self.after_cancel(self._pan_job)
            except tk.TclError:
                pass
            self._pan_job = None
        self._flush_pan()
        self._pan_start = None
        self._schedule_save_view(180)

    def _wheel(self, event) -> None:
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, sx: float, sy: float, factor: float) -> None:
        if self.zone_map is None:
            return
        old_scale = self.scale
        new_scale = max(0.01, min(50.0, old_scale * factor))
        actual = new_scale / old_scale
        if abs(actual - 1.0) < 1e-9:
            return
        self.scale = new_scale
        self.offset_x = sx + (self.offset_x - sx) * actual
        self.offset_y = sy + (self.offset_y - sy) * actual
        self.canvas.scale("map_content", sx, sy, actual, actual)
        # Font sizes/line widths remain screen-readable; only coordinates scale.
        self._schedule_save_view()

    def _move_view_to(self, new_offset_x: float, new_offset_y: float) -> None:
        dx = new_offset_x - self.offset_x
        dy = new_offset_y - self.offset_y
        self.offset_x = new_offset_x
        self.offset_y = new_offset_y
        if dx or dy:
            self.canvas.move("map_content", dx, dy)

    def _motion(self, event) -> None:
        if self.zone_map is None:
            self.coord_status.set("")
            return
        mx, my = self._screen_to_world(event.x, event.y)
        gx, gy = -mx, -my
        self.coord_status.set(f"Cursor /loc approx: Y {gy:.1f}, X {gx:.1f}")

    def _query_quest_related_ids(self) -> set[int]:
        related: set[int] = set()
        frontier: list[int] = []
        for quest in self.db.tracked_quests():
            qid = int(quest["id"])
            related.add(qid)
            for rel in self.db.relationships_for_entity(qid):
                other = int(
                    rel["target_entity_id"] if rel["direction"] == "out" else rel["source_entity_id"]
                )
                if other not in related:
                    related.add(other)
                    frontier.append(other)
        for eid in frontier:
            for rel in self.db.relationships_for_entity(eid):
                other = int(
                    rel["target_entity_id"] if rel["direction"] == "out" else rel["source_entity_id"]
                )
                related.add(other)
        return related

    def _refresh_overlay_cache(self, *, force: bool = False) -> bool:
        zone = self.get_zone()
        if not zone:
            changed = bool(self._cached_locations or self._cached_quest_ids or self._cached_zone)
            self._cached_zone = None
            self._cached_locations = []
            self._cached_quest_ids = set()
            self._cached_overlay_signature = ()
            return changed

        rows = list(self.db.locations_in_zone(zone))
        quest_ids = self._query_quest_related_ids()
        row_signature = tuple(
            (
                int(row["entity_id"]),
                row["x"],
                row["y"],
                row["z"],
                row["kind"],
                row["name"],
            )
            for row in rows
        )
        signature = (normalize_map_name(zone), tuple(sorted(quest_ids)), row_signature)
        changed = force or signature != self._cached_overlay_signature
        if changed:
            self._cached_zone = zone
            self._cached_locations = rows
            self._cached_quest_ids = quest_ids
            self._cached_overlay_signature = signature
        return changed

    def refresh_overlays(self) -> None:
        """Public hook for quest/knowledge changes without rebuilding map geometry."""
        self._refresh_overlay_cache(force=True)
        self._refresh_marker_list()
        self._redraw_overlays()

    def _refresh_marker_list(self) -> None:
        self.marker_list.delete(0, "end")
        self._marker_ids = []
        for row in self._cached_locations:
            eid = int(row["entity_id"])
            star = "★ " if eid in self._cached_quest_ids else ""
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
            new_x = self.canvas.winfo_width() * 0.5 - mx * self.scale
            new_y = self.canvas.winfo_height() * 0.5 - my * self.scale
            self._move_view_to(new_x, new_y)
            self._schedule_save_view()
            return

    # ------------------------------------------------------------------
    # Map-only visual themes

    def _map_theme_id(self) -> str:
        return MAP_THEME_BY_LABEL.get(self.map_theme.get(), MAP_THEME_STONE)

    def _on_map_theme_changed(self, _event=None) -> None:
        theme_id = self._map_theme_id()
        self.db.set_meta(MAP_THEME_META, theme_id)
        self._color_cache.clear()
        self._apply_map_background()
        self.redraw()

    def _apply_map_background(self) -> None:
        theme_id = self._map_theme_id()
        background = {
            MAP_THEME_ORIGINAL: "#f7f7f7",
            MAP_THEME_STONE: "#2b3542",
            MAP_THEME_PARCHMENT: "#d9cfad",
        }[theme_id]
        self.canvas.configure(background=background)

    def _themed_map_color(self, r: int, g: int, b: int, *, label: bool = False) -> str:
        theme_id = self._map_theme_id()
        key = (theme_id, r, g, b, label)
        cached = self._color_cache.get(key)
        if cached is not None:
            return cached

        if theme_id == MAP_THEME_ORIGINAL:
            if r > 245 and g > 245 and b > 245:
                color = "#666666" if label else "#999999"
            else:
                color = _hex_color(r, g, b)
            self._color_cache[key] = color
            return color

        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        hue, sat, value = colorsys.rgb_to_hsv(rf, gf, bf)

        if theme_id == MAP_THEME_STONE:
            dark = (49, 60, 72)
            light = (220, 221, 207)
            if sat < 0.12:
                rgb = _mix_rgb(dark, light, 0.18 + 0.72 * value)
            else:
                # Preserve source-map semantic hue families while translating them
                # into the EverQuestie gray/blue stone palette.
                if hue < 0.08 or hue >= 0.95:       # red
                    base = (191, 139, 105)           # muted copper
                elif hue < 0.18:                    # orange/yellow
                    base = (201, 181, 119)           # aged gold
                elif hue < 0.45:                    # green
                    base = (122, 151, 137)           # sage
                elif hue < 0.72:                    # cyan/blue
                    base = (118, 145, 173)           # steel blue
                else:                               # violet/magenta
                    base = (150, 137, 166)           # slate violet
                rgb = _mix_rgb(dark, base, 0.35 + 0.58 * value)
            if label:
                rgb = _mix_rgb(rgb, light, 0.12)
        else:
            ink = (68, 57, 42)
            paper = (217, 207, 173)
            if sat < 0.12:
                rgb = _mix_rgb(ink, (118, 100, 72), 0.15 + 0.55 * value)
            else:
                if hue < 0.08 or hue >= 0.95:
                    base = (132, 67, 51)             # rust
                elif hue < 0.18:
                    base = (143, 104, 53)            # ochre
                elif hue < 0.45:
                    base = (93, 105, 66)             # olive
                elif hue < 0.72:
                    base = (70, 91, 104)             # faded ink blue
                else:
                    base = (104, 75, 92)             # plum ink
                rgb = _mix_rgb(ink, base, 0.42 + 0.48 * value)
            if label:
                rgb = _mix_rgb(rgb, ink, 0.10)
            # Keep extremely bright original lines visible against paper.
            if value > 0.94 and sat < 0.08:
                rgb = _mix_rgb(ink, paper, 0.32)

        color = _hex_color(*rgb)
        self._color_cache[key] = color
        return color

    def _overlay_palette(self) -> dict[str, str]:
        theme_id = self._map_theme_id()
        if theme_id == MAP_THEME_STONE:
            return {
                "knowledge": "#6f91b8",
                "quest": "#d0b665",
                "quest_text": "#f0dfa1",
                "outline": "#111820",
                "trail": "#7aa88f",
                "player": "#8ec59f",
                "player_outline": "#294f39",
                "player_text": "#c8ead1",
            }
        if theme_id == MAP_THEME_PARCHMENT:
            return {
                "knowledge": "#536f80",
                "quest": "#a67836",
                "quest_text": "#6c471f",
                "outline": "#403626",
                "trail": "#66754b",
                "player": "#758650",
                "player_outline": "#44502d",
                "player_text": "#44502d",
            }
        return {
            "knowledge": "#1f6feb",
            "quest": "#ffbf00",
            "quest_text": "#7a4b00",
            "outline": "#111111",
            "trail": "#39a85b",
            "player": "#14a44d",
            "player_outline": "#0b5d2a",
            "player_text": "#0b5d2a",
        }

    # ------------------------------------------------------------------
    # Rendering

    def _z_context(self) -> tuple[bool, float, float]:
        if not self.filter_elevation.get():
            return False, 0.0, 0.0
        loc = self.get_location()
        if not loc:
            return False, 0.0, 0.0
        try:
            span = max(1.0, float(self.elevation_span.get()))
        except (ValueError, tk.TclError):
            span = 150.0
        return True, float(loc[2]), span

    @staticmethod
    def _z_visible_for_context(z0: float, z1: float | None, context: tuple[bool, float, float]) -> bool:
        enabled, z, span = context
        if not enabled:
            return True
        if z1 is None:
            return abs(z0 - z) <= span
        lo, hi = sorted((z0, z1))
        return not (hi < z - span or lo > z + span)

    def _on_elevation_changed(self) -> None:
        loc = self.get_location()
        self._last_filter_z = float(loc[2]) if loc and self.filter_elevation.get() else None
        self._rebuild_static()
        self._redraw_overlays()

    def _draw_empty_message(self) -> None:
        self.canvas.delete("map_message")
        if self.zone_map is None:
            fill = "#d7d8cf" if self._map_theme_id() == MAP_THEME_STONE else "#665d4d"
            self.canvas.create_text(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                text="Choose a map pack and load the current zone.",
                fill=fill,
                tags=("map_message",),
            )

    def _rebuild_static(self) -> None:
        self.canvas.delete("map_geometry")
        self.canvas.delete("map_labels")
        self.canvas.delete("map_message")
        if self.zone_map is None:
            self._draw_empty_message()
            return

        z_context = self._z_context()
        for layer_no, layer in self.zone_map.layers.items():
            geometry_tag = f"map_geometry_layer_{layer_no}"
            label_tag = f"map_label_layer_{layer_no}"
            for line in layer.lines:
                if not self._z_visible_for_context(line.z0, line.z1, z_context):
                    continue
                x0, y0 = self._world_to_screen(line.x0, line.y0)
                x1, y1 = self._world_to_screen(line.x1, line.y1)
                self.canvas.create_line(
                    x0,
                    y0,
                    x1,
                    y1,
                    fill=self._themed_map_color(line.r, line.g, line.b),
                    width=1,
                    tags=("map_content", "map_static", "map_geometry", geometry_tag),
                )

            for point in layer.points:
                if not self._z_visible_for_context(point.z, None, z_context):
                    continue
                x, y = self._world_to_screen(point.x, point.y)
                font_size = {1: 8, 2: 10, 3: 12}.get(point.size, 9)
                self.canvas.create_text(
                    x,
                    y,
                    text=point.display_text,
                    fill=self._themed_map_color(point.r, point.g, point.b, label=True),
                    font=("TkDefaultFont", font_size),
                    anchor="center",
                    tags=("map_content", "map_static", "map_labels", label_tag),
                )
        self._apply_static_visibility()

    def _apply_static_visibility(self) -> None:
        for layer_no in range(4):
            enabled = bool(self.layer_vars[layer_no].get())
            self.canvas.itemconfigure(
                f"map_geometry_layer_{layer_no}", state="normal" if enabled else "hidden"
            )
            labels_enabled = enabled and bool(self.show_labels.get())
            self.canvas.itemconfigure(
                f"map_label_layer_{layer_no}", state="normal" if labels_enabled else "hidden"
            )

    def _redraw_overlays(self) -> None:
        self.canvas.delete("eqquest_overlay")
        self._overlay_entity_by_item.clear()
        if self.zone_map is None:
            return
        if not (self.show_knowledge.get() or self.show_quest.get()):
            return

        z_context = self._z_context()
        palette = self._overlay_palette()
        for row in self._cached_locations:
            if row["x"] is None or row["y"] is None:
                continue
            eid = int(row["entity_id"])
            is_quest = eid in self._cached_quest_ids
            if is_quest and not self.show_quest.get():
                continue
            if not is_quest and not self.show_knowledge.get():
                continue
            z = float(row["z"] or 0.0)
            if not self._z_visible_for_context(z, None, z_context):
                continue
            mx, my, _ = game_to_map(float(row["x"]), float(row["y"]), z)
            x, y = self._world_to_screen(mx, my)
            radius = 6 if is_quest else 4
            item = self.canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=palette["quest"] if is_quest else palette["knowledge"],
                outline=palette["outline"],
                width=2,
                tags=("map_content", "eqquest_overlay"),
            )
            self._overlay_entity_by_item[item] = eid
            if is_quest:
                text_item = self.canvas.create_text(
                    x + radius + 3,
                    y,
                    text=row["name"],
                    anchor="w",
                    fill=palette["quest_text"],
                    font=("TkDefaultFont", 9, "bold"),
                    tags=("map_content", "eqquest_overlay"),
                )
                self._overlay_entity_by_item[text_item] = eid

    def _redraw_position(self) -> None:
        self.canvas.delete("eqquest_trail")
        self.canvas.delete("eqquest_player")
        if self.zone_map is None:
            return
        palette = self._overlay_palette()

        if self.show_trail.get() and len(self._trail) >= 2:
            points: list[float] = []
            for loc in self._trail:
                mx, my, _ = game_to_map(*loc)
                sx, sy = self._world_to_screen(mx, my)
                points.extend((sx, sy))
            if len(points) >= 4:
                self.canvas.create_line(
                    *points,
                    fill=palette["trail"],
                    width=2,
                    tags=("map_content", "eqquest_trail"),
                )

        if self.show_player.get():
            loc = self.get_location()
            if loc:
                mx, my, _ = game_to_map(*loc)
                x, y = self._world_to_screen(mx, my)
                size = 8
                self.canvas.create_polygon(
                    x,
                    y - size,
                    x + size,
                    y + size,
                    x,
                    y + size / 2,
                    x - size,
                    y + size,
                    fill=palette["player"],
                    outline=palette["player_outline"],
                    width=2,
                    tags=("map_content", "eqquest_player"),
                )
                self.canvas.create_text(
                    x + 11,
                    y - 10,
                    text="last /loc",
                    anchor="w",
                    fill=palette["player_text"],
                    font=("TkDefaultFont", 9, "bold"),
                    tags=("map_content", "eqquest_player"),
                )

    def redraw(self) -> None:
        """Full rebuild for map/content option changes, never used for pan/zoom."""
        self.canvas.delete("all")
        self._overlay_entity_by_item.clear()
        self._apply_map_background()
        if self.zone_map is None:
            self._draw_empty_message()
            return
        self._rebuild_static()
        self._redraw_overlays()
        self._redraw_position()

    def _poll_state(self) -> None:
        zone = self.get_zone()
        loc = self.get_location()
        if zone != self._last_zone:
            self._last_zone = zone
            self._trail.clear()
            self._last_location = None
            self._last_filter_z = None
            self._refresh_overlay_cache(force=True)
            self._refresh_marker_list()
            if zone:
                self.manual_zone.set(zone)
            if zone and self.map_root.get().strip():
                self.load_current_zone()
            elif self.zone_map is not None:
                self._redraw_overlays()

        if loc != self._last_location:
            self._last_location = loc
            self._append_trail_location(loc)
            if self.follow_player.get() and loc and self.zone_map is not None:
                mx, my, _ = game_to_map(*loc)
                new_x = self.canvas.winfo_width() * 0.5 - mx * self.scale
                new_y = self.canvas.winfo_height() * 0.5 - my * self.scale
                self._move_view_to(new_x, new_y)

            # Normal /loc updates touch only the small trail/player objects. The
            # native map is rebuilt for movement only when elevation filtering is
            # explicitly enabled and the current Z actually changes.
            if self.filter_elevation.get() and loc:
                z = float(loc[2])
                if self._last_filter_z is None or z != self._last_filter_z:
                    self._last_filter_z = z
                    self._rebuild_static()
                    self._redraw_overlays()
            self._redraw_position()

        now = time.monotonic()
        if now >= self._next_overlay_refresh:
            self._next_overlay_refresh = now + 2.0
            if self._refresh_overlay_cache():
                self._refresh_marker_list()
                self._redraw_overlays()

        self.after(250, self._poll_state)
