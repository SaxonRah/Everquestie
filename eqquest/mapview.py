from __future__ import annotations

import json
import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .db import Database
from .knowledge import entity_detail_text, relation_label
from .local_search import map_label_terms, parse_local_query, resolve_local_hits, search_local_hits
from .map_search import MapLabelHit, find_map_label_hits
from .map_catalog import MapCatalog, MapCatalogHit
from .mapraster import (
    RasterRequest,
    RasterResult,
    map_background_rgb,
    render_map_raster,
    themed_map_rgb,
)
from .eqmap import (
    ZoneMap,
    discover_base_maps,
    game_to_map,
    map_to_game,
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

# The wall image is cached at high resolution and zoomed in Tk. These levels
# keep zoom predictable and allow exact rational image scaling without
# rerasterizing native EQ geometry on wheel events.
MAP_ZOOM_LEVELS = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 2.50, 3.00, 4.00)


def _hex_color(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _binding_key(zone_name: str) -> str:
    return MAP_BIND_PREFIX + normalize_map_name(zone_name)


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
        on_knowledge_search: Callable[[str], None] | None = None,
    ):
        super().__init__(master, padding=8)
        self.db = db
        self.get_zone = get_zone
        self.get_location = get_location
        self.set_zone_callback = set_zone
        self.on_entity = on_entity
        self.on_knowledge_search = on_knowledge_search
        self.map_catalog = MapCatalog(db)

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

        # Dual-layer map model. Native EQ line geometry becomes one cached, full-map
        # wall image. Pan/zoom never walks map lines again. Text/locations stay as
        # independent Canvas objects so they remain selectable and database-aware.
        self._base_map_status = ""
        self._raster_photo: tk.PhotoImage | None = None          # high-res wall source
        self._display_photo: tk.PhotoImage | None = None         # current zoom cache entry
        self._display_image_item: int | None = None
        # Exact vector-derived wall images keyed by discrete map zoom level.
        # Wheel zoom only swaps one cached PhotoImage; it never rescales it.
        self._wall_exact_photos: dict[float, tk.PhotoImage] = {}
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
        self._lookup_map_hit_by_item: dict[str, MapLabelHit | MapCatalogHit] = {}
        self._lookup_selected_entity: int | None = None
        self._lookup_selected_map_hit: MapLabelHit | MapCatalogHit | None = None
        self._catalog_index_results: queue.Queue[tuple[str, object]] = queue.Queue()
        self._catalog_indexing = False
        self.catalog_progress_var = tk.DoubleVar(value=0.0)
        self.catalog_progress_text = tk.StringVar(value="Map catalog idle")

        self._build()
        self._apply_map_background()
        self.after(30, self._poll_raster_results)
        self.after(250, self._poll_state)
        self.after(300, self._poll_catalog_index_results)

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
                command=self._on_wall_options_changed,
            ).pack(side="left", padx=(4, 0))
        ttk.Checkbutton(
            line1, text="Map labels", variable=self.show_labels, command=self._on_labels_changed
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
        self.index_maps_button = ttk.Button(lookup_row, text="Index maps", command=self.index_map_catalog)
        self.index_maps_button.grid(row=0, column=2, padx=(4, 0))

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
        ttk.Button(lookup_actions, text="Open Map", command=self._open_lookup_on_map).pack(side="left", padx=(5, 0))
        self.catalog_progress = ttk.Progressbar(
            lookup_actions, variable=self.catalog_progress_var, maximum=1.0, length=135, mode="determinate"
        )
        self.catalog_progress.pack(side="right", padx=(6, 0))
        ttk.Label(lookup_actions, textvariable=self.catalog_progress_text).pack(side="right", padx=(6, 0))
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
        self.map_status.set(f"Map pack: {Path(root).name} | {count} base map files | catalog refresh is manual")

    def ensure_map_catalog(self) -> None:
        root = self.map_root.get().strip()
        if not root or not Path(root).is_dir() or self._catalog_indexing:
            return
        self.index_map_catalog()

    def index_map_catalog(self) -> None:
        root = self.map_root.get().strip()
        if not root or not Path(root).is_dir():
            self.lookup_status.set("Choose a valid map pack before indexing.")
            return
        if self._catalog_indexing:
            return
        self._catalog_indexing = True
        self.index_maps_button.configure(state="disabled")
        self.catalog_progress.configure(maximum=1.0)
        self.catalog_progress_var.set(0.0)
        self.catalog_progress_text.set("Starting map index…")
        self.lookup_status.set("Manually refreshing the EverQuestie map catalog…")
        db_path = self.db.path

        def worker() -> None:
            thread_db = None
            try:
                thread_db = Database(db_path)

                def progress(stage: str, current: int, total: int, detail: str) -> None:
                    self._catalog_index_results.put(("progress", (stage, current, total, detail)))

                stats = MapCatalog(thread_db).index_root(
                    root, source_name=Path(root).name, progress=progress
                )
                self._catalog_index_results.put(("ok", stats))
            except Exception as exc:
                self._catalog_index_results.put(("error", str(exc)))
            finally:
                if thread_db is not None:
                    thread_db.close()

        threading.Thread(target=worker, name="EverQuestieMapCatalog", daemon=True).start()


    def _poll_catalog_index_results(self) -> None:
        try:
            while True:
                status, payload = self._catalog_index_results.get_nowait()
                if status == "progress":
                    stage, current, total, detail = payload
                    total = max(1, int(total))
                    current = max(0, min(int(current), total))
                    self.catalog_progress.configure(maximum=float(total))
                    self.catalog_progress_var.set(float(current))
                    label = {
                        "scan": "Scanning",
                        "index": "Indexing",
                        "reconcile": "Linking",
                        "done": "Ready",
                    }.get(str(stage), "Working")
                    self.catalog_progress_text.set(f"{label} {current:,}/{total:,}")
                    self.lookup_status.set(str(detail))
                    continue

                self._catalog_indexing = False
                self.index_maps_button.configure(state="normal")
                if status == "ok":
                    stats = payload
                    self.catalog_progress.configure(maximum=1.0)
                    self.catalog_progress_var.set(1.0)
                    self.catalog_progress_text.set("Map catalog ready")
                    self.lookup_status.set(
                        f"Map catalog: {stats.labels:,} labels | {stats.linked:,} linked | {stats.ambiguous:,} ambiguous"
                    )
                else:
                    self.catalog_progress.configure(maximum=1.0)
                    self.catalog_progress_var.set(0.0)
                    self.catalog_progress_text.set("Map catalog failed")
                    self.lookup_status.set(f"Map catalog index failed: {payload}")
        except queue.Empty:
            pass
        self.after(150, self._poll_catalog_index_results)

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
        self._map_label_text_by_item.clear()
        self._raster_photo = None
        self._display_photo = None
        self._display_image_item = None
        self._wall_exact_photos.clear()
        self._wall_dirty = True
        self.map_file.set(str(self.zone_map.base_path))
        self._invalidate_raster()
        counts = []
        for layer, data in sorted(self.zone_map.layers.items()):
            counts.append(f"L{layer}:{len(data.lines)} lines/{len(data.points)} labels")
        self._base_map_status = f"{self.zone_map.stem} | " + " | ".join(counts)
        self.map_status.set(self._base_map_status)
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
        elif self.zone_map is not None:
            # Resize the cached wall presentation only. Native map lines are not
            # rerasterized merely because the window changed size.
            self._refresh_wall_display()
            self._draw_map_labels()
            self._redraw_overlays()
            self._redraw_position()
        else:
            self._draw_empty_message()

    def _pan_begin(self, event) -> None:
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
        self._marker_names = []
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
            self._marker_names.append(str(row["name"]))

    def _marker_selected(self, _event) -> None:
        sel = self.marker_list.curselection()
        if not sel:
            return
        index = int(sel[0])
        eid = self._marker_ids[index]
        name = self._marker_names[index] if index < len(self._marker_names) else ""
        self._center_entity(eid)
        self._lookup_name(name, preferred_entity_id=eid)

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

    @staticmethod
    def _map_lookup_terms(term: str) -> list[str]:
        return map_label_terms(term)

    def _lookup_candidates(self, term: str, preferred_entity_id: int | None = None):
        query = parse_local_query(term)
        structured = bool(query.kinds or query.zone or query.source or query.exact)
        if structured:
            return search_local_hits(
                self.db,
                term,
                current_zone=self.get_zone(),
                limit=40,
            )
        return resolve_local_hits(
            self.db,
            term,
            current_zone=self.get_zone(),
            preferred_entity_id=preferred_entity_id,
            limit=40,
        )

    def map_label_matches(self, term: str, *, limit: int = 40) -> list[MapLabelHit]:
        return find_map_label_hits(
            self.zone_map,
            term,
            current_zone=self.get_zone() or self.manual_zone.get().strip() or None,
            enabled_layers=self._enabled_layers(),
            limit=limit,
        )

    def _map_label_detail_text(self, hit: MapLabelHit | MapCatalogHit) -> str:
        gx, gy, gz = map_to_game(hit.x, hit.y, hit.z)
        if isinstance(hit, MapCatalogHit):
            zone = hit.zone_name or hit.map_stem
            lines = [
                f"[map label] {hit.text}",
                f"Zone/map: {zone}",
                f"Map stem: {hit.map_stem}",
                f"Layer: {hit.layer}",
                f"EQ /loc: Y {gy:.1f}, X {gx:.1f}, Z {gz:.1f}",
                f"Map catalog source: {hit.source_name}"
                + (f" {hit.source_version}" if hit.source_version else ""),
                f"Map file key: {hit.source_key or Path(hit.path).name}",
                f"Map source line: {hit.source_line}",
                f"Catalog link: {hit.link_status}" + (f" — {hit.link_reason}" if hit.link_reason else ""),
            ]
            if hit.linked_entity_id is not None:
                entity = self.db.entity(hit.linked_entity_id)
                if entity is not None:
                    lines += ["", f"Linked local entity: [{entity['kind']}] {entity['name']}"]
            else:
                lines += [
                    "",
                    "Map catalog evidence only — no normalized EverQuestie knowledge entity is linked yet.",
                    "The map label remains unclassified; EverQuestie will not guess NPC/item/quest semantics.",
                ]
            return "\n".join(lines)

        zone = self.get_zone() or self.manual_zone.get().strip() or (self.zone_map.stem if self.zone_map else "unknown")
        layer_path = None
        if self.zone_map is not None and hit.layer in self.zone_map.layers:
            layer_path = self.zone_map.layers[hit.layer].path.name
        lines = [
            f"[map label] {hit.text}",
            f"Zone: {zone}",
            f"Layer: {hit.layer}",
            f"EQ /loc: Y {gy:.1f}, X {gx:.1f}, Z {gz:.1f}",
        ]
        if layer_path:
            lines.append(f"Map file: {layer_path}")
        if hit.source_line:
            lines.append(f"Map source line: {hit.source_line}")
        lines += [
            "",
            "Local map evidence only — no normalized EverQuestie knowledge entity matches this label yet.",
            "The map file does not encode whether this name is an NPC, quest, merchant, item, or another POI, so EverQuestie will not invent a type.",
        ]
        return "\n".join(lines)

    def map_label_search_summary(self, term: str, *, limit: int = 20) -> list[str]:
        lines: list[str] = []
        catalog_hits = self.map_catalog.search(term, current_zone=self.get_zone(), limit=limit)
        if catalog_hits:
            for hit in catalog_hits:
                gx, gy, gz = map_to_game(hit.x, hit.y, hit.z)
                zone = hit.zone_name or hit.map_stem
                linked = f" | linked entity {hit.linked_entity_id}" if hit.linked_entity_id is not None else ""
                lines.append(
                    f"[map label] {hit.text} | {zone} | layer {hit.layer} | "
                    f"/loc Y {gy:.1f}, X {gx:.1f}, Z {gz:.1f} | {hit.reason}{linked}"
                )
            return lines
        for hit in self.map_label_matches(term, limit=limit):
            gx, gy, gz = map_to_game(hit.x, hit.y, hit.z)
            lines.append(
                f"[map label] {hit.text} | current map layer {hit.layer} | "
                f"/loc Y {gy:.1f}, X {gx:.1f}, Z {gz:.1f} | {hit.reason}"
            )
        return lines

    def _lookup_name(self, term: str, preferred_entity_id: int | None = None) -> None:
        term = " ".join((term or "").replace("_", " ").split()).strip()
        if not term:
            return
        self.lookup_query.set(term)
        hits = self._lookup_candidates(term, preferred_entity_id)
        self.lookup_tree.delete(*self.lookup_tree.get_children())
        self._lookup_entity_by_item.clear()
        self._lookup_map_hit_by_item.clear()
        self._lookup_selected_entity = None
        self._lookup_selected_map_hit = None
        if not hits:
            catalog_hits = self.map_catalog.search(term, current_zone=self.get_zone(), limit=40)
            if catalog_hits:
                for index, hit in enumerate(catalog_hits):
                    iid = f"catalog:{hit.label_id}:{index}"
                    kind = "map label"
                    if hit.linked_entity_id is not None:
                        linked = self.db.entity(hit.linked_entity_id)
                        if linked is not None:
                            kind = f"map→{linked['kind']}"
                    self.lookup_tree.insert("", "end", iid=iid, text=hit.text, values=(kind, hit.reason))
                    self._lookup_map_hit_by_item[iid] = hit
                first = self.lookup_tree.get_children()[0]
                self.lookup_tree.selection_set(first)
                self.lookup_tree.focus(first)
                self.lookup_tree.see(first)
                self._lookup_selected_map_hit = self._lookup_map_hit_by_item[first]
                self.lookup_status.set(
                    f"{len(catalog_hits)} global map evidence match" + ("es" if len(catalog_hits) != 1 else "")
                )
                self._set_lookup_detail(self._map_label_detail_text(self._lookup_selected_map_hit))
                return
            map_hits = self.map_label_matches(term, limit=20)
            if map_hits:
                for index, hit in enumerate(map_hits):
                    iid = f"maplabel:{index}"
                    self.lookup_tree.insert("", "end", iid=iid, text=hit.text, values=("map label", hit.reason))
                    self._lookup_map_hit_by_item[iid] = hit
                first = self.lookup_tree.get_children()[0]
                self.lookup_tree.selection_set(first)
                self.lookup_tree.focus(first)
                self.lookup_tree.see(first)
                self._lookup_selected_map_hit = self._lookup_map_hit_by_item[first]
                self.lookup_status.set(
                    f"No normalized DB entity; {len(map_hits)} current-map label candidate" +
                    ("s" if len(map_hits) != 1 else "")
                )
                self._set_lookup_detail(self._map_label_detail_text(self._lookup_selected_map_hit))
                return
            self.lookup_status.set("No local DB or indexed/current-map label match")
            self._set_lookup_detail(f"No local EverQuestie knowledge or map evidence matches: {term}")
            return
        for hit in hits:
            row = hit.row
            item = self.lookup_tree.insert("", "end", text=row["name"], values=(row["kind"], hit.reason))
            self._lookup_entity_by_item[item] = int(row["id"])
        first = self.lookup_tree.get_children()[0]
        self.lookup_tree.selection_set(first)
        self.lookup_tree.focus(first)
        self.lookup_tree.see(first)
        self._show_entity_info(self._lookup_entity_by_item[first], tree_item=first)
        self.lookup_status.set(f"{len(hits)} ranked local match" + ("es" if len(hits) != 1 else ""))

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
        self._lookup_selected_map_hit = None
        relationships = list(self.db.relationships_for_entity(entity_id))
        self._set_lookup_detail(entity_detail_text(self.db, entity_id, include_source_text=False))

        if tree_item is not None and not self.lookup_tree.get_children(tree_item):
            for rel in relationships[:250]:
                if rel["direction"] == "out":
                    other_id = int(rel["target_entity_id"])
                    other_kind = str(rel["target_kind"])
                    other_name = str(rel["target_name"])
                    relation = relation_label(str(rel["relation"])) + " →"
                else:
                    other_id = int(rel["source_entity_id"])
                    other_kind = str(rel["source_kind"])
                    other_name = str(rel["source_name"])
                    relation = "← " + relation_label(str(rel["relation"]))
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
        map_hit = self._lookup_map_hit_by_item.get(item)
        if map_hit is not None:
            self._lookup_selected_entity = None
            self._lookup_selected_map_hit = map_hit
            self._set_lookup_detail(self._map_label_detail_text(map_hit))
            return
        entity_id = self._lookup_entity_by_item.get(item)
        if entity_id is None:
            return
        self._show_entity_info(entity_id, tree_item=item)

    def _open_lookup_in_knowledge(self, _event=None) -> None:
        if self._lookup_selected_entity is not None and self.on_entity:
            self.on_entity(self._lookup_selected_entity)
            return
        if isinstance(self._lookup_selected_map_hit, MapCatalogHit):
            if self._lookup_selected_map_hit.linked_entity_id is not None and self.on_entity:
                self.on_entity(self._lookup_selected_map_hit.linked_entity_id)
                return
        term = ""
        if self._lookup_selected_map_hit is not None:
            term = self._lookup_selected_map_hit.text
        else:
            term = self.lookup_query.get().strip()
        if term and self.on_knowledge_search:
            self.on_knowledge_search(term)

    def _center_map_point(self, x: float, y: float) -> None:
        new_x = self.canvas.winfo_width() * 0.5 - float(x) * self.scale
        new_y = self.canvas.winfo_height() * 0.5 - float(y) * self.scale
        self._move_view_to(new_x, new_y)
        self._schedule_save_view()

    def _catalog_hit_local_path(self, hit: MapCatalogHit) -> Path | None:
        root = self.map_root.get().strip()
        if root and hit.source_key:
            candidate = Path(root) / Path(hit.source_key)
            if candidate.is_file():
                return candidate
        legacy = Path(hit.path)
        if legacy.is_file():
            return legacy
        if root:
            filename = f"{hit.map_stem}.txt" if hit.layer == 0 else f"{hit.map_stem}_{hit.layer}.txt"
            candidate = Path(root) / filename
            if candidate.is_file():
                return candidate
        return None

    def _open_lookup_on_map(self, _event=None) -> None:
        hit = self._lookup_selected_map_hit
        if isinstance(hit, MapCatalogHit):
            local_path = self._catalog_hit_local_path(hit)
            if local_path is None:
                self.lookup_status.set(
                    f"Catalog hit found for {hit.text}, but that map file is not present in the selected local map pack."
                )
                return
            self.load_map(local_path)
            self.after(80, lambda: self._center_map_point(hit.x, hit.y))
            self.lookup_status.set(f"Opened {hit.zone_name or hit.map_stem} at {hit.text}")
            return
        if isinstance(hit, MapLabelHit):
            self._center_map_point(hit.x, hit.y)
            return
        if self._lookup_selected_entity is not None:
            map_hits = self.map_catalog.hits_for_entity(self._lookup_selected_entity, limit=20)
            if map_hits:
                chosen = map_hits[0]
                current = normalize_map_name(self.get_zone() or "")
                for candidate in map_hits:
                    if current and current in {
                        normalize_map_name(candidate.zone_name), normalize_map_name(candidate.map_stem)
                    }:
                        chosen = candidate
                        break
                self.load_map(chosen.path)
                self.after(80, lambda: self._center_map_point(chosen.x, chosen.y))
                self.lookup_status.set(f"Opened linked map evidence for {chosen.text}")
                return
            self.focus_entity(self._lookup_selected_entity)

    # ------------------------------------------------------------------
    # Map-only visual themes

    # ------------------------------------------------------------------
    # Map-only visual themes

    def _map_theme_id(self) -> str:
        return MAP_THEME_BY_LABEL.get(self.map_theme.get(), MAP_THEME_STONE)

    def _on_map_theme_changed(self, _event=None) -> None:
        theme_id = self._map_theme_id()
        self.db.set_meta(MAP_THEME_META, theme_id)
        self._color_cache.clear()
        self._apply_map_background()
        self._wall_dirty = True
        self._invalidate_raster()
        self.redraw()

    def _apply_map_background(self) -> None:
        r, g, b = map_background_rgb(self._map_theme_id())
        self.canvas.configure(background=_hex_color(r, g, b))

    def _themed_map_color(self, r: int, g: int, b: int, *, label: bool = False) -> str:
        theme_id = self._map_theme_id()
        key = (theme_id, r, g, b, label)
        cached = self._color_cache.get(key)
        if cached is not None:
            return cached
        rgb = themed_map_rgb(theme_id, r, g, b, label=label)
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

    def _calculate_fit_transform(self) -> tuple[float, float, float] | None:
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
            line_width=factor,
            exact_levels=tuple((level, level / factor) for level in MAP_ZOOM_LEVELS),
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
        self._wall_exact_photos = {float(factor): photo}
        for zoom_level, zoom_ppm in result.exact_rasters:
            level = float(zoom_level)
            if abs(level - float(factor)) < 1e-12:
                continue
            try:
                self._wall_exact_photos[level] = tk.PhotoImage(data=zoom_ppm, format="PPM")
            except tk.TclError:
                continue
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
                f"{result.source_lines:,} source lines | {len(self._wall_exact_photos)} exact zoom images"
            )

    def _scaled_wall_photo(self) -> tk.PhotoImage | None:
        """Return the exact vector-derived image for the current discrete zoom."""
        if not self._wall_exact_photos:
            return self._raster_photo
        current_level = self.scale / max(self._wall_fit_scale, 1e-9)
        level = min(self._wall_exact_photos, key=lambda value: abs(value - current_level))
        return self._wall_exact_photos[level]

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
                tags=("map_content", "eqquest_overlay", "map_selectable"),
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
                    tags=("map_content", "eqquest_overlay", "map_selectable"),
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
