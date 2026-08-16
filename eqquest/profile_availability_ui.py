from __future__ import annotations


_PROFILE_AVAILABILITY_UI_MARKER = "_everquestie_profile_availability_ui"
_PROFILE_QUEST_ZONE_MARKER = "_everquestie_profile_quest_zone_policy"


def install_profile_availability_ui() -> None:
    """Project the global gameplay profile into Knowledge and tracked-quest guidance."""
    from . import app as app_module
    from .profile_availability import (
        ProfileAwareQuestEngine,
        entity_profile_decision,
        profiled_entity_detail_text,
    )
    from .world_profiles import world_profile

    # app.py imported these names directly. Rebinding its runtime globals keeps the
    # legacy/source UI builder intact while making normal entity detail and the quest
    # engine consume the same selected gameplay profile as Travel.
    app_module.entity_detail_text = profiled_entity_detail_text
    app_module.QuestEngine = ProfileAwareQuestEngine

    # Tracking a quest may historically suggest its zone when the log has not supplied
    # one. Keep that convenience only when the selected profile does not positively
    # reject the quest's direct canonical world evidence. Tracking and reconciliation
    # still proceed either way.
    current_app = app_module.EverQuestieApp
    current_suggest_zone = current_app._suggest_zone_from_quest
    if not getattr(current_suggest_zone, _PROFILE_QUEST_ZONE_MARKER, False):
        def _suggest_zone_from_quest(self, quest_id: int) -> None:
            decision = entity_profile_decision(self.db, int(quest_id))
            if decision.blocked:
                profile = world_profile(decision.profile_id)
                row = self.db.entity(int(quest_id))
                name = str(row["name"]) if row is not None else str(quest_id)
                try:
                    self._append_event(
                        f"ZONE | not inferred from quest under {profile.label}: {name} | {decision.reason}"
                    )
                except Exception:
                    pass
                return
            return current_suggest_zone(self, quest_id)

        setattr(_suggest_zone_from_quest, _PROFILE_QUEST_ZONE_MARKER, True)
        current_app._suggest_zone_from_quest = _suggest_zone_from_quest

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
