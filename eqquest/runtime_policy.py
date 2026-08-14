from __future__ import annotations

from pathlib import Path


_MAP_POLICY_MARKER = "_everquestie_shipped_catalog_policy"


def install_runtime_policy() -> None:
    """Install release-runtime guards before the application UI is imported.

    Source checkouts and builders still use writable :class:`Database` instances and
    retain explicit catalog-building tools. Packaged runtime uses RuntimeDatabase,
    where knowledge_writable=False; in that lifecycle catalog construction must never
    happen on the player's machine.
    """
    from .map_catalog import MapCatalog
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
    if getattr(original_viewer, _MAP_POLICY_MARKER, False):
        return

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

    setattr(RuntimePolicyMapViewerFrame, _MAP_POLICY_MARKER, True)
    mapview_module.MapViewerFrame = RuntimePolicyMapViewerFrame
