from __future__ import annotations

from pathlib import Path

from .live_composition import chain_live_start
from .log_geography import recover_log_geography


_QUEST_PROGRESS_ZONE_CONTEXT_MARKER = "_everquestie_quest_progress_zone_context_ui"


def _zone_context_from_log(log_path: str | Path, parser) -> str | None:
    """Return the last authoritative zone boundary in one EQ log."""
    geography = recover_log_geography(log_path, parser)
    return geography.zone if geography is not None else None


def install_quest_progress_zone_context_ui() -> None:
    """Seed QuestEngine with explicit log geography when monitoring starts.

    Live QuestEngine observation owns subsequent zone/Welcome boundaries itself. This
    wrapper only handles the important start-at-EOF case where the player is already in
    a zone and no new zone line will arrive after the tailer starts.
    """
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _QUEST_PROGRESS_ZONE_CONTEXT_MARKER, False):
        return

    def _seed_quest_progress_zone_context_after_start(self) -> None:
        if getattr(self, "tailer", None) is None:
            return

        engine = getattr(self, "quest_engine", None)
        parser = getattr(self, "parser", None)
        log_var = getattr(self, "log_path", None)
        if engine is None or parser is None or log_var is None:
            return

        log_path = str(log_var.get() or "").strip()
        starting_zone = _zone_context_from_log(log_path, parser) if log_path else None
        engine.seed_zone_context(starting_zone)

    chain_live_start(current_app, _seed_quest_progress_zone_context_after_start)
    setattr(current_app, _QUEST_PROGRESS_ZONE_CONTEXT_MARKER, True)
