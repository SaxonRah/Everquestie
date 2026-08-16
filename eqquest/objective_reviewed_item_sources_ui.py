from __future__ import annotations

from .objective_reviewed_item_sources import (
    augment_objective_with_reviewed_item_sources,
    quest_objective_navigation_with_reviewed_sources,
)


_OBJECTIVE_REVIEWED_ITEM_SOURCES_MARKER = "_everquestie_objective_reviewed_item_sources_ui"


def install_objective_reviewed_item_sources_ui() -> None:
    """Bind one reviewed-source objective policy to every current objective UI owner."""
    from . import app as app_module
    from . import zone_opportunities_ui as zone_opportunities_module

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

    # Zone Opportunities imports the raw projector directly because it operates on an
    # explicitly selected untracked step rather than the packaged tracked-quest tree.
    # Bind that module-level dependency to the same public reviewed-source navigator so
    # Map objective and Navigate objective cannot disagree about exact loot-item sources.
    zone_opportunities_module.tracked_quest_objective_navigation = (
        quest_objective_navigation_with_reviewed_sources
    )

    setattr(current_app, _OBJECTIVE_REVIEWED_ITEM_SOURCES_MARKER, True)
