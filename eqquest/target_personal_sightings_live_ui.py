from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .live_composition import chain_live_build
from .live_navigation import handoff_to_travel
from .target_personal_sightings import (
    target_personal_sighting_text,
    target_personal_sightings,
)
from .target_personal_sightings_ui import ask_target_personal_sighting
from .zone_authority import resolve_authoritative_zone


_TARGET_PERSONAL_SIGHTINGS_MARKER = "_everquestie_target_personal_sightings_ui"


def install_target_personal_sightings_ui() -> None:
    """Add on-demand personal sighting geography for the exact current NPC target."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _TARGET_PERSONAL_SIGHTINGS_MARKER, False):
        return

    def _build_target_personal_sightings(self) -> None:
        panel = ttk.LabelFrame(self.live_tab, text="Target History", padding=6)
        panel.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)

        self.target_personal_sightings_status = tk.StringVar(
            value=(
                "Personal sightings uses explicit logged zone-entry context. It never writes "
                "those observations into canonical NPC spawn/location knowledge."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.target_personal_sightings_status,
            justify="left",
            wraplength=1010,
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            panel,
            text="Personal sightings",
            command=self._target_personal_sightings_browse,
        ).grid(row=0, column=1, sticky="e", padx=(10, 0))

    def _target_personal_sightings_browse(self) -> None:
        target = getattr(self, "_target_intelligence_value", None)
        if target is None or not target.resolved or target.entity_id is None:
            self.status.set("No exact current NPC target is available for personal sighting history.")
            return

        rows = target_personal_sightings(self.db, int(target.entity_id))
        if not rows:
            text = (
                f"Your logs contain no trustworthy zone-context observations for "
                f"{target.canonical_name}. Events after a Welcome reset remain unlocated until "
                "another explicit zone entry is observed."
            )
            self.target_personal_sightings_status.set(text)
            self.status.set(text)
            return

        actionable = sum(1 for row in rows if row.actionable)
        observations = sum(int(row.total_count) for row in rows)
        self.target_personal_sightings_status.set(
            f"{target.canonical_name}: {observations} personal observation(s) across "
            f"{len(rows)} logged zone context(s); {actionable} resolve to canonical Travel destinations."
        )

        selected = ask_target_personal_sighting(
            self,
            target.canonical_name,
            rows,
        )
        if selected is None:
            self.status.set("Personal-sighting selection cancelled.")
            return

        if not selected.actionable or selected.canonical_zone_entity_id is None:
            messagebox.showinfo(
                "Personal Sighting History",
                target_personal_sighting_text(target.canonical_name, selected),
            )
            self.status.set(
                f"{selected.observed_zone_name}: personal sighting zone is "
                f"{selected.resolution_status}; EverQuestie will not guess a route destination."
            )
            return

        current_zone = " ".join(
            str(getattr(self.state_model, "current_zone", "") or "").split()
        ).strip()
        if current_zone:
            current_resolution = resolve_authoritative_zone(self.db, current_zone)
            if (
                current_resolution.identity is not None
                and int(current_resolution.identity.entity_id)
                == int(selected.canonical_zone_entity_id)
            ):
                messagebox.showinfo(
                    "Personal Sighting History",
                    target_personal_sighting_text(target.canonical_name, selected),
                )
                self.status.set(
                    f"Already in personal sighting zone {selected.canonical_zone_name} for "
                    f"{target.canonical_name}. Personal zone history contains no exact NPC /loc."
                )
                return

        routed = handoff_to_travel(self, selected.canonical_zone_name)
        if routed is None:
            self.status.set("Travel routing is not connected in this application surface.")
            return
        if routed:
            self.status.set(
                f"Travel route opened to personal sighting zone {selected.canonical_zone_name} "
                f"for {target.canonical_name}. Destination comes from your log history, not "
                "canonical spawn evidence."
            )
        else:
            self.status.set(
                f"Personal sighting zone {selected.canonical_zone_name} is canonical, but no "
                "confirmed route from the live current zone is available; see Travel for details."
            )

    def _target_personal_sighting_details(self, row) -> None:
        target = getattr(self, "_target_intelligence_value", None)
        target_name = (
            str(target.canonical_name)
            if target is not None and getattr(target, "resolved", False)
            else "current target"
        )
        messagebox.showinfo(
            "Personal Sighting History",
            target_personal_sighting_text(target_name, row),
        )

    chain_live_build(current_app, _build_target_personal_sightings)
    current_app._target_personal_sightings_browse = _target_personal_sightings_browse
    current_app._target_personal_sighting_details = _target_personal_sighting_details
    setattr(current_app, _TARGET_PERSONAL_SIGHTINGS_MARKER, True)
