from __future__ import annotations

from pathlib import Path


_RUNTIME_MODE_UI_MARKER = "_everquestie_runtime_mode_ui"
_RUNTIME_PROFILE_REFRESH_MARKER = "_everquestie_runtime_profile_refresh"
_RUNTIME_DATABASE_DIAGNOSTIC_MARKER = "_everquestie_profile_capability_diagnostic"

_RELEASE_INPUT_META_KEYS = (
    "approved_zone_alias_supplement_count",
    "approved_zone_alias_count",
    "approved_travel_supplement_count",
    "approved_travel_supplement_edge_count",
)


def _server_profile_label(db) -> str:
    """Return the persisted global server profile without making diagnostics fragile."""
    try:
        from .world_profiles import active_world_profile_id, world_profile

        return world_profile(active_world_profile_id(db)).label
    except Exception:
        return "not reported"


def profile_capability_text(db) -> str:
    """Describe which runtime surfaces are truly profile-specific today."""
    try:
        from .world_profiles import active_world_profile_id, world_profile

        profile = world_profile(active_world_profile_id(db))
    except Exception:
        return (
            "Server profile capabilities:\n"
            "  Profile: not reported\n"
            "  Routing / entity availability: not reported\n"
            "  Class/level Mechanics: source compatibility not reported"
        )

    if profile.profile_id == "live":
        routing = "Live profile policy (default)"
        mechanics = "exact installed Live-client support-file facts"
    elif profile.profile_id == "unrestricted":
        routing = "unrestricted confirmed topology / lifecycle projection"
        mechanics = "Live-client source facts only; not a custom-server ruleset projection"
    else:
        cap = f" through {profile.expansion_cap.replace('_', ' ').title()}" if profile.expansion_cap else ""
        routing = f"profile-filtered topology / lifecycle{cap}"
        mechanics = "Live-client source facts only; not a profile-specific ruleset projection"

    return (
        "Server profile capabilities:\n"
        f"  Profile: {profile.label}\n"
        f"  Routing / entity availability: {routing}\n"
        f"  Class/level Mechanics: {mechanics}"
    )


def release_knowledge_inputs_text(db) -> str:
    """Describe reviewed inputs retained by an immutable release snapshot.

    Old packaged snapshots contain none of these counters and remain quiet. A partially
    populated or malformed set is surfaced explicitly instead of silently implying that
    a release was fully staged.
    """
    if getattr(db, "knowledge_writable", True):
        return ""

    get_meta = getattr(db, "get_meta", None)
    if not callable(get_meta):
        return ""

    try:
        raw = {
            key: str(get_meta(key, "") or "").strip()
            for key in _RELEASE_INPUT_META_KEYS
        }
    except Exception:
        return ""

    if not any(raw.values()):
        return ""
    if not all(raw.values()):
        return (
            "Release knowledge inputs:\n"
            "  Reviewed-input counters: incomplete"
        )

    try:
        alias_supplements = int(raw["approved_zone_alias_supplement_count"])
        aliases = int(raw["approved_zone_alias_count"])
        travel_supplements = int(raw["approved_travel_supplement_count"])
        travel_edges = int(raw["approved_travel_supplement_edge_count"])
    except ValueError:
        return (
            "Release knowledge inputs:\n"
            "  Reviewed-input counters: invalid"
        )

    return (
        "Release knowledge inputs:\n"
        f"  Reviewed zone aliases: {aliases} aliases from {alias_supplements} supplement(s)\n"
        f"  Reviewed travel: {travel_edges} edges from {travel_supplements} supplement(s)"
    )


def database_mode_text(db) -> str:
    """Return an unmistakable description of DB boundary plus active server context."""
    profile = _server_profile_label(db)
    if not getattr(db, "knowledge_writable", True):
        knowledge = Path(getattr(db, "knowledge_path", getattr(db, "path", "")))
        state = Path(getattr(db, "state_path", ""))
        return (
            "Database mode: PACKAGED / IMMUTABLE"
            f"   |   Server: {profile}"
            f"   |   Knowledge: {knowledge}"
            f"   |   User state: {state}"
        )
    path = Path(getattr(db, "path", ""))
    return (
        "Database mode: BUILDER / MUTABLE"
        f"   |   Server: {profile}"
        f"   |   Database: {path}"
    )


def install_runtime_mode_ui() -> None:
    """Add persistent database-role/server-context diagnostics after UI policies."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    current_build_ui = current_app._build_ui
    if not getattr(current_build_ui, _RUNTIME_MODE_UI_MARKER, False):
        def _build_ui(self) -> None:
            current_build_ui(self)

            from tkinter import ttk

            text = database_mode_text(self.db)
            banner = ttk.Frame(self, padding=(8, 3, 8, 3), style="Stone.TFrame")
            label = ttk.Label(banner, text=text, anchor="w")
            label.pack(fill="x")
            try:
                banner.pack(fill="x", padx=8, pady=(0, 4), before=self.notebook)
            except Exception:
                banner.pack(fill="x", padx=8, pady=(0, 4))
            self.database_mode_banner = banner
            self.database_mode_label = label

            mode = (
                "PACKAGED/IMMUTABLE"
                if not getattr(self.db, "knowledge_writable", True)
                else "BUILDER/MUTABLE"
            )
            try:
                self.title(f"{self.title()} — {mode}")
            except Exception:
                pass

        setattr(_build_ui, _RUNTIME_MODE_UI_MARKER, True)
        current_app._build_ui = _build_ui

    # Append the profile capability boundary to the normal Database diagnostics rather
    # than making the persistent top banner excessively long. Packaged snapshots also
    # expose the compact reviewed release-input counters retained by finalization.
    current_database_text = getattr(current_app, "_database_diagnostic_text", None)
    if current_database_text is not None and not getattr(
        current_database_text,
        _RUNTIME_DATABASE_DIAGNOSTIC_MARKER,
        False,
    ):
        def _database_diagnostic_text(self) -> str:
            parts = [current_database_text(self).rstrip(), profile_capability_text(self.db)]
            release_inputs = release_knowledge_inputs_text(self.db)
            if release_inputs:
                parts.append(release_inputs)
            return "\n\n".join(parts)

        setattr(_database_diagnostic_text, _RUNTIME_DATABASE_DIAGNOSTIC_MARKER, True)
        current_app._database_diagnostic_text = _database_diagnostic_text

    # The global Server selector is installed before this diagnostics layer. Decorate
    # its application-level callback so the persistent banner always reflects the
    # profile that actually owns Travel/Knowledge/quest availability.
    current_changed = getattr(current_app, "_world_profile_changed", None)
    if current_changed is None or getattr(current_changed, _RUNTIME_PROFILE_REFRESH_MARKER, False):
        return

    def _world_profile_changed(self, event=None) -> None:
        current_changed(self, event)
        label = getattr(self, "database_mode_label", None)
        if label is None:
            return
        try:
            label.configure(text=database_mode_text(self.db))
        except Exception:
            pass

    setattr(_world_profile_changed, _RUNTIME_PROFILE_REFRESH_MARKER, True)
    current_app._world_profile_changed = _world_profile_changed
