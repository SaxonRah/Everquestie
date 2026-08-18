from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .knowledge_location_ui import ask_knowledge_map_choice, ask_knowledge_route_choice
from .live_composition import chain_activity_pathways_refresh
from .live_navigation import handoff_to_travel
from .quest_objective_navigation import tracked_quest_objective_navigation
from .zone_opportunities import (
    ZoneOpportunity,
    ZoneOpportunityStep,
    zone_opportunities,
    zone_opportunity_text,
)


_ZONE_OPPORTUNITIES_MARKER = "_everquestie_zone_opportunities_ui"


def zone_opportunity_step_labels(
    steps: tuple[ZoneOpportunityStep, ...],
) -> tuple[str, ...]:
    """Render exact structured steps without reinterpreting their meaning."""
    labels: list[str] = []
    for step in steps:
        event = f" [{step.event_kind}]" if step.event_kind else ""
        labels.append(f"Step {step.step_order}: {step.description}{event}")
    return tuple(labels)


class _ZoneOpportunityStepDialog(simpledialog.Dialog):
    def __init__(self, parent, *, opportunity: ZoneOpportunity):
        self.opportunity = opportunity
        self.result: ZoneOpportunityStep | None = None
        self._listbox = None
        super().__init__(parent, title=f"Choose objective — {opportunity.quest_name}")

    def body(self, master):
        ttk.Label(
            master,
            text=(
                f"{self.opportunity.quest_name} has multiple exact structured objectives "
                f"in {self.opportunity.zone_name}.\n"
                "Choose the objective you want to map. EverQuestie will not guess one."
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._listbox = tk.Listbox(
            master,
            exportselection=False,
            width=100,
            height=min(14, max(4, len(self.opportunity.steps))),
        )
        self._listbox.grid(row=1, column=0, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        for label in zone_opportunity_step_labels(self.opportunity.steps):
            self._listbox.insert("end", label)
        if self.opportunity.steps:
            self._listbox.selection_set(0)
            self._listbox.activate(0)
        self._listbox.bind("<Double-1>", lambda _event: self.ok())
        return self._listbox

    def buttonbox(self):
        box = ttk.Frame(self)
        ttk.Button(box, text="Map objective", width=14, command=self.ok).pack(
            side="left", padx=5, pady=5
        )
        ttk.Button(box, text="Cancel", width=10, command=self.cancel).pack(
            side="left", padx=5, pady=5
        )
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)
        box.pack()

    def validate(self) -> bool:
        return bool(self._listbox is not None and self._listbox.curselection())

    def apply(self) -> None:
        if self._listbox is None:
            return
        selected = self._listbox.curselection()
        if not selected:
            return
        index = int(selected[0])
        if 0 <= index < len(self.opportunity.steps):
            self.result = self.opportunity.steps[index]


def ask_zone_opportunity_step(
    parent,
    opportunity: ZoneOpportunity,
) -> ZoneOpportunityStep | None:
    """Choose one exact structured objective, prompting only when choice exists."""
    steps = tuple(opportunity.steps)
    if not steps:
        return None
    if len(steps) == 1:
        return steps[0]
    dialog = _ZoneOpportunityStepDialog(parent, opportunity=opportunity)
    return dialog.result


def install_zone_opportunities_ui() -> None:
    """Add location-triggered untracked quest discovery to the Live tab."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _ZONE_OPPORTUNITIES_MARKER, False):
        return

    current_build_live = current_app._build_live

    def _build_live(self) -> None:
        current_build_live(self)

        panel = ttk.LabelFrame(self.live_tab, text="What can I accomplish from here?", padding=6)
        panel.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)
        self._zone_opportunity_by_item: dict[str, ZoneOpportunity] = {}
        self._zone_opportunity_signature = None
        self.zone_opportunity_status = tk.StringVar(
            value=(
                "Enter a known zone to see untracked quests with explicit structured "
                "objectives there. Location alone never means the quest is owned."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.zone_opportunity_status,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        self.zone_opportunity_tree = ttk.Treeview(
            panel,
            columns=("objectives", "context"),
            show="tree headings",
            selectmode="browse",
            height=3,
        )
        self.zone_opportunity_tree.heading("#0", text="Quest")
        self.zone_opportunity_tree.heading("objectives", text="Objectives here")
        self.zone_opportunity_tree.heading("context", text="Context")
        self.zone_opportunity_tree.column("#0", width=300, minwidth=180, stretch=True)
        self.zone_opportunity_tree.column(
            "objectives", width=105, minwidth=90, stretch=False, anchor="center"
        )
        self.zone_opportunity_tree.column("context", width=390, minwidth=220, stretch=True)
        self.zone_opportunity_tree.grid(row=1, column=0, sticky="ew")
        scroll = ttk.Scrollbar(
            panel,
            orient="vertical",
            command=self.zone_opportunity_tree.yview,
        )
        scroll.grid(row=1, column=1, sticky="ns")
        self.zone_opportunity_tree.configure(yscrollcommand=scroll.set)
        self.zone_opportunity_tree.bind(
            "<Double-1>", lambda _event: self._zone_opportunity_view_selected()
        )

        buttons = ttk.Frame(panel)
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(
            buttons,
            text="View quest",
            command=self._zone_opportunity_view_selected,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="Track quest",
            command=self._zone_opportunity_track_selected,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Map objective",
            command=self._zone_opportunity_map_selected,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Why here?",
            command=self._zone_opportunity_explain_selected,
        ).pack(side="left", padx=(6, 0))

    def _selected_zone_opportunity(self) -> ZoneOpportunity | None:
        tree = getattr(self, "zone_opportunity_tree", None)
        if tree is None:
            return None
        selected = tree.selection()
        if not selected:
            return None
        return getattr(self, "_zone_opportunity_by_item", {}).get(selected[0])

    def _zone_opportunity_view_selected(self) -> None:
        opportunity = _selected_zone_opportunity(self)
        if opportunity is None:
            return
        opener = getattr(self, "_open_knowledge_entity_exact", None)
        if callable(opener):
            opener(int(opportunity.quest_id))
        else:
            self._map_entity_selected(int(opportunity.quest_id))

    def _zone_opportunity_track_selected(self) -> None:
        opportunity = _selected_zone_opportunity(self)
        if opportunity is None:
            return
        self._track_and_reconcile(
            int(opportunity.quest_id),
            announce="ZONE OPPORTUNITY | tracking selected quest",
        )
        self._refresh_guidance()
        self._refresh_activity_pathways(force=True)

    def _zone_opportunity_map_selected(self) -> None:
        opportunity = _selected_zone_opportunity(self)
        if opportunity is None:
            self.status.set("Select a Zone Opportunity first.")
            return

        step = ask_zone_opportunity_step(self, opportunity)
        if step is None:
            if opportunity.steps:
                self.status.set("Zone Opportunity objective selection cancelled.")
            else:
                self.status.set("Selected Zone Opportunity has no structured objective to map.")
            return

        result = tracked_quest_objective_navigation(
            self.db,
            int(opportunity.quest_id),
            getattr(self.state_model, "current_zone", None),
            step_order=int(step.step_order),
        )
        if result.map_ready:
            choice = ask_knowledge_map_choice(
                self,
                f"{opportunity.quest_name} — current-zone objective",
                result.current_zone_name,
                result.map_choices,
            )
            if choice is None:
                self.status.set("Zone Opportunity map selection cancelled.")
                return
            self._focus_navigation_map_target(
                choice.zone_name,
                choice.x,
                choice.y,
                choice.z,
                choice.map_label,
            )
            self.status.set(
                f"Mapped Zone Opportunity objective: {choice.location_entity_name}."
            )
            return

        if result.route_ready:
            # This should be uncommon because the qualifying step already resolved to
            # the current zone, but preserve the canonical navigation result rather than
            # guessing if source locations disagree.
            choice = ask_knowledge_route_choice(
                self,
                f"{opportunity.quest_name} — objective",
                result.current_zone_name,
                result.route_choices,
            )
            if choice is None:
                self.status.set("Zone Opportunity route selection cancelled.")
                return
            routed = handoff_to_travel(self, choice.zone_name)
            if routed is None:
                self.status.set("Travel routing is not connected in this application surface.")
                return
            if routed:
                self.status.set(f"Travel route opened to {choice.zone_name} for this objective.")
            else:
                self.status.set(
                    f"No confirmed route to {choice.zone_name} is currently available; see Travel for details."
                )
            return

        reason = str(result.reason or "No safe exact objective location is known.")
        reason = reason.replace("Active objective", "Selected objective")
        self.status.set(reason)

    def _zone_opportunity_explain_selected(self) -> None:
        opportunity = _selected_zone_opportunity(self)
        if opportunity is None:
            return
        messagebox.showinfo("Zone Opportunity", zone_opportunity_text(opportunity))

    def _refresh_zone_opportunities(self, *, force: bool = False) -> None:
        tree = getattr(self, "zone_opportunity_tree", None)
        status = getattr(self, "zone_opportunity_status", None)
        if tree is None or status is None:
            return

        current_zone = getattr(self.state_model, "current_zone", None)
        visible_pathway_ids = {
            int(suggestion.quest_id)
            for suggestion in getattr(self, "_activity_pathway_by_item", {}).values()
        }
        dismissed_ids = {
            int(value)
            for value in getattr(self, "_activity_pathway_dismissed_quests", set())
        }
        opportunities = tuple(
            row
            for row in zone_opportunities(
                self.db,
                current_zone,
                activity_quest_ids=visible_pathway_ids,
                limit=15,
            )
            if int(row.quest_id) not in dismissed_ids
        )
        signature = tuple(
            (
                row.quest_id,
                row.activity_match,
                row.profile_status,
                tuple((step.step_order, step.description, step.source_zone) for step in row.steps),
            )
            for row in opportunities
        )
        if force or signature != getattr(self, "_zone_opportunity_signature", None):
            previous = tree.selection()
            previous_quest = None
            if previous:
                old = getattr(self, "_zone_opportunity_by_item", {}).get(previous[0])
                previous_quest = old.quest_id if old is not None else None

            tree.delete(*tree.get_children(""))
            self._zone_opportunity_by_item = {}
            for row in opportunities:
                iid = f"zone-opportunity:{row.quest_id}"
                context = (
                    "recent activity match"
                    if row.activity_match
                    else "structured zone objective"
                )
                if row.profile_status not in {"available", ""}:
                    context += f"; profile {row.profile_status}"
                tree.insert(
                    "",
                    "end",
                    iid=iid,
                    text=row.quest_name,
                    values=(len(row.steps), context),
                )
                self._zone_opportunity_by_item[iid] = row
                if previous_quest == row.quest_id:
                    tree.selection_set(iid)
                    tree.focus(iid)
            self._zone_opportunity_signature = signature

        zone_text = " ".join(str(current_zone or "").split()).strip()
        if opportunities:
            status.set(
                f"{len(opportunities)} untracked quest(s) have explicit structured objectives "
                f"in {opportunities[0].zone_name}. Location-triggered discovery; quest ownership is not assumed."
            )
        elif zone_text:
            status.set(
                f"No untracked profile-compatible structured quest objectives are currently known in {zone_text}. "
                "Coverage will expand as approved quest sources finish importing."
            )
        else:
            status.set(
                "Current zone is unknown. Zone Opportunities appear only after an authoritative canonical zone is known."
            )

    current_app._build_live = _build_live
    current_app._selected_zone_opportunity = _selected_zone_opportunity
    current_app._zone_opportunity_view_selected = _zone_opportunity_view_selected
    current_app._zone_opportunity_track_selected = _zone_opportunity_track_selected
    current_app._zone_opportunity_map_selected = _zone_opportunity_map_selected
    current_app._zone_opportunity_explain_selected = _zone_opportunity_explain_selected
    current_app._refresh_zone_opportunities = _refresh_zone_opportunities
    chain_activity_pathways_refresh(current_app, _refresh_zone_opportunities)
    setattr(current_app, _ZONE_OPPORTUNITIES_MARKER, True)