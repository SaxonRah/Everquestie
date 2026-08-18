from __future__ import annotations

from .session_activity_ledger import latest_observed_event, session_ledger_entry


_SESSION_ACTIVITY_LEDGER_MARKER = "_everquestie_session_activity_ledger_ui"


def install_session_activity_ledger_ui() -> None:
    """Annotate persisted kill/loot rows in the existing chronological Live tail.

    This deliberately reuses the existing event text surface instead of adding another
    competing panel. The original parsed event remains the parent line; derived lines
    are indented beneath it and are read-only projections from user observations plus
    shipped knowledge.
    """
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _SESSION_ACTIVITY_LEDGER_MARKER, False):
        return

    current_build_live = current_app._build_live
    current_append_event = current_app._append_event
    current_start = current_app._start

    def _build_live(self) -> None:
        current_build_live(self)
        self._session_activity_ledger_last_event_id = int(
            getattr(self, "_activity_session_start_event_id", 0) or 0
        )

    def _start(self) -> None:
        current_start(self)
        self._session_activity_ledger_last_event_id = int(
            getattr(self, "_activity_session_start_event_id", 0) or 0
        )

    def _append_event(self, text: str) -> None:
        current_append_event(self, text)

        latest = latest_observed_event(self.db)
        if latest is None:
            return
        event_id, event = latest
        boundary = int(getattr(self, "_activity_session_start_event_id", 0) or 0)
        last = int(getattr(self, "_session_activity_ledger_last_event_id", boundary) or 0)
        if event_id <= max(boundary, last):
            return

        # _append_event is also used for commands, reconciliation notices and manual
        # zone messages. Annotate only the exact summary of the just-persisted event.
        if str(text) != event.summary():
            return

        self._session_activity_ledger_last_event_id = event_id
        if event.kind not in {"kill", "loot"}:
            return

        engine = getattr(self, "activity_pathway_engine", None)
        suggestions = ()
        if engine is not None:
            # Consume the observation now so the annotation and the dedicated Potential
            # Pathways panel use the same session counters. The normal timer can safely
            # call refresh_observations again; it will see no duplicate event IDs.
            engine.refresh_observations()
            suggestions = tuple(
                engine.suggestions(
                    getattr(self.state_model, "current_zone", None),
                    limit=25,
                )
            )

        entry = session_ledger_entry(
            self.db,
            event_id,
            boundary,
            current_zone=getattr(self.state_model, "current_zone", None),
            pathway_suggestions=suggestions,
        )
        if entry is None:
            return
        for annotation in entry.annotations:
            current_append_event(self, f"  ↳ {annotation}")

    current_app._build_live = _build_live
    current_app._start = _start
    current_app._append_event = _append_event
    setattr(current_app, _SESSION_ACTIVITY_LEDGER_MARKER, True)
