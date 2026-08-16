from __future__ import annotations

from .personal_observations import personal_observation_text


_PERSONAL_OBSERVATIONS_UI_MARKER = "_everquestie_personal_observations_ui"


def install_personal_observations_ui() -> None:
    """Append player-owned log history to normal Knowledge detail read-only."""
    from . import app as app_module

    current_renderer = app_module.entity_detail_text
    if getattr(current_renderer, _PERSONAL_OBSERVATIONS_UI_MARKER, False):
        return

    def entity_detail_with_personal_observations(
        db,
        entity_id: int,
        *,
        include_source_text: bool = False,
    ) -> str:
        # Preserve the current player-facing renderer (profile availability, raw-source
        # suppression, world detail, provenance). Personal history is a separate block.
        text = current_renderer(
            db,
            int(entity_id),
            include_source_text=include_source_text,
        )
        if text == "Entity not found.":
            return text
        observations = personal_observation_text(db, int(entity_id))
        if not observations:
            return text
        return text.rstrip() + "\n\n" + observations

    setattr(
        entity_detail_with_personal_observations,
        _PERSONAL_OBSERVATIONS_UI_MARKER,
        True,
    )
    app_module.entity_detail_text = entity_detail_with_personal_observations
