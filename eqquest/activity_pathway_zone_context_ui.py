from __future__ import annotations

from .live_composition import chain_live_start


_ACTIVITY_PATHWAY_ZONE_CONTEXT_MARKER = "_everquestie_activity_pathway_zone_context_ui"


def install_activity_pathway_zone_context_ui() -> None:
    """Seed Pathways with the authoritative zone recovered when monitoring starts.

    The base application scans the selected log for its latest explicit zone before the
    tailer starts. Activity Pathways resets its session at that same boundary, so this
    final start wrapper re-seeds the engine with the recovered zone. New explicit zone
    and Welcome events remain authoritative after monitoring begins.
    """
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _ACTIVITY_PATHWAY_ZONE_CONTEXT_MARKER, False):
        return

    def _seed_activity_pathway_zone_context_after_start(self) -> None:
        engine = getattr(self, "activity_pathway_engine", None)
        if engine is None or getattr(self, "tailer", None) is None:
            return

        boundary = int(
            getattr(
                self,
                "_activity_session_start_event_id",
                engine.latest_observed_event_id(),
            )
            or 0
        )
        starting_zone = getattr(self.state_model, "current_zone", None)
        engine.reset_session(boundary, starting_zone=starting_zone)
        self._activity_session_start_zone = starting_zone
        self._activity_pathway_signature = None

    chain_live_start(current_app, _seed_activity_pathway_zone_context_after_start)
    setattr(current_app, _ACTIVITY_PATHWAY_ZONE_CONTEXT_MARKER, True)
