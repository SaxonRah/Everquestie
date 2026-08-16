from __future__ import annotations


_WORLD_PROFILE_UI_MARKER = "_everquestie_world_profile_ui"
_GLOBAL_PROFILE_APP_MARKER = "_everquestie_global_world_profile_ui"


def _children(widget) -> list:
    try:
        return list(widget.winfo_children())
    except Exception:
        return []


def _walk(widget):
    stack = [widget]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(_children(current)))


def _find_log_controls(app):
    """Find the application top bar without coupling to a private widget name."""
    for child in _children(app):
        for descendant in _walk(child):
            try:
                if str(descendant.cget("text")) == "EQ log:":
                    return child
            except Exception:
                continue
    return None


def install_world_profile_ui() -> None:
    """Install global gameplay/server profile UI and profiled Travel routing.

    The selected profile affects more than Travel, so its owner is the application
    chrome rather than one tab. Travel still owns route calculation/results, while the
    global selector stores one user-state profile consumed by Travel, Knowledge and
    tracked-quest guidance.
    """
    from . import app as app_module
    from . import route_guidance_ui as ui
    from .world_profile_routing import (
        build_profiled_route_guidance,
        profiled_route_guidance_text,
    )
    from .world_profiles import (
        WORLD_PROFILES,
        active_world_profile_id,
        set_active_world_profile,
        world_profile,
        zone_profile_decision,
    )

    # RouteGuidanceFrame resolves these names from its module globals at call time.
    # Replacing the references keeps one Travel owner and one hop renderer while adding
    # a read-time world-profile filter over the finalized canonical graph.
    ui.build_route_guidance = build_profiled_route_guidance
    ui.route_guidance_text = profiled_route_guidance_text

    current = ui.RouteGuidanceFrame
    current_show_zone = current.show_zone_context
    if not getattr(current_show_zone, _WORLD_PROFILE_UI_MARKER, False):
        def _show_zone_context(self) -> None:
            current_show_zone(self)
            token = self._selected_or_current_zone()
            if not token:
                return
            try:
                from .zone_authority import resolve_authoritative_zone

                resolution = resolve_authoritative_zone(self.db, token)
                if resolution.identity is None:
                    return
                profile = world_profile(active_world_profile_id(self.db))
                decision = zone_profile_decision(
                    self.db,
                    resolution.identity.entity_id,
                    profile.profile_id,
                )
                availability = "routeable" if decision.allowed else "not routeable"
                expansion = (
                    f" | expansion evidence: {', '.join(decision.expansions)}"
                    if decision.expansions
                    else ""
                )
                self.status_var.set(
                    f"{self.status_var.get()} | {profile.label}: {availability} "
                    f"({decision.reason}){expansion}"
                )
            except Exception:
                # Zone context remains useful even if profile annotation cannot be projected.
                return

        setattr(_show_zone_context, _WORLD_PROFILE_UI_MARKER, True)
        current.show_zone_context = _show_zone_context

    current_app = app_module.EverQuestieApp
    current_build_ui = current_app._build_ui
    if getattr(current_build_ui, _GLOBAL_PROFILE_APP_MARKER, False):
        return

    labels = tuple(profile.label for profile in WORLD_PROFILES)
    ids_by_label = {profile.label: profile.profile_id for profile in WORLD_PROFILES}

    def _world_profile_changed(self, _event=None) -> None:
        selected_label = self.world_profile_var.get().strip()
        profile_id = ids_by_label.get(selected_label, "live")
        profile = set_active_world_profile(self.db, profile_id)
        self.world_profile_var.set(profile.label)

        travel = getattr(self, "travel_tab", None)
        if travel is not None:
            try:
                travel._route_guidance = None
            except Exception:
                pass
            source = travel.from_var.get().strip() or "?"
            target = travel.to_var.get().strip()
            if target:
                try:
                    travel._everquestie_result_mode = "pending_route"
                except Exception:
                    pass
                try:
                    travel._set_result(
                        f"Server profile changed to {profile.label}.\n"
                        f"Route request: {source} → {target}\n\n"
                        "Press Find route to recalculate using this profile."
                    )
                except Exception:
                    pass
                try:
                    travel.status_var.set(
                        f"Server profile: {profile.label}. Cached route cleared; "
                        "press Find route to recalculate."
                    )
                except Exception:
                    pass
            else:
                try:
                    travel.status_var.set(
                        f"Server profile: {profile.label}. {profile.description}"
                    )
                except Exception:
                    pass

        try:
            self.status.set(f"Server profile: {profile.label}. {profile.description}")
        except Exception:
            pass

    def _build_ui(self) -> None:
        current_build_ui(self)
        import tkinter as tk
        from tkinter import ttk

        profile = world_profile(active_world_profile_id(self.db))
        self.world_profile_var = tk.StringVar(value=profile.label)

        top = _find_log_controls(self)
        if top is None:
            return

        holder = ttk.Frame(top)
        holder.pack(side="right", padx=(10, 0))
        ttk.Label(holder, text="Server:").pack(side="left", padx=(0, 4))
        combo = ttk.Combobox(
            holder,
            textvariable=self.world_profile_var,
            values=labels,
            state="readonly",
            width=31,
        )
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", self._world_profile_changed)
        self.world_profile_combo = combo

    setattr(_build_ui, _GLOBAL_PROFILE_APP_MARKER, True)
    current_app._world_profile_changed = _world_profile_changed
    current_app._build_ui = _build_ui
