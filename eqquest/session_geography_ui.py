from __future__ import annotations

from .log_geography import recover_log_geography


_SESSION_GEOGRAPHY_UI_MARKER = "_everquestie_session_geography_ui"


def _render_session_geography(app) -> None:
    """Render current state including explicit unknown zone/location values."""
    app._update_zone_display()
    location = getattr(app.state_model, "last_location", None)
    if location is None:
        app.loc_var.set("Location: unknown")
        return
    x, y, z = location
    app.loc_var.set(f"Location: {x:.1f}, {y:.1f}, {z:.1f}")


def _mark_loaded_map_as_reference(app) -> None:
    """Do not let an old loaded map masquerade as current after geography is lost."""
    map_view = getattr(app, "map_view", None)
    if map_view is None:
        return
    try:
        map_view.manual_zone.set("")
    except Exception:
        pass
    if getattr(map_view, "zone_map", None) is not None:
        try:
            map_view.map_status.set(
                "Current zone is unknown after the latest Welcome boundary; "
                "the loaded map is reference only until a new zone is observed."
            )
        except Exception:
            pass
    try:
        map_view._redraw_position()
    except Exception:
        pass


def install_session_geography_ui() -> None:
    """Keep explicit geography-boundary UI policy without replacing async bootstrap.

    The base app owns bounded/background log-history recovery.  This layer renders
    unknown geography explicitly and makes a previously loaded map reference-only
    when geography is lost.
    """
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _SESSION_GEOGRAPHY_UI_MARKER, False):
        return

    current_drain = current_app._drain_lines
    current_apply_bootstrap = getattr(
        current_app,
        "_apply_bootstrap_state",
        None,
    )

    if current_apply_bootstrap is not None:
        def _apply_bootstrap_state(self, *args, **kwargs):
            result = current_apply_bootstrap(self, *args, **kwargs)

            _render_session_geography(self)

            if getattr(self.state_model, "current_zone", None) is None:
                _mark_loaded_map_as_reference(self)

            return result

        current_app._apply_bootstrap_state = _apply_bootstrap_state

    def _drain_lines(self):
        before_zone = getattr(
            self.state_model,
            "current_zone",
            None,
        )

        result = current_drain(self)

        _render_session_geography(self)

        after_zone = getattr(
            self.state_model,
            "current_zone",
            None,
        )

        if before_zone and not after_zone:
            _mark_loaded_map_as_reference(self)

        return result

    # IMPORTANT:
    # Do not replace _bootstrap_state_from_log here.  The base implementation
    # starts live tailing first and performs bounded history recovery on a worker.
    current_app._drain_lines = _drain_lines
    setattr(
        current_app,
        _SESSION_GEOGRAPHY_UI_MARKER,
        True,
    )
