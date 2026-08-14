from __future__ import annotations

import json
from pathlib import Path


_MAP_POLICY_MARKER = "_everquestie_shipped_catalog_policy"
_APP_POLICY_MARKER = "_everquestie_packaged_app_policy"


def _same_canonical_zone(db, left: str | None, right: str | None) -> bool:
    """Compare runtime zone tokens without weakening canonical ambiguity rules."""
    left_text = " ".join(str(left or "").split()).strip()
    right_text = " ".join(str(right or "").split()).strip()
    if not left_text or not right_text:
        return False
    from .zone_identity import resolve_zone

    left_resolution = resolve_zone(db, left_text)
    right_resolution = resolve_zone(db, right_text)
    if left_resolution.identity is not None and right_resolution.identity is not None:
        return left_resolution.entity_id == right_resolution.entity_id
    # Exact raw equality is safe as a fallback for an incomplete old snapshot; never
    # use substring/fuzzy matching here because this guards map coordinate ownership.
    return left_text.casefold() == right_text.casefold()


def _draw_runtime_navigation_target(viewer) -> None:
    """Draw one transient game-space navigation target on the currently loaded map."""
    viewer.canvas.delete("eqquest_navigation_target")
    target = getattr(viewer, "_navigation_target", None)
    if target is None or viewer.zone_map is None:
        return
    zone, game_x, game_y, game_z, label = target
    if not _same_canonical_zone(viewer.db, viewer.get_zone(), zone):
        return

    from .eqmap import game_to_map

    mx, my, _ = game_to_map(float(game_x), float(game_y), float(game_z or 0.0))
    sx, sy = viewer._world_to_screen(mx, my)
    radius = 10
    color = "#ffd24a"
    viewer.canvas.create_oval(
        sx - radius,
        sy - radius,
        sx + radius,
        sy + radius,
        outline=color,
        width=3,
        tags=("map_content", "eqquest_navigation_target"),
    )
    viewer.canvas.create_line(
        sx - radius - 4,
        sy,
        sx + radius + 4,
        sy,
        fill=color,
        width=2,
        tags=("map_content", "eqquest_navigation_target"),
    )
    viewer.canvas.create_line(
        sx,
        sy - radius - 4,
        sx,
        sy + radius + 4,
        fill=color,
        width=2,
        tags=("map_content", "eqquest_navigation_target"),
    )
    viewer.canvas.create_text(
        sx + radius + 7,
        sy - radius - 2,
        text=str(label or "Navigation target"),
        anchor="sw",
        fill=color,
        font=("TkDefaultFont", 9, "bold"),
        tags=("map_content", "eqquest_navigation_target"),
    )


def _focus_runtime_navigation_target(
    viewer,
    zone: str,
    x: float,
    y: float,
    z: float | None,
    label: str,
) -> bool:
    """Center a loaded local map on one normalized EQ game-space coordinate."""
    viewer._navigation_target = (
        str(zone),
        float(x),
        float(y),
        (float(z) if z is not None else None),
        str(label or "Navigation target"),
    )
    if not _same_canonical_zone(viewer.db, viewer.get_zone(), zone):
        viewer.coord_status.set("Navigation target belongs to a different current zone.")
        return False
    if viewer.zone_map is None:
        viewer.coord_status.set("Navigation target is known, but no local map is loaded for this zone.")
        return False

    from .eqmap import game_to_map

    mx, my, _ = game_to_map(float(x), float(y), float(z or 0.0))
    viewer._center_map_point(mx, my)
    _draw_runtime_navigation_target(viewer)
    z_text = f" Z={float(z):g}" if z is not None else ""
    viewer.coord_status.set(
        f"Target: {label} | /loc Y={float(y):g} X={float(x):g}{z_text}"
    )
    return True


def install_runtime_policy() -> None:
    """Install packaged-runtime guards before the application UI is launched.

    Source checkouts/builders retain explicit import, MCP, map-catalog and FTS build
    surfaces. Packaged runtime consumes immutable shipped knowledge plus writable user
    state; it must never expose a path that recompiles the knowledge DB on the player's
    machine.
    """
    from .map_catalog import MapCatalog
    from .map_resolution import resolve_catalog_map_for_zone
    from . import mapview as mapview_module

    if not getattr(MapCatalog.index_root, _MAP_POLICY_MARKER, False):
        original_ensure_schema = MapCatalog.ensure_schema
        original_index_root = MapCatalog.index_root

        def ensure_schema(self):
            if getattr(self.db, "knowledge_writable", True):
                return original_ensure_schema(self)
            return None

        def index_root(self, *args, **kwargs):
            if not getattr(self.db, "knowledge_writable", True):
                raise RuntimeError(
                    "Map catalog construction is builder-only; packaged EverQuestie "
                    "uses the shipped knowledge catalog."
                )
            return original_index_root(self, *args, **kwargs)

        # runtime._install_runtime_adapters() recognizes this marker on ensure_schema
        # and therefore will not replace the policy when runtime.main() starts.
        ensure_schema._everquestie_runtime_adapter = True  # type: ignore[attr-defined]
        setattr(index_root, _MAP_POLICY_MARKER, True)
        MapCatalog.ensure_schema = ensure_schema
        MapCatalog.index_root = index_root

    original_viewer = mapview_module.MapViewerFrame
    if not getattr(original_viewer, _MAP_POLICY_MARKER, False):
        class RuntimePolicyMapViewerFrame(original_viewer):
            """Map viewer that consumes, but never compiles, packaged catalog knowledge."""

            def __init__(self, *args, **kwargs):
                self._navigation_target = None
                super().__init__(*args, **kwargs)

            def _packaged_runtime(self) -> bool:
                return not getattr(self.db, "knowledge_writable", True)

            def _build(self) -> None:
                super()._build()
                if self._packaged_runtime():
                    self.index_maps_button.configure(text="Shipped catalog", state="disabled")
                    self.catalog_progress.configure(maximum=1.0)
                    self.catalog_progress_var.set(1.0)
                    self.catalog_progress_text.set("Shipped catalog")

            def set_map_root(self, folder: str | Path) -> None:
                super().set_map_root(folder)
                if self._packaged_runtime():
                    self.map_status.set(
                        f"Map pack: {Path(folder).name} | using shipped EverQuestie catalog"
                    )

            def ensure_map_catalog(self) -> None:
                if self._packaged_runtime():
                    return
                return super().ensure_map_catalog()

            def index_map_catalog(self) -> None:
                if self._packaged_runtime():
                    self.lookup_status.set(
                        "The global map catalog is shipped with EverQuestie; rebuilding it is builder-only."
                    )
                    return
                return super().index_map_catalog()

            def _redraw_position(self) -> None:
                super()._redraw_position()
                _draw_runtime_navigation_target(self)

            def focus_navigation_target(
                self,
                zone: str,
                x: float,
                y: float,
                z: float | None,
                label: str,
            ) -> bool:
                return _focus_runtime_navigation_target(self, zone, x, y, z, label)

            def clear_navigation_target(self) -> None:
                self._navigation_target = None
                self.canvas.delete("eqquest_navigation_target")

            def load_current_zone(self) -> None:
                if not self._packaged_runtime():
                    return super().load_current_zone()

                zone = self.get_zone()
                root = self.map_root.get().strip()
                if not zone:
                    self.map_status.set("Current zone is not known from the log yet.")
                    return
                if not root or not Path(root).is_dir():
                    self.map_status.set("Choose a map pack folder first.")
                    return

                bound = self.db.get_meta(mapview_module._binding_key(zone), "")
                hinted = None
                zone_row, _ = self.db.resolve_entity(zone, "zone")
                if zone_row is not None:
                    try:
                        data = json.loads(zone_row["data_json"] or "{}")
                    except Exception:
                        data = {}
                    hinted = data.get("map_short_name") or data.get("short_name")

                resolved = resolve_catalog_map_for_zone(
                    self.db,
                    zone,
                    root,
                    bound_stem=bound,
                    hinted_stem=hinted,
                )
                if resolved.path is None:
                    if resolved.candidates:
                        choices = ", ".join(path.name for path in resolved.candidates[:6])
                        self.map_status.set(
                            f"Multiple canonical maps are present for {zone}: {choices}. "
                            "Open the intended map once and press Bind zone."
                        )
                    else:
                        self.map_status.set(
                            f"No unique local map-file match for {zone}. "
                            "Open the correct .txt once, then press Bind zone."
                        )
                    self._refresh_overlay_cache(force=True)
                    self._refresh_marker_list()
                    return

                self.load_map(resolved.path)
                self._base_map_status = f"{self._base_map_status} | {resolved.reason}"
                self.map_status.set(self._base_map_status)

        setattr(RuntimePolicyMapViewerFrame, _MAP_POLICY_MARKER, True)
        mapview_module.MapViewerFrame = RuntimePolicyMapViewerFrame

    # Import app only after the map-view patch so app.py binds the guarded viewer.
    from . import app as app_module
    from .locations import where_text as unified_where_text
    from .mechanics_context_ui import MechanicsContextFrame
    from .route_guidance_ui import RouteGuidanceFrame as TravelFrame

    # The application historically imported knowledge.where_text directly. Route the
    # live WHERE command through the unified evidence projection so confirmed map POIs
    # and provider/importer locations are both visible without mutating either source.
    app_module.where_text = unified_where_text
    # The packaged Mechanics tab consumes the same canonical class/level projection as
    # other runtime callers. Builder/source-checkout UI retains its legacy raw-table
    # browser, while normal users never need to understand client numeric IDs/tables.
    app_module.MechanicsFrame = MechanicsContextFrame

    original_app = app_module.EverQuestieApp
    if getattr(original_app, _APP_POLICY_MARKER, False):
        return

    class RuntimePolicyEverQuestieApp(original_app):
        """Normal-user UI over immutable shipped knowledge and writable player state."""

        def _packaged_runtime(self) -> bool:
            return not getattr(self.db, "knowledge_writable", True)

        def _focus_navigation_map_target(
            self,
            zone: str,
            x: float,
            y: float,
            z: float | None,
            label: str,
        ) -> None:
            # Targets emitted by Travel are constrained to the live current zone. Check
            # again at the ownership boundary in case the player zoned between clicks.
            if not _same_canonical_zone(self.db, self.state_model.current_zone, zone):
                self.status.set("Navigation target expired because the current zone changed.")
                return
            self.notebook.select(self.map_tab)
            self.map_view.load_current_zone()
            if self.map_view.focus_navigation_target(zone, x, y, z, label):
                self.status.set(f"Map focused on {label}.")
            else:
                self.status.set(
                    "Navigation coordinate is known, but the matching local map could not be focused."
                )

        def _build_ui(self) -> None:
            super()._build_ui()

            self.travel_tab = TravelFrame(
                self.notebook,
                db=self.db,
                get_zone=lambda: self.state_model.current_zone,
                get_location=lambda: self.state_model.last_location,
                on_map_target=self._focus_navigation_map_target,
            )
            # Live, Map, Travel, Knowledge, Mechanics keeps navigation-oriented
            # information close to the player's current location.
            self.notebook.insert(2, self.travel_tab, text="Travel")

            if not self._packaged_runtime():
                return

            # Importers, MCP compilation/search and mirror management are builder /
            # developer infrastructure. The normal packaged application consumes the
            # shipped knowledge snapshot and therefore does not expose those surfaces.
            self.notebook.hide(self.import_tab)
            self.notebook.hide(self.search_tab)

            # FTS is finalized into the release snapshot. Rebuilding it would mutate
            # immutable packaged knowledge and is therefore not a user operation.
            self.database_rebuild_button.configure(
                text="Shipped search index",
                state="disabled",
            )

        def _rebuild_search_index(self) -> None:
            if self._packaged_runtime():
                self.status.set(
                    "The search index is finalized in the shipped knowledge snapshot and is read-only."
                )
                return
            return super()._rebuild_search_index()

        def _database_diagnostic_text(self) -> str:
            text = super()._database_diagnostic_text()
            if not self._packaged_runtime():
                return text
            diagnostics = self.db.database_diagnostics()
            state_path = str(diagnostics.get("state_path") or "")
            role = (
                "Packaged storage:\n"
                f"  Knowledge: {diagnostics.get('path', self.db.path)} (read-only / immutable)\n"
                f"  User state: {state_path or 'not reported'} (writable)\n\n"
            )
            return role + text

    setattr(RuntimePolicyEverQuestieApp, _APP_POLICY_MARKER, True)
    app_module.EverQuestieApp = RuntimePolicyEverQuestieApp
