from __future__ import annotations


_PROFILE_AVAILABILITY_UI_MARKER = "_everquestie_profile_availability_ui"


def install_profile_availability_ui() -> None:
    """Project the global gameplay profile into Knowledge and tracked-quest guidance."""
    from . import app as app_module
    from .profile_availability import (
        ProfileAwareQuestEngine,
        profiled_entity_detail_text,
    )

    # app.py imported these names directly. Rebinding its runtime globals keeps the
    # legacy/source UI builder intact while making normal entity detail and the quest
    # engine consume the same selected gameplay profile as Travel.
    app_module.entity_detail_text = profiled_entity_detail_text
    app_module.QuestEngine = ProfileAwareQuestEngine

    # world_profile_ui owns the selector. Decorate its change callback so one global
    # selection immediately refreshes other already-built player surfaces as well.
    from . import route_guidance_ui as travel_ui

    current = travel_ui.RouteGuidanceFrame
    current_changed = getattr(current, "_world_profile_changed", None)
    if current_changed is None or getattr(current_changed, _PROFILE_AVAILABILITY_UI_MARKER, False):
        return

    def _world_profile_changed(self, event=None) -> None:
        current_changed(self, event)
        try:
            top = self.winfo_toplevel()
        except Exception:
            return

        # Knowledge detail is read-only; this simply re-renders the selected entity
        # with its new availability statement. No entity/source row is changed.
        show_entity = getattr(top, "_show_entity", None)
        if callable(show_entity):
            try:
                show_entity()
            except Exception:
                pass

        # Quest progress remains writable player state. Refreshing guidance changes
        # only the recommendation text, never tracked/completed progress.
        refresh_guidance = getattr(top, "_refresh_guidance", None)
        if callable(refresh_guidance):
            try:
                refresh_guidance()
            except Exception:
                pass

    setattr(_world_profile_changed, _PROFILE_AVAILABILITY_UI_MARKER, True)
    current._world_profile_changed = _world_profile_changed
