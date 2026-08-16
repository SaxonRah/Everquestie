from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .knowledge_map_choices import knowledge_map_choices, knowledge_route_choices
from .target_intelligence import (
    TargetIntelligence,
    current_target_intelligence,
    target_intelligence_compact_text,
    target_intelligence_detail_text,
)


_TARGET_INTELLIGENCE_MARKER = "_everquestie_target_intelligence_ui"


def install_target_intelligence_ui() -> None:
    """Add exact current-target context and safe navigation to the Live tab."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _TARGET_INTELLIGENCE_MARKER, False):
        return

    current_build_live = current_app._build_live
    current_start = current_app._start
    current_stop = current_app._stop

    def _latest_observed_event_id(self) -> int:
        row = self.db.conn.execute(
            "SELECT COALESCE(MAX(id),0) AS event_id FROM observed_events"
        ).fetchone()
        return int(row["event_id"] or 0) if row is not None else 0

    def _build_live(self) -> None:
        current_build_live(self)

        panel = ttk.LabelFrame(self.live_tab, text="Target Intelligence", padding=6)
        panel.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)

        self.target_intelligence_status = tk.StringVar(
            value=(
                "Target or consider an NPC while monitoring to see exact source-backed "
                "context. EverQuestie will not fuzzy-match a target name."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.target_intelligence_status,
            justify="left",
            wraplength=1060,
        ).grid(row=0, column=0, sticky="ew")

        buttons = ttk.Frame(panel)
        buttons.grid(row=0, column=1, sticky="e", padx=(10, 0))
        ttk.Button(
            buttons,
            text="View target",
            command=self._target_intelligence_view,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="Navigate",
            command=self._target_intelligence_navigate,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Details",
            command=self._target_intelligence_details,
        ).pack(side="left", padx=(6, 0))

        self._target_intelligence_session_start_event_id = _latest_observed_event_id(self)
        self._target_intelligence_value: TargetIntelligence | None = None
        self._target_intelligence_signature = None
        self.after(400, self._target_intelligence_tick)

    def _target_intelligence_view(self) -> None:
        value = getattr(self, "_target_intelligence_value", None)
        if value is None or not value.resolved or value.entity_id is None:
            self.status.set("No exact current NPC target is available to open in Knowledge.")
            return

        opener = getattr(self, "_open_knowledge_entity_exact", None)
        if callable(opener):
            opener(int(value.entity_id))
        else:
            self._map_entity_selected(int(value.entity_id))

    def _target_intelligence_navigate(self) -> None:
        value = getattr(self, "_target_intelligence_value", None)
        if value is None or not value.resolved or value.entity_id is None:
            self.status.set("No exact current NPC target is available for navigation.")
            return

        choices = knowledge_map_choices(
            self.db,
            int(value.entity_id),
            getattr(self.state_model, "current_zone", None),
        )
        if choices.ready:
            if len(choices.choices) == 1:
                choice = choices.choices[0]
            else:
                from .knowledge_location_ui import ask_knowledge_map_choice

                choice = ask_knowledge_map_choice(
                    self,
                    value.canonical_name,
                    choices.current_zone_name,
                    choices.choices,
                )
                if choice is None:
                    self.status.set("Target location selection cancelled.")
                    return
            self._focus_navigation_map_target(
                choice.zone_name,
                choice.x,
                choice.y,
                choice.z,
                choice.map_label,
            )
            self.status.set(
                f"Mapped exact target {value.canonical_name} at {choice.loc_text}."
            )
            return

        routes = knowledge_route_choices(choices)
        if routes:
            if len(routes) == 1:
                route = routes[0]
            else:
                from .knowledge_location_ui import ask_knowledge_route_choice

                route = ask_knowledge_route_choice(
                    self,
                    value.canonical_name,
                    choices.current_zone_name,
                    routes,
                )
                if route is None:
                    self.status.set("Target route selection cancelled.")
                    return

            travel = getattr(self, "travel_tab", None)
            if travel is None or not hasattr(travel, "route_to_zone"):
                self.status.set("Travel routing is not connected in this application surface.")
                return
            self.notebook.select(self.travel_tab)
            routed = bool(self.travel_tab.route_to_zone(route.zone_name))
            if routed:
                self.status.set(
                    f"Travel route opened to {route.zone_name} for target {value.canonical_name}."
                )
            else:
                self.status.set(
                    f"No confirmed route to {route.zone_name} is currently available; "
                    "see Travel for details."
                )
            return

        self.status.set(choices.reason)

    def _target_intelligence_details(self) -> None:
        value = getattr(self, "_target_intelligence_value", None)
        if value is None:
            value = current_target_intelligence(
                self.db,
                after_event_id=int(
                    getattr(self, "_target_intelligence_session_start_event_id", 0) or 0
                ),
            )
        messagebox.showinfo(
            "Target Intelligence",
            target_intelligence_detail_text(value),
        )

    def _refresh_target_intelligence(self, *, force: bool = False) -> None:
        status = getattr(self, "target_intelligence_status", None)
        if status is None:
            return

        value = current_target_intelligence(
            self.db,
            after_event_id=int(
                getattr(self, "_target_intelligence_session_start_event_id", 0) or 0
            ),
        )
        signature = (
            value.status,
            value.observed_name,
            value.observed_event_kind,
            value.event_id,
            value.entity_id,
            value.canonical_name,
            value.resolution_kind,
            value.level_min,
            value.level_max,
            value.profile_status,
            tuple(
                (row.label, row.other_kind, row.count, row.examples)
                for row in value.relationships
            ),
            value.known_zones,
            value.personal_observed_slain,
            value.personal_targeted,
        )
        if force or signature != getattr(self, "_target_intelligence_signature", None):
            status.set(target_intelligence_compact_text(value))
            self._target_intelligence_signature = signature
        self._target_intelligence_value = value

    def _target_intelligence_tick(self) -> None:
        self._refresh_target_intelligence()
        self.after(400, self._target_intelligence_tick)

    def _start(self) -> None:
        current_start(self)
        if getattr(self, "tailer", None) is not None:
            self._target_intelligence_session_start_event_id = _latest_observed_event_id(self)
            self._target_intelligence_signature = None
            self._target_intelligence_value = None
            self._refresh_target_intelligence(force=True)

    def _stop(self) -> None:
        current_stop(self)
        if hasattr(self, "target_intelligence_status"):
            self._refresh_target_intelligence(force=True)

    current_app._build_live = _build_live
    current_app._target_intelligence_view = _target_intelligence_view
    current_app._target_intelligence_navigate = _target_intelligence_navigate
    current_app._target_intelligence_details = _target_intelligence_details
    current_app._refresh_target_intelligence = _refresh_target_intelligence
    current_app._target_intelligence_tick = _target_intelligence_tick
    current_app._start = _start
    current_app._stop = _stop
    setattr(current_app, _TARGET_INTELLIGENCE_MARKER, True)
