from __future__ import annotations

import json
from pathlib import Path


_MAP_POLICY_MARKER = "_everquestie_shipped_catalog_policy"
_APP_POLICY_MARKER = "_everquestie_packaged_app_policy"


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
    from .travel import TravelFrame

    # The application historically imported knowledge.where_text directly. Route the
    # live WHERE command through the unified evidence projection so confirmed map POIs
    # and provider/importer locations are both visible without mutating either source.
    app_module.where_text = unified_where_text

    original_app = app_module.EverQuestieApp
    if getattr(original_app, _APP_POLICY_MARKER, False):
        return

    class RuntimePolicyEverQuestieApp(original_app):
        """Normal-user UI over immutable shipped knowledge and writable player state."""

        def _packaged_runtime(self) -> bool:
            return not getattr(self.db, "knowledge_writable", True)

        def _build_ui(self) -> None:
            super()._build_ui()

            self.travel_tab = TravelFrame(
                self.notebook,
                db=self.db,
                get_zone=lambda: self.state_model.current_zone,
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