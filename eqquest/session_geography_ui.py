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
    """Make the app's current-zone owner obey explicit log geography boundaries.

    The base application historically recovered only zone and /loc lines and updated its
    labels only when values were truthy. That left the pre-login zone/location visible
    after ``Welcome to EverQuest!`` and left stale /loc text visible after ordinary zone
    changes. This layer makes unknown geography a first-class UI state without changing
    knowledge or player-owned quest data.
    """
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _SESSION_GEOGRAPHY_UI_MARKER, False):
        return

    current_drain = current_app._drain_lines

    def _bootstrap_state_from_log(self, log_path) -> None:
        geography = recover_log_geography(log_path, self.parser)
        if geography is None:
            return

        self.state_model.clear_geography()
        if geography.zone:
            self.state_model.set_zone(
                geography.zone,
                source="log-history",
                force=True,
            )
        if geography.location is not None:
            self.state_model.last_location = geography.location

        _render_session_geography(self)

        map_view = getattr(self, "map_view", None)
        if map_view is None:
            return
        if geography.zone:
            map_view.manual_zone.set(geography.zone)
            map_view.load_current_zone()
        else:
            _mark_loaded_map_as_reference(self)

    def _drain_lines(self):
        before_zone = getattr(self.state_model, "current_zone", None)
        result = current_drain(self)
        _render_session_geography(self)
        after_zone = getattr(self.state_model, "current_zone", None)
        if before_zone and not after_zone:
            _mark_loaded_map_as_reference(self)
        return result

    current_app._bootstrap_state_from_log = _bootstrap_state_from_log
    current_app._drain_lines = _drain_lines
    setattr(current_app, _SESSION_GEOGRAPHY_UI_MARKER, True)
