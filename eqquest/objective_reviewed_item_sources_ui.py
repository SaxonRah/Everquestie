from __future__ import annotations

from .objective_reviewed_item_sources import augment_objective_with_reviewed_item_sources


_OBJECTIVE_REVIEWED_ITEM_SOURCES_MARKER = "_everquestie_objective_reviewed_item_sources_ui"


def install_objective_reviewed_item_sources_ui() -> None:
    """Augment packaged tracked-objective navigation without replacing its owner."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _OBJECTIVE_REVIEWED_ITEM_SOURCES_MARKER, False):
        return

    current_selected_navigation = current_app._selected_objective_navigation

    def _selected_objective_navigation(self):
        base = current_selected_navigation(self)
        if base is None:
            return None
        return augment_objective_with_reviewed_item_sources(
            self.db,
            base,
            getattr(self.state_model, "current_zone", None),
        )

    current_app._selected_objective_navigation = _selected_objective_navigation
    setattr(current_app, _OBJECTIVE_REVIEWED_ITEM_SOURCES_MARKER, True)
