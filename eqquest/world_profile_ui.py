from __future__ import annotations


_WORLD_PROFILE_UI_MARKER = "_everquestie_world_profile_ui"


def _children(widget) -> list:
    try:
        return list(widget.winfo_children())
    except Exception:
        return []


def _find_zone_navigation_controls(frame):
    for child in _children(frame):
        try:
            if str(child.cget("text")) == "Zone navigation":
                return child
        except Exception:
            continue
    return None


def install_world_profile_ui() -> None:
    """Install persistent gameplay-profile routing on the shared Travel surface."""
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
    current_build = current._build
    if getattr(current_build, _WORLD_PROFILE_UI_MARKER, False):
        return
    current_show_zone = current.show_zone_context

    labels = tuple(profile.label for profile in WORLD_PROFILES)
    ids_by_label = {profile.label: profile.profile_id for profile in WORLD_PROFILES}

    def _world_profile_changed(self, _event=None) -> None:
        selected_label = self.world_profile_var.get().strip()
        profile_id = ids_by_label.get(selected_label, "live")
        profile = set_active_world_profile(self.db, profile_id)
        self._route_guidance = None
        self.world_profile_status_var.set(profile.description)

        source = self.from_var.get().strip() or "?"
        target = self.to_var.get().strip()
        if target:
            try:
                self._everquestie_result_mode = "pending_route"
            except Exception:
                pass
            self._set_result(
                f"Gameplay profile changed to {profile.label}.\n"
                f"Route request: {source} → {target}\n\n"
                "Press Find route to recalculate using this profile."
            )
            self.status_var.set(
                f"Gameplay profile: {profile.label}. Cached route cleared; press Find route to recalculate."
            )
        else:
            self.status_var.set(f"Gameplay profile: {profile.label}. {profile.description}")

    def _build(self) -> None:
        current_build(self)
        import tkinter as tk
        from tkinter import ttk

        profile = world_profile(active_world_profile_id(self.db))
        self.world_profile_var = tk.StringVar(value=profile.label)
        self.world_profile_status_var = tk.StringVar(value=profile.description)

        controls = _find_zone_navigation_controls(self)
        if controls is None:
            return

        ttk.Label(controls, text="Gameplay profile").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        combo = ttk.Combobox(
            controls,
            textvariable=self.world_profile_var,
            values=labels,
            state="readonly",
            width=34,
        )
        combo.grid(row=2, column=1, sticky="w", padx=8, pady=(8, 0))
        combo.bind("<<ComboboxSelected>>", self._world_profile_changed)
        ttk.Label(
            controls,
            textvariable=self.world_profile_status_var,
            wraplength=650,
            justify="left",
        ).grid(row=2, column=2, columnspan=4, sticky="w", padx=(4, 0), pady=(8, 0))
        self.world_profile_combo = combo

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
                f"{self.status_var.get()} | {profile.label}: {availability} ({decision.reason}){expansion}"
            )
        except Exception:
            # Zone context remains useful even if profile annotation cannot be projected.
            return

    setattr(_build, _WORLD_PROFILE_UI_MARKER, True)
    current._world_profile_changed = _world_profile_changed
    current._build = _build
    current.show_zone_context = _show_zone_context
