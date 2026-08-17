from __future__ import annotations

from pathlib import Path


_QUEST_PROGRESS_ZONE_CONTEXT_MARKER = "_everquestie_quest_progress_zone_context_ui"


def _zone_context_from_log(log_path: str | Path, parser) -> str | None:
    """Return the last authoritative zone boundary in one EQ log.

    Only explicit ``You have entered ...`` lines establish geography. ``Welcome to
    EverQuest!`` clears that geography until another explicit zone entry appears.
    Manual UI state and quest-inferred destinations are intentionally not inputs.
    """
    current: str | None = None
    try:
        with Path(log_path).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "You have entered " not in line and "Welcome to EverQuest!" not in line:
                    continue
                event = parser.parse_line(line)
                if event is None:
                    continue
                kind = str(event.kind or "").casefold()
                if kind == "welcome":
                    current = None
                elif kind == "zone" and event.zone:
                    current = " ".join(str(event.zone).split()).strip() or None
    except (OSError, PermissionError):
        return None
    return current


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

    current_start = current_app._start

    def _start(self) -> None:
        current_start(self)
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

    current_app._start = _start
    setattr(current_app, _QUEST_PROGRESS_ZONE_CONTEXT_MARKER, True)
