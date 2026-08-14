from __future__ import annotations


_MAP_LOADING_POLICY_MARKER = "_everquestie_unified_map_loading_policy"


def _canvas_ready_for_initial_fit(canvas) -> bool:
    """Return True only when Tk has given the map canvas real visible dimensions."""
    try:
        if not bool(canvas.winfo_ismapped()):
            return False
        return int(canvas.winfo_width()) > 1 and int(canvas.winfo_height()) > 1
    except Exception:
        return False


def install_map_loading_policy() -> None:
    """Unify player-facing map loading in source and packaged runtimes.

    ``runtime_policy`` deliberately keeps builder-only controls available in a source
    checkout, but local rendering is a player-facing operation in both modes.  Current
    zone resolution and first presentation therefore must not differ merely because
    the knowledge database happens to be writable.

    Install this after :func:`eqquest.runtime_policy.install_runtime_policy`.  The
    wrapper subclasses whatever map-view policy is currently active, preserving
    packaged map-catalog guards and source/developer controls while replacing only the
    current-zone resolution and first-fit boundaries.
    """
    from . import mapview as mapview_module
    from .local_map_readiness import resolve_local_map_readiness

    current_viewer = mapview_module.MapViewerFrame
    if getattr(current_viewer, _MAP_LOADING_POLICY_MARKER, False):
        return

    class UnifiedMapLoadingFrame(current_viewer):
        """Map viewer with identical live-zone resolution and first display in every mode."""

        def local_map_readiness(self, zone: str):
            root = self.map_root.get().strip()
            bound = self.db.get_meta(mapview_module._binding_key(zone), "")
            return resolve_local_map_readiness(
                self.db,
                zone,
                root,
                bound_stem=bound,
            )

        def _restore_view(self) -> bool:
            """A freshly loaded map always starts fitted instead of restoring stale camera state.

            The previous implementation restored a persisted pan/zoom before falling back
            to Fit.  Auto-loaded maps can be loaded while the Notebook Map tab is hidden,
            so that saved transform could become the first visible presentation even when
            the wall image was still being installed.  A new map should instead first be
            shown in full; user pan/zoom state can be saved again after that presentation.
            """
            return False

        def fit(self) -> None:
            """Fit only after the canvas is actually mapped at its visible size.

            During startup/log-driven auto-load the Map tab may still be hidden and Tk can
            report placeholder dimensions.  Keep ``_fit_pending`` set so the first real
            ``<Configure>`` event performs the fit once the tab is visible.
            """
            if self.zone_map is None:
                return
            if not _canvas_ready_for_initial_fit(self.canvas):
                self._fit_pending = True
                return
            return super().fit()

        def load_current_zone(self) -> None:
            zone = self.get_zone()
            if not zone:
                self.map_status.set("Current zone is not known from the log yet.")
                return

            readiness = self.local_map_readiness(zone)
            if not readiness.ready or readiness.path is None:
                if readiness.status == "root_unavailable":
                    self.map_status.set("Choose a map pack folder first.")
                elif readiness.status == "zone_ambiguous":
                    self.map_status.set(
                        f"Canonical zone identity is ambiguous for {zone}; EverQuestie will not guess a local map."
                    )
                elif readiness.status == "map_ambiguous":
                    choose_variant = getattr(self, "choose_local_map_variant", None)
                    if callable(choose_variant) and choose_variant():
                        return
                    choices = ", ".join(path.name for path in readiness.candidates[:6])
                    self.map_status.set(
                        f"Multiple canonical maps remain present for {zone}: {choices}. "
                        "No local variant was bound."
                    )
                else:
                    self.map_status.set(
                        f"No unique local map-file match for {zone}. "
                        "Open the correct .txt once, then press Bind zone."
                    )
                self._refresh_overlay_cache(force=True)
                self._refresh_marker_list()
                return

            self.load_map(readiness.path)
            self._base_map_status = f"{self._base_map_status} | {readiness.reason}"
            self.map_status.set(self._base_map_status)

    setattr(UnifiedMapLoadingFrame, _MAP_LOADING_POLICY_MARKER, True)
    mapview_module.MapViewerFrame = UnifiedMapLoadingFrame

    # runtime_policy imports app.py after installing its map-view subclass.  app.py
    # keeps the class in a module global, so update that binding too before _build_ui
    # constructs the actual Map tab.
    try:
        from . import app as app_module
    except Exception:
        return
    app_module.MapViewerFrame = UnifiedMapLoadingFrame
