from __future__ import annotations

from pathlib import Path


_RUNTIME_MODE_UI_MARKER = "_everquestie_runtime_mode_ui"


def database_mode_text(db) -> str:
    """Return an unmistakable description of the active EverQuestie DB boundary."""
    if not getattr(db, "knowledge_writable", True):
        knowledge = Path(getattr(db, "knowledge_path", getattr(db, "path", "")))
        state = Path(getattr(db, "state_path", ""))
        return (
            "Database mode: PACKAGED / IMMUTABLE"
            f"   |   Knowledge: {knowledge}"
            f"   |   User state: {state}"
        )
    path = Path(getattr(db, "path", ""))
    return f"Database mode: BUILDER / MUTABLE   |   Database: {path}"


def install_runtime_mode_ui() -> None:
    """Add a persistent database-role banner after all runtime UI policies are installed."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    current_build_ui = current_app._build_ui
    if getattr(current_build_ui, _RUNTIME_MODE_UI_MARKER, False):
        return

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

        mode = "PACKAGED/IMMUTABLE" if not getattr(self.db, "knowledge_writable", True) else "BUILDER/MUTABLE"
        try:
            self.title(f"{self.title()} — {mode}")
        except Exception:
            pass

    setattr(_build_ui, _RUNTIME_MODE_UI_MARKER, True)
    current_app._build_ui = _build_ui
