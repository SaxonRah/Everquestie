from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .knowledge_location_ui import ask_knowledge_map_choice, ask_knowledge_route_choice
from .knowledge_map_choices import knowledge_map_choices, knowledge_route_choices
from .live_composition import chain_activity_pathways_refresh
from .live_navigation import handoff_to_travel, open_exact_knowledge_entity
from .target_intelligence import (
    TargetIntelligence,
    current_target_intelligence,
    target_intelligence_compact_text,
    target_intelligence_detail_text,
)
from .target_quest_relevance import (
    TargetQuestRelevance,
    target_quest_relevance,
    target_quest_relevance_text,
)
from .world_profiles import active_world_profile_id


_TARGET_INTELLIGENCE_MARKER = "_everquestie_target_intelligence_ui"


def install_target_intelligence_ui() -> None:
    """Add exact current-target context, quest relevance and safe navigation to Live."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _TARGET_INTELLIGENCE_MARKER, False):
        return

    current_build_live = current_app._build_live

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

        self.target_quest_status = tk.StringVar(
            value="Quest relevance appears after an exact NPC target resolves."
        )
        ttk.Label(
            panel,
            textvariable=self.target_quest_status,
            justify="left",
            wraplength=1060,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 3))

        columns = ("relevance", "state")
        self.target_quest_tree = ttk.Treeview(
            panel,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            height=4,
        )
        self.target_quest_tree.heading("#0", text="Quest")
        self.target_quest_tree.heading("relevance", text="Why this target matters")
        self.target_quest_tree.heading("state", text="State")
        self.target_quest_tree.column("#0", width=300, minwidth=180, stretch=True)
        self.target_quest_tree.column("relevance", width=490, minwidth=240, stretch=True)
        self.target_quest_tree.column("state", width=155, minwidth=110, stretch=False)
        self.target_quest_tree.grid(row=2, column=0, sticky="ew")
        scroll = ttk.Scrollbar(panel, orient="vertical", command=self.target_quest_tree.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        self.target_quest_tree.configure(yscrollcommand=scroll.set)
        self.target_quest_tree.bind(
            "<Double-1>", lambda _event: self._target_quest_view_selected()
        )

        quest_buttons = ttk.Frame(panel)
        quest_buttons.grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(
            quest_buttons,
            text="View quest",
            command=self._target_quest_view_selected,
        ).pack(side="left")
        ttk.Button(
            quest_buttons,
            text="Track quest",
            command=self._target_quest_track_selected,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            quest_buttons,
            text="Why relevant?",
            command=self._target_quest_explain_selected,
        ).pack(side="left", padx=(6, 0))

        self._target_intelligence_value: TargetIntelligence | None = None
        self._target_intelligence_signature = None
        self._target_quest_relevance_key = None
        self._target_quest_by_item: dict[str, TargetQuestRelevance] = {}
        self._refresh_target_intelligence(force=True)

    def _target_intelligence_view(self) -> None:
        value = getattr(self, "_target_intelligence_value", None)
        if value is None or not value.resolved or value.entity_id is None:
            self.status.set("No exact current NPC target is available to open in Knowledge.")
            return

        open_exact_knowledge_entity(self, int(value.entity_id))

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
            route = ask_knowledge_route_choice(
                self,
                value.canonical_name,
                choices.current_zone_name,
                routes,
            )
            if route is None:
                self.status.set("Target route selection cancelled.")
                return

            routed = handoff_to_travel(self, route.zone_name)
            if routed is None:
                self.status.set("Travel routing is not connected in this application surface.")
                return
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
                    getattr(self, "_activity_session_start_event_id", 0) or 0
                ),
            )
        messagebox.showinfo(
            "Target Intelligence",
            target_intelligence_detail_text(value),
        )

    def _selected_target_quest(self) -> TargetQuestRelevance | None:
        tree = getattr(self, "target_quest_tree", None)
        if tree is None:
            return None
        selected = tree.selection()
        if not selected:
            return None
        return getattr(self, "_target_quest_by_item", {}).get(selected[0])

    def _target_quest_view_selected(self) -> None:
        relevance = _selected_target_quest(self)
        if relevance is None:
            self.status.set("Select a target-related quest first.")
            return
        open_exact_knowledge_entity(self, int(relevance.quest_id))

    def _target_quest_track_selected(self) -> None:
        relevance = _selected_target_quest(self)
        if relevance is None:
            self.status.set("Select a target-related quest first.")
            return
        if relevance.tracked:
            self.status.set(f"{relevance.quest_name} is already tracked.")
            return
        self._track_and_reconcile(
            int(relevance.quest_id),
            announce="TARGET | tracking source-backed related quest",
        )
        self._refresh_guidance()
        self._target_quest_relevance_key = None
        self._refresh_activity_pathways(force=True)

    def _target_quest_explain_selected(self) -> None:
        relevance = _selected_target_quest(self)
        if relevance is None:
            self.status.set("Select a target-related quest first.")
            return
        messagebox.showinfo(
            "Target Quest Relevance",
            target_quest_relevance_text(relevance),
        )

    def _render_target_quest_relevance(
        self,
        value: TargetIntelligence,
        rows: tuple[TargetQuestRelevance, ...],
    ) -> None:
        tree = getattr(self, "target_quest_tree", None)
        status = getattr(self, "target_quest_status", None)
        if tree is None or status is None:
            return
        children = tree.get_children()
        if children:
            tree.delete(*children)
        self._target_quest_by_item = {}

        if not value.resolved or value.entity_id is None:
            status.set("Quest relevance appears after an exact NPC target resolves.")
            return
        if not rows:
            status.set(
                "No reviewed source-backed quest relationship is compiled for this exact target. "
                "That is a knowledge gap, not a claim that the NPC has no quest use."
            )
            return

        progress_rows = sum(1 for relevance in rows if relevance.tracked_progress_label)
        if progress_rows:
            status.set(
                f"{progress_rows} tracked quest objective(s) correspond to this exact target; "
                "progress is live player state. Other rows are source-backed relevance only."
            )
        else:
            status.set(
                "Exact source-backed quest relevance for this target. Nothing is auto-tracked."
            )

        for relevance in rows:
            item_id = f"quest:{relevance.quest_id}"
            self._target_quest_by_item[item_id] = relevance
            reason = relevance.primary_reason
            if len(relevance.reasons) > 1:
                reason += f" + {len(relevance.reasons) - 1} more"
            state = "tracked" if relevance.tracked else "untracked"
            if relevance.tracked_progress_label:
                state += f" / {relevance.tracked_progress_label}"
            if relevance.profile_status not in {"", "available"}:
                state += f" / {relevance.profile_status}"
            tree.insert(
                "",
                "end",
                iid=item_id,
                text=relevance.quest_name,
                values=(reason, state),
            )

    def _refresh_target_intelligence(self, *, force: bool = False) -> None:
        status = getattr(self, "target_intelligence_status", None)
        if status is None:
            return

        value = current_target_intelligence(
            self.db,
            after_event_id=int(
                getattr(self, "_activity_session_start_event_id", 0) or 0
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
            value.profile_reason,
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

        profile_id = active_world_profile_id(self.db)
        engine = getattr(self, "activity_pathway_engine", None)
        observation_cursor = int(getattr(engine, "_last_event_id", 0) or 0)
        relevance_key = (
            int(value.entity_id) if value.resolved and value.entity_id is not None else None,
            profile_id,
            observation_cursor,
        )
        if force or relevance_key != getattr(self, "_target_quest_relevance_key", None):
            rows = (
                target_quest_relevance(
                    self.db,
                    int(value.entity_id),
                    profile_id=profile_id,
                )
                if value.resolved and value.entity_id is not None
                else ()
            )
            self._render_target_quest_relevance(value, rows)
            self._target_quest_relevance_key = relevance_key

    current_app._build_live = _build_live
    current_app._target_intelligence_view = _target_intelligence_view
    current_app._target_intelligence_navigate = _target_intelligence_navigate
    current_app._target_intelligence_details = _target_intelligence_details
    current_app._target_quest_view_selected = _target_quest_view_selected
    current_app._target_quest_track_selected = _target_quest_track_selected
    current_app._target_quest_explain_selected = _target_quest_explain_selected
    current_app._render_target_quest_relevance = _render_target_quest_relevance
    current_app._refresh_target_intelligence = _refresh_target_intelligence
    # Activity Intelligence owns the monitoring-session boundary and refresh cadence.
    # Target quest relevance rides the same pass so it cannot drift into a second
    # polling loop or disagree about where this monitoring session began.
    chain_activity_pathways_refresh(current_app, _refresh_target_intelligence)
    setattr(current_app, _TARGET_INTELLIGENCE_MARKER, True)