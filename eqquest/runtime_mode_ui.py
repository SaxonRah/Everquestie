from __future__ import annotations

from pathlib import Path


_RUNTIME_MODE_UI_MARKER = "_everquestie_runtime_mode_ui"
_RUNTIME_PROFILE_REFRESH_MARKER = "_everquestie_runtime_profile_refresh"


def _server_profile_label(db) -> str:
    """Return the persisted global server profile without making diagnostics fragile."""
    try:
        from .world_profiles import active_world_profile_id, world_profile

        return world_profile(active_world_profile_id(db)).label
    except Exception:
        return "not reported"


def database_mode_text(db) -> str:
    """Return an unmistakable description of DB boundary plus active server context."""
    profile = _server_profile_label(db)
    if not getattr(db, "knowledge_writable", True):
        knowledge = Path(getattr(db, "knowledge_path", getattr(db, "path", "")))
        state = Path(getattr(db, "state_path", ""))
        return (
            "Database mode: PACKAGED / IMMUTABLE"
            f"   |   Server: {profile}"
            f"   |   Knowledge: {knowledge}"
            f"   |   User state: {state}"
        )
    path = Path(getattr(db, "path", ""))
    return (
        "Database mode: BUILDER / MUTABLE"
        f"   |   Server: {profile}"
        f"   |   Database: {path}"
    )


def install_runtime_mode_ui() -> None:
    """Add persistent database-role/server-context diagnostics after UI policies."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    current_build_ui = current_app._build_ui
    if not getattr(current_build_ui, _RUNTIME_MODE_UI_MARKER, False):
        def _build_ui(self) -> None:
            current_build_ui(self)

            from tkinter import ttk

            text = database_mode_text(self.db)
            banner = ttk.Frame(self, padding=(8, 3, 8, 3), style="Stone.TFrame")
            label = ttk.Label(banner, text=text, anchor="w")
            label.pack(fill="x")
            try:
                banner.pack(fill="x", padx=8, pady=(0, 4), before=self.notebook)
            except Exception:
                banner.pack(fill="x", padx=8, pady=(0, 4))
            self.database_mode_banner = banner
            self.database_mode_label = label

            mode = (
                "PACKAGED/IMMUTABLE"
                if not getattr(self.db, "knowledge_writable", True)
                else "BUILDER/MUTABLE"
            )
            try:
                self.title(f"{self.title()} — {mode}")
            except Exception:
                pass

        setattr(_build_ui, _RUNTIME_MODE_UI_MARKER, True)
        current_app._build_ui = _build_ui

    # The global Server selector is installed before this diagnostics layer. Decorate
    # its application-level callback so the persistent banner always reflects the
    # profile that actually owns Travel/Knowledge/quest availability.
    current_changed = getattr(current_app, "_world_profile_changed", None)
    if current_changed is None or getattr(current_changed, _RUNTIME_PROFILE_REFRESH_MARKER, False):
        return

    def _world_profile_changed(self, event=None) -> None:
        current_changed(self, event)
        label = getattr(self, "database_mode_label", None)
        if label is None:
            return
        try:
            label.configure(text=database_mode_text(self.db))
        except Exception:
            pass

    setattr(_world_profile_changed, _RUNTIME_PROFILE_REFRESH_MARKER, True)
    current_app._world_profile_changed = _world_profile_changed
