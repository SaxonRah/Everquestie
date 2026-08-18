from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .live_navigation import open_exact_knowledge_entity
from .target_known_drops import target_known_drop_text, target_known_drops
from .target_known_drops_ui import ask_target_known_drop
from .target_personal_loot import target_personal_loot, target_personal_loot_text
from .target_personal_loot_ui import ask_target_personal_loot
from .world_profiles import active_world_profile_id


_TARGET_KNOWN_DROPS_MARKER = "_everquestie_target_known_drops_ui"


def install_target_known_drops_ui() -> None:
    """Add on-demand canonical and personal drop history below Target Intelligence."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _TARGET_KNOWN_DROPS_MARKER, False):
        return

    current_build_live = current_app._build_live

    def _build_live(self) -> None:
        current_build_live(self)

        panel = ttk.LabelFrame(self.live_tab, text="Target Drops", padding=6)
        panel.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)

        self.target_known_drops_status = tk.StringVar(
            value=(
                "Known drops shows reviewed canonical relationships; Personal loot shows "
                "only what your own log explicitly recorded from this corpse/source."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.target_known_drops_status,
            justify="left",
            wraplength=950,
        ).grid(row=0, column=0, sticky="ew")

        buttons = ttk.Frame(panel)
        buttons.grid(row=0, column=1, sticky="e", padx=(10, 0))
        ttk.Button(
            buttons,
            text="Known drops",
            command=self._target_known_drops_browse,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="Personal loot",
            command=self._target_personal_loot_browse,
        ).pack(side="left", padx=(6, 0))

    def _target_known_drops_browse(self) -> None:
        target = getattr(self, "_target_intelligence_value", None)
        if target is None or not target.resolved or target.entity_id is None:
            self.status.set("No exact current NPC target is available for drop lookup.")
            return

        drops = target_known_drops(
            self.db,
            int(target.entity_id),
            profile_id=active_world_profile_id(self.db),
        )
        if not drops:
            text = (
                f"No reviewed source-backed drops are compiled for {target.canonical_name}. "
                "That is a knowledge gap, not a claim that the NPC has no loot."
            )
            self.target_known_drops_status.set(text)
            self.status.set(text)
            return

        tracked = sum(1 for drop in drops if any(use.tracked for use in drop.quest_uses))
        quest_items = sum(1 for drop in drops if drop.quest_uses)
        self.target_known_drops_status.set(
            f"{target.canonical_name}: {len(drops)} reviewed known drop(s); "
            f"{quest_items} with reviewed quest use, {tracked} used by a tracked quest."
        )
        selected = ask_target_known_drop(
            self,
            target.canonical_name,
            drops,
        )
        if selected is None:
            self.status.set("Known-drop selection cancelled.")
            return

        open_exact_knowledge_entity(self, int(selected.item_id))
        self.status.set(
            f"Opened exact known drop {selected.item_name} from {target.canonical_name}."
        )

    def _target_personal_loot_browse(self) -> None:
        target = getattr(self, "_target_intelligence_value", None)
        if target is None or not target.resolved or target.entity_id is None:
            self.status.set("No exact current NPC target is available for personal loot history.")
            return

        rows = target_personal_loot(self.db, int(target.entity_id))
        if not rows:
            text = (
                f"Your logs contain no explicit corpse/source loot observations for "
                f"{target.canonical_name}. Generic loot lines are not assigned by proximity."
            )
            self.target_known_drops_status.set(text)
            self.status.set(text)
            return

        resolved = sum(1 for row in rows if row.resolved)
        corroborated = sum(1 for row in rows if row.reviewed_drop_known)
        total_loot = sum(int(row.observed_count) for row in rows)
        self.target_known_drops_status.set(
            f"{target.canonical_name}: your logs explicitly recorded {total_loot} loot event(s) "
            f"across {len(rows)} item name(s); {resolved} exact canonical item(s), "
            f"{corroborated} independently corroborated by the reviewed drop graph."
        )

        selected = ask_target_personal_loot(self, target.canonical_name, rows)
        if selected is None:
            self.status.set("Personal-loot selection cancelled.")
            return

        if selected.item_id is None:
            messagebox.showinfo(
                "Personal Loot Observation",
                target_personal_loot_text(target.canonical_name, selected),
            )
            self.status.set(
                f"{selected.observed_item_name}: personal loot observation is "
                f"{selected.resolution_status}; no exact canonical item was opened."
            )
            return

        open_exact_knowledge_entity(self, int(selected.item_id))
        corroboration = (
            "reviewed drop evidence also exists"
            if selected.reviewed_drop_known
            else "personal observation only; no reviewed drop edge claimed"
        )
        self.status.set(
            f"Opened exact personal-loot item {selected.canonical_item_name} from "
            f"{target.canonical_name} ({corroboration})."
        )

    def _target_known_drop_details(self, drop) -> None:
        target = getattr(self, "_target_intelligence_value", None)
        target_name = (
            str(target.canonical_name)
            if target is not None and getattr(target, "resolved", False)
            else "current target"
        )
        messagebox.showinfo(
            "Target Drop Evidence",
            target_known_drop_text(target_name, drop),
        )

    def _target_personal_loot_details(self, row) -> None:
        target = getattr(self, "_target_intelligence_value", None)
        target_name = (
            str(target.canonical_name)
            if target is not None and getattr(target, "resolved", False)
            else "current target"
        )
        messagebox.showinfo(
            "Personal Loot Observation",
            target_personal_loot_text(target_name, row),
        )

    current_app._build_live = _build_live
    current_app._target_known_drops_browse = _target_known_drops_browse
    current_app._target_personal_loot_browse = _target_personal_loot_browse
    current_app._target_known_drop_details = _target_known_drop_details
    current_app._target_personal_loot_details = _target_personal_loot_details
    setattr(current_app, _TARGET_KNOWN_DROPS_MARKER, True)
