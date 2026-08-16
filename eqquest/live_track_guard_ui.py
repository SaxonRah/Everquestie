from __future__ import annotations


_LIVE_TRACK_GUARD_MARKER = "_everquestie_live_track_guard_ui"


def _refresh_live_recommendations(self) -> None:
    """Refresh the composed Live recommendation stack after ownership changes."""
    refresh = getattr(self, "_refresh_activity_pathways", None)
    if callable(refresh):
        try:
            refresh(force=True)
        except Exception:
            pass


def track_live_recommendation(
    self,
    selection,
    *,
    announce: str,
    surface_label: str,
) -> bool:
    """Track one selected quest only after verifying writable player state now.

    Live recommendation rows are read projections and can become stale between render
    and click. The writable tracked-quest state is therefore authoritative at the
    action boundary. If ownership cannot be verified, fail closed instead of risking a
    duplicate reconciliation pass.
    """
    quest_id = int(selection.quest_id)
    quest_name = str(selection.quest_name)
    checker = getattr(getattr(self, "db", None), "is_quest_tracked", None)
    if not callable(checker):
        self.status.set(
            f"{surface_label}: could not verify whether {quest_name} is already tracked; "
            "quest state was not changed."
        )
        return False

    try:
        already_tracked = bool(checker(quest_id))
    except Exception:
        self.status.set(
            f"{surface_label}: could not verify whether {quest_name} is already tracked; "
            "quest state was not changed."
        )
        return False

    if already_tracked:
        self.status.set(f"{quest_name} is already tracked.")
        _refresh_live_recommendations(self)
        return False

    self._track_and_reconcile(quest_id, announce=announce)
    refresh_guidance = getattr(self, "_refresh_guidance", None)
    if callable(refresh_guidance):
        refresh_guidance()
    if hasattr(self, "_target_quest_relevance_key"):
        self._target_quest_relevance_key = None
    _refresh_live_recommendations(self)
    return True


def install_live_track_guard_ui() -> None:
    """Make every Live recommendation Track action re-check ownership on click."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _LIVE_TRACK_GUARD_MARKER, False):
        return

    def _activity_pathway_track_selected(self) -> None:
        suggestion = self._selected_activity_pathway()
        if suggestion is None:
            self.status.set("Select a Potential Pathway first.")
            return
        track_live_recommendation(
            self,
            suggestion,
            announce="PATHWAY | tracking suggested quest",
            surface_label="Potential Pathway",
        )

    def _zone_opportunity_track_selected(self) -> None:
        opportunity = self._selected_zone_opportunity()
        if opportunity is None:
            self.status.set("Select a Zone Opportunity first.")
            return
        track_live_recommendation(
            self,
            opportunity,
            announce="ZONE OPPORTUNITY | tracking selected quest",
            surface_label="Zone Opportunity",
        )

    def _loot_relevance_track_quest(self) -> None:
        selected = self._selected_loot_relevance()
        if selected is None:
            self.status.set("Select a Recent Loot Relevance row first.")
            return
        _item, use = selected
        track_live_recommendation(
            self,
            use,
            announce="LOOT RELEVANCE | tracking selected quest",
            surface_label="Recent Loot Relevance",
        )

    def _target_quest_track_selected(self) -> None:
        relevance = self._selected_target_quest()
        if relevance is None:
            self.status.set("Select a target-related quest first.")
            return
        track_live_recommendation(
            self,
            relevance,
            announce="TARGET | tracking source-backed related quest",
            surface_label="Target Intelligence",
        )

    current_app._activity_pathway_track_selected = _activity_pathway_track_selected
    current_app._zone_opportunity_track_selected = _zone_opportunity_track_selected
    current_app._loot_relevance_track_quest = _loot_relevance_track_quest
    current_app._target_quest_track_selected = _target_quest_track_selected
    setattr(current_app, _LIVE_TRACK_GUARD_MARKER, True)
