from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .target_known_drops import target_known_drop_text, target_known_drops
from .target_known_drops_ui import ask_target_known_drop
from .world_profiles import active_world_profile_id


_TARGET_KNOWN_DROPS_MARKER = "_everquestie_target_known_drops_ui"


def install_target_known_drops_ui() -> None:
    """Add an on-demand exact drop browser below Target Intelligence on Live."""
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
                "Choose Known drops after an exact NPC target resolves. Only reviewed "
                "source-backed drop relationships are listed."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.target_known_drops_status,
            justify="left",
            wraplength=1020,
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            panel,
            text="Known drops",
            command=self._target_known_drops_browse,
        ).grid(row=0, column=1, sticky="e", padx=(10, 0))

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

        opener = getattr(self, "_open_knowledge_entity_exact", None)
        if callable(opener):
            opener(int(selected.item_id))
        else:
            self._map_entity_selected(int(selected.item_id))
        self.status.set(
            f"Opened exact known drop {selected.item_name} from {target.canonical_name}."
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

    current_app._build_live = _build_live
    current_app._target_known_drops_browse = _target_known_drops_browse
    current_app._target_known_drop_details = _target_known_drop_details
    setattr(current_app, _TARGET_KNOWN_DROPS_MARKER, True)
