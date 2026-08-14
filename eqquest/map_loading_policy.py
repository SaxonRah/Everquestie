from __future__ import annotations


_MAP_LOADING_POLICY_MARKER = "_everquestie_unified_map_loading_policy"


def install_map_loading_policy() -> None:
    """Make source and packaged Map tabs use one local-map readiness projection.

    ``runtime_policy`` deliberately keeps builder-only controls available in a source
    checkout, but local rendering is a player-facing operation in both modes.  The
    current-zone button therefore must not use a different zone/map resolver merely
    because the knowledge database happens to be writable.

    Install this after :func:`eqquest.runtime_policy.install_runtime_policy`.  The
    wrapper subclasses whatever map-view policy is currently active, preserving
    packaged map-catalog guards and source/developer controls while replacing only the
    current-zone resolution boundary.
    """
    from . import mapview as mapview_module
    from .local_map_readiness import resolve_local_map_readiness

    current_viewer = mapview_module.MapViewerFrame
    if getattr(current_viewer, _MAP_LOADING_POLICY_MARKER, False):
        return

    class UnifiedMapLoadingFrame(current_viewer):
        """Map viewer with identical live-zone/local-file resolution in every mode."""

        def local_map_readiness(self, zone: str):
            root = self.map_root.get().strip()
            bound = self.db.get_meta(mapview_module._binding_key(zone), "")
            return resolve_local_map_readiness(
                self.db,
                zone,
                root,
                bound_stem=bound,
            )

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
