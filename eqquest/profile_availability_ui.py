from __future__ import annotations


_PROFILE_AVAILABILITY_UI_MARKER = "_everquestie_profile_availability_ui"
_PROFILE_QUEST_ZONE_MARKER = "_everquestie_profile_quest_zone_policy"


def player_knowledge_detail_text(
    db,
    entity_id: int,
    *,
    include_source_text: bool = False,
) -> str:
    """Render the complete player-facing Knowledge projection.

    The underlying knowledge renderer deliberately retains an opt-in raw-source
    snapshot for builder/debug callers. The normal Knowledge pane instead shows
    canonical/entity-specific projections plus provenance, gameplay-profile context,
    and a clearly separated player-owned log-history block when observations exist.

    Shared client support files such as dbstr_us.txt and ZoneNames.txt are whole-file
    source records, so their raw text is never dumped beneath one selected entity.
    Personal observations are not promoted into canonical source data; they remain a
    read-only projection of the writable user-state event history.

    ``include_source_text`` is accepted for signature compatibility with the legacy
    app callback, which historically passed ``True``. It is intentionally ignored at
    this player-facing boundary; direct diagnostic callers can still request source
    text from :func:`eqquest.knowledge.entity_detail_text`.
    """
    from .personal_observations import personal_observation_text
    from .profile_availability import profiled_entity_detail_text

    text = profiled_entity_detail_text(db, int(entity_id), include_source_text=False)
    if text == "Entity not found.":
        return text
    observations = personal_observation_text(db, int(entity_id))
    if not observations:
        return text
    return text.rstrip() + "\n\n" + observations


def install_profile_availability_ui() -> None:
    """Project the global gameplay profile into player-facing knowledge surfaces."""
    from . import app as app_module
    from . import mechanics_context_ui as mechanics_ui
    from .mechanics_profile_availability import profiled_spell_stacking_text
    from .profile_availability import ProfileAwareQuestEngine
    from .world_profiles import active_world_profile_id, world_profile, zone_profile_decision
    from .zone_authority import resolve_authoritative_zone

    # app.py imported these names directly. Rebinding its runtime globals keeps the
    # legacy/source UI builder intact while making normal entity detail and the quest
    # engine consume the same selected gameplay profile as Travel. Raw source-page
    # snapshots remain available to explicit diagnostics but are not dumped into the
    # normal Knowledge pane. Player observations remain clearly labeled user-state data.
    app_module.entity_detail_text = player_knowledge_detail_text
    app_module.QuestEngine = ProfileAwareQuestEngine

    # MechanicsContextFrame resolves this module global when a spell is selected. Keep
    # canonical stacking/mechanics unchanged and compose the same profile projection
    # used by Knowledge underneath it. This is read-only and idempotent.
    mechanics_ui.spell_stacking_text = profiled_spell_stacking_text

    # Tracking a quest may historically suggest its zone when the log has not supplied
    # one. Evaluate the exact zone the app is about to suggest, not only the quest's
    # aggregate availability: mixed-era quests can contain both allowed and blocked
    # world evidence. Tracking and reconciliation still proceed either way.
    current_app = app_module.EverQuestieApp
    current_suggest_zone = current_app._suggest_zone_from_quest
    if not getattr(current_suggest_zone, _PROFILE_QUEST_ZONE_MARKER, False):
        def _suggest_zone_from_quest(self, quest_id: int) -> None:
            zone = self._quest_zone_name(int(quest_id))
            if zone:
                resolution = resolve_authoritative_zone(self.db, zone)
                if resolution.identity is not None:
                    profile_id = active_world_profile_id(self.db)
                    decision = zone_profile_decision(
                        self.db,
                        resolution.identity.entity_id,
                        profile_id,
                    )
                    if not decision.allowed:
                        profile = world_profile(profile_id)
                        row = self.db.entity(int(quest_id))
                        name = str(row["name"]) if row is not None else str(quest_id)
                        try:
                            self._append_event(
                                f"ZONE | not inferred from quest under {profile.label}: "
                                f"{name} -> {decision.zone_name} | {decision.reason}"
                            )
                        except Exception:
                            pass
                        return
            return current_suggest_zone(self, quest_id)

        setattr(_suggest_zone_from_quest, _PROFILE_QUEST_ZONE_MARKER, True)
        current_app._suggest_zone_from_quest = _suggest_zone_from_quest

    # world_profile_ui owns the application-level selector. Decorate that one global
    # change callback so already-built Knowledge, tracked-quest, Live intelligence and
    # Mechanics surfaces update immediately when the player changes server context.
    current_changed = getattr(current_app, "_world_profile_changed", None)
    if current_changed is None or getattr(current_changed, _PROFILE_AVAILABILITY_UI_MARKER, False):
        return

    def _world_profile_changed(self, event=None) -> None:
        current_changed(self, event)

        # Knowledge detail is read-only; this simply re-renders the selected entity
        # with its new availability statement. No entity/source row is changed.
        show_entity = getattr(self, "_show_entity", None)
        if callable(show_entity):
            try:
                show_entity()
            except Exception:
                pass

        # Quest progress remains writable player state. Refreshing guidance changes
        # only the recommendation text, never tracked/completed progress.
        refresh_guidance = getattr(self, "_refresh_guidance", None)
        if callable(refresh_guidance):
            try:
                refresh_guidance()
            except Exception:
                pass

        # Potential Pathways owns the composed Live refresh chain. Resolve the method
        # dynamically at profile-change time so later-installed Zone Opportunities,
        # Recent Loot and Target Intelligence decorators all refresh in the same pass.
        # This is projection-only; it does not create observations or mutate quest state.
        refresh_live = getattr(self, "_refresh_activity_pathways", None)
        if callable(refresh_live):
            try:
                refresh_live(force=True)
            except Exception:
                pass

        mechanics = getattr(self, "mechanics_view", None)

        # Class/level mechanics are exact Live-client source facts, not a profile ruleset
        # projection. Re-render their source-context notice immediately on profile change.
        refresh_class = getattr(mechanics, "refresh_class_level", None)
        if callable(refresh_class):
            try:
                refresh_class()
            except Exception:
                pass

        # Spell selection is another read-only projection of the same entity. Re-render
        # it so a profile switch cannot leave stale availability under current mechanics.
        refresh_spell = getattr(mechanics, "_spell_selected", None)
        if callable(refresh_spell):
            try:
                refresh_spell()
            except Exception:
                pass

    setattr(_world_profile_changed, _PROFILE_AVAILABILITY_UI_MARKER, True)
    current_app._world_profile_changed = _world_profile_changed
