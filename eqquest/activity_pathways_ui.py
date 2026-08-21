from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .activity_pathway_navigation import pathway_contact_navigation
from .activity_pathways import (
    ActivityPathwayEngine,
    PathwayEvidence,
    PathwaySuggestion,
    pathway_detail_text,
)
from .knowledge_location_ui import ask_knowledge_map_choice, ask_knowledge_route_choice
from .live_composition import chain_live_build
from .live_navigation import handoff_to_travel, open_exact_knowledge_entity
from .objective_reviewed_item_sources import (
    quest_objective_navigation_with_reviewed_sources,
)
from .session_activity import session_activity_summary, session_activity_text


_ACTIVITY_PATHWAYS_MARKER = "_everquestie_activity_pathways_ui"


def direct_pathway_objective_evidence(
    suggestion: PathwaySuggestion,
) -> tuple[PathwayEvidence, ...]:
    """Return only exact structured quest-step matches from one pathway suggestion."""
    return tuple(
        evidence
        for evidence in suggestion.evidence
        if evidence.path_kind == "direct_objective" and int(evidence.step_order) > 0
    )


def pathway_objective_evidence_labels(
    evidence_rows: tuple[PathwayEvidence, ...],
) -> tuple[str, ...]:
    labels: list[str] = []
    for evidence in evidence_rows:
        action = "kill" if evidence.event_kind == "kill" else evidence.event_kind or "objective"
        zone = f" — {evidence.step_zone}" if evidence.step_zone else ""
        labels.append(
            f"Step {evidence.step_order}: {evidence.step_description} "
            f"[{action}: {evidence.subject}]{zone}"
        )
    return tuple(labels)


class _PathwayObjectiveDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent,
        *,
        suggestion: PathwaySuggestion,
        evidence_rows: tuple[PathwayEvidence, ...],
    ):
        self.suggestion = suggestion
        self.evidence_rows = evidence_rows
        self.result: PathwayEvidence | None = None
        self._listbox = None
        super().__init__(parent, title=f"Choose matched objective — {suggestion.quest_name}")

    def body(self, master):
        ttk.Label(
            master,
            text=(
                f"Your current activity matched multiple exact structured objectives for "
                f"{self.suggestion.quest_name}.\n"
                "Choose the exact matched step to navigate. EverQuestie will not guess one."
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._listbox = tk.Listbox(
            master,
            exportselection=False,
            width=110,
            height=min(14, max(4, len(self.evidence_rows))),
        )
        self._listbox.grid(row=1, column=0, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        for label in pathway_objective_evidence_labels(self.evidence_rows):
            self._listbox.insert("end", label)
        if self.evidence_rows:
            self._listbox.selection_set(0)
            self._listbox.activate(0)
        self._listbox.bind("<Double-1>", lambda _event: self.ok())
        return self._listbox

    def buttonbox(self):
        box = ttk.Frame(self)
        ttk.Button(box, text="Navigate match", width=14, command=self.ok).pack(
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
        if 0 <= index < len(self.evidence_rows):
            self.result = self.evidence_rows[index]


def ask_pathway_objective_evidence(
    parent,
    suggestion: PathwaySuggestion,
) -> PathwayEvidence | None:
    """Choose one exact direct objective match, prompting only when necessary."""
    rows = direct_pathway_objective_evidence(suggestion)
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    dialog = _PathwayObjectiveDialog(
        parent,
        suggestion=suggestion,
        evidence_rows=rows,
    )
    return dialog.result


def install_activity_pathways_ui() -> None:
    """Add evidence-backed live activity opportunities without changing quest state."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _ACTIVITY_PATHWAYS_MARKER, False):
        return

    current_start = current_app._start
    current_stop = current_app._stop

    def _build_activity_pathways(self) -> None:
        self.activity_pathway_engine = ActivityPathwayEngine(self.db)
        boundary = self.activity_pathway_engine.latest_observed_event_id()
        self.activity_pathway_engine.reset_session(boundary)
        self._activity_session_start_event_id = boundary
        self._activity_session_start_zone = getattr(self.state_model, "current_zone", None)
        self._activity_pathway_by_item: dict[str, PathwaySuggestion] = {}
        self._activity_pathway_signature = None

        self.live_tab.rowconfigure(1, weight=0)
        panel = ttk.LabelFrame(self.live_tab, text="Potential Pathways", padding=6)
        panel.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)

        self.activity_pathway_status = tk.StringVar(
            value=(
                "Start monitoring to discover source-backed quest opportunities from "
                "exact kill and loot activity. Nothing is auto-tracked."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.activity_pathway_status,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        columns = ("why", "score")
        self.activity_pathway_tree = ttk.Treeview(
            panel,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            height=4,
        )
        self.activity_pathway_tree.heading("#0", text="Quest")
        self.activity_pathway_tree.heading("why", text="Why it appeared")
        self.activity_pathway_tree.heading("score", text="Signal")
        self.activity_pathway_tree.column("#0", width=290, minwidth=180, stretch=True)
        self.activity_pathway_tree.column("why", width=430, minwidth=220, stretch=True)
        self.activity_pathway_tree.column(
            "score", width=70, minwidth=60, stretch=False, anchor="center"
        )
        self.activity_pathway_tree.grid(row=1, column=0, sticky="ew")
        scroll = ttk.Scrollbar(
            panel, orient="vertical", command=self.activity_pathway_tree.yview
        )
        scroll.grid(row=1, column=1, sticky="ns")
        self.activity_pathway_tree.configure(yscrollcommand=scroll.set)
        self.activity_pathway_tree.bind(
            "<Double-1>", lambda _event: self._activity_pathway_view_selected()
        )

        buttons = ttk.Frame(panel)
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(
            buttons,
            text="View quest",
            command=self._activity_pathway_view_selected,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="Track quest",
            command=self._activity_pathway_track_selected,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Navigate contact",
            command=self._activity_pathway_navigate_contact,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Navigate match",
            command=self._activity_pathway_navigate_match,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Why this?",
            command=self._activity_pathway_explain_selected,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Session recap",
            command=self._activity_session_recap,
        ).pack(side="left", padx=(6, 0))

        self.after(1000, self._activity_pathway_tick)

    def _selected_pathway(self) -> PathwaySuggestion | None:
        tree = getattr(self, "activity_pathway_tree", None)
        if tree is None:
            return None
        selected = tree.selection()
        if not selected:
            return None
        return getattr(self, "_activity_pathway_by_item", {}).get(selected[0])

    def _activity_pathway_view_selected(self) -> None:
        suggestion = _selected_pathway(self)
        if suggestion is None:
            return
        open_exact_knowledge_entity(self, int(suggestion.quest_id))

    def _activity_pathway_track_selected(self) -> None:
        suggestion = _selected_pathway(self)
        if suggestion is None:
            return
        self._track_and_reconcile(
            int(suggestion.quest_id),
            announce="PATHWAY | tracking suggested quest",
        )
        self._refresh_guidance()
        self._refresh_activity_pathways(force=True)

    def _activity_pathway_navigate_contact(self) -> None:
        suggestion = _selected_pathway(self)
        if suggestion is None:
            self.status.set("Select a Potential Pathway first.")
            return

        result = pathway_contact_navigation(
            self.db,
            int(suggestion.quest_id),
            getattr(self.state_model, "current_zone", None),
        )
        if result.map_ready:
            choice = ask_knowledge_map_choice(
                self,
                f"{result.quest_name} — {result.contact_kind}",
                result.current_zone_name,
                result.map_choices,
            )
            if choice is None:
                self.status.set("Pathway contact map selection cancelled.")
                return
            self._focus_navigation_map_target(
                choice.zone_name,
                choice.x,
                choice.y,
                choice.z,
                choice.map_label,
            )
            self.status.set(
                f"Pathway {result.contact_kind} mapped: {choice.location_entity_name}."
            )
            return

        if result.route_ready:
            choice = ask_knowledge_route_choice(
                self,
                f"{result.quest_name} — {result.contact_kind}",
                result.current_zone_name,
                result.route_choices,
            )
            if choice is None:
                self.status.set("Pathway contact route selection cancelled.")
                return

            routed = handoff_to_travel(self, choice.zone_name)
            if routed is None:
                self.status.set("Travel routing is not connected in this application surface.")
                return
            if routed:
                self.status.set(
                    f"Travel route opened to {choice.zone_name} for pathway "
                    f"{result.contact_kind}."
                )
            else:
                self.status.set(
                    f"No confirmed route to {choice.zone_name} is currently available; "
                    "see Travel for details."
                )
            return

        self.status.set(result.reason)

    def _activity_pathway_navigate_match(self) -> None:
        suggestion = _selected_pathway(self)
        if suggestion is None:
            self.status.set("Select a Potential Pathway first.")
            return

        direct = direct_pathway_objective_evidence(suggestion)
        if not direct:
            self.status.set(
                f"{suggestion.quest_name}: this pathway is source-backed through a "
                "relationship chain, but it has no exact structured matched step to "
                "navigate. Use Navigate contact or View quest."
            )
            return

        evidence = ask_pathway_objective_evidence(self, suggestion)
        if evidence is None:
            self.status.set("Potential Pathway matched-objective selection cancelled.")
            return

        result = quest_objective_navigation_with_reviewed_sources(
            self.db,
            int(suggestion.quest_id),
            getattr(self.state_model, "current_zone", None),
            step_order=int(evidence.step_order),
        )
        if result.map_ready:
            choice = ask_knowledge_map_choice(
                self,
                f"{suggestion.quest_name} — matched objective",
                result.current_zone_name,
                result.map_choices,
            )
            if choice is None:
                self.status.set("Matched objective map selection cancelled.")
                return
            self._focus_navigation_map_target(
                choice.zone_name,
                choice.x,
                choice.y,
                choice.z,
                choice.map_label,
            )
            self.status.set(
                f"Mapped exact matched objective: {choice.location_entity_name}."
            )
            return

        if result.route_ready:
            choice = ask_knowledge_route_choice(
                self,
                f"{suggestion.quest_name} — matched objective",
                result.current_zone_name,
                result.route_choices,
            )
            if choice is None:
                self.status.set("Matched objective route selection cancelled.")
                return
            routed = handoff_to_travel(self, choice.zone_name)
            if routed is None:
                self.status.set("Travel routing is not connected in this application surface.")
                return
            if routed:
                self.status.set(
                    f"Travel route opened to {choice.zone_name} for exact matched objective "
                    f"step {evidence.step_order}."
                )
            else:
                self.status.set(
                    f"No confirmed route to {choice.zone_name} is currently available; "
                    "see Travel for details."
                )
            return

        reason = str(result.reason or "No safe exact matched-objective location is known.")
        self.status.set(reason.replace("Active objective", "Matched objective"))

    def _activity_pathway_explain_selected(self) -> None:
        suggestion = _selected_pathway(self)
        if suggestion is None:
            return
        messagebox.showinfo("Potential Pathway", pathway_detail_text(suggestion))

    def _activity_session_recap(self) -> None:
        boundary = int(getattr(self, "_activity_session_start_event_id", 0) or 0)
        summary = session_activity_summary(
            self.db,
            boundary,
            starting_zone=getattr(self, "_activity_session_start_zone", None),
            current_zone=getattr(self.state_model, "current_zone", None),
            pathway_count=len(getattr(self, "_activity_pathway_by_item", {})),
        )
        messagebox.showinfo("EverQuestie Session Recap", session_activity_text(summary))

    def _refresh_activity_pathways(self, *, force: bool = False) -> None:
        engine = getattr(self, "activity_pathway_engine", None)
        tree = getattr(self, "activity_pathway_tree", None)
        if engine is None or tree is None:
            return

        monitoring = getattr(self, "tailer", None) is not None
        if monitoring:
            engine.refresh_observations()

        suggestions = engine.suggestions(
            getattr(self.state_model, "current_zone", None),
            limit=10,
        )
        signature = tuple(
            (
                suggestion.quest_id,
                suggestion.score,
                tuple(
                    (
                        e.event_kind,
                        e.subject,
                        e.observed_count,
                        e.step_order,
                        e.path_kind,
                        e.related_item,
                    )
                    for e in suggestion.evidence
                ),
            )
            for suggestion in suggestions
        )
        if force or signature != getattr(self, "_activity_pathway_signature", None):
            previous = tree.selection()
            previous_quest = None
            if previous:
                old = getattr(self, "_activity_pathway_by_item", {}).get(previous[0])
                previous_quest = old.quest_id if old is not None else None

            tree.delete(*tree.get_children(""))
            self._activity_pathway_by_item = {}
            for suggestion in suggestions:
                iid = f"pathway:{suggestion.quest_id}"
                strength = (
                    "high"
                    if suggestion.score >= 90
                    else "medium"
                    if suggestion.score >= 55
                    else "new"
                )
                tree.insert(
                    "",
                    "end",
                    iid=iid,
                    text=suggestion.quest_name,
                    values=(suggestion.primary_reason, strength),
                )
                self._activity_pathway_by_item[iid] = suggestion
                if previous_quest == suggestion.quest_id:
                    tree.selection_set(iid)
                    tree.focus(iid)
            self._activity_pathway_signature = signature

        if suggestions:
            prefix = "Watching live activity" if monitoring else "Last monitoring session"
            self.activity_pathway_status.set(
                f"{prefix}: {len(suggestions)} potential quest pathway(s). "
                "Exact structured/source-backed relationships only; nothing is auto-tracked."
            )
        elif monitoring:
            self.activity_pathway_status.set(
                "Watching live activity. Potential pathways appear when exact kill/loot "
                "observations match structured objectives or reviewed source-backed chains."
            )
        else:
            self.activity_pathway_status.set(
                "Start monitoring to discover source-backed quest opportunities from "
                "exact kill and loot activity. Nothing is auto-tracked."
            )

    def _activity_pathway_tick(self) -> None:
        """Refresh Live intelligence only when relevant new observations exist.

        The composed pathway refresh also drives Zone Opportunities, Recent Loot,
        activity clustering and Target Intelligence.  Running that whole stack once
        per second regardless of input can monopolize Tk's UI thread against a large
        packaged knowledge snapshot.
        """
        engine = getattr(self, "activity_pathway_engine", None)
        monitoring = getattr(self, "tailer", None) is not None

        if engine is not None and monitoring:
            cursor = int(getattr(engine, "_last_event_id", 0) or 0)

            row = self.db.conn.execute(
                """
                SELECT
                    COALESCE(MAX(id), 0) AS max_id,
                    COALESCE(
                        MAX(
                            CASE
                                WHEN kind IN (
                                    'welcome',
                                    'zone',
                                    'kill',
                                    'loot',
                                    'target_npc',
                                    'consider',
                                    'task_assigned',
                                    'task_update'
                                )
                                THEN 1
                                ELSE 0
                            END
                        ),
                        0
                    ) AS relevant
                FROM observed_events
                WHERE id > ?
                """,
                (cursor,),
            ).fetchone()

            max_id = int(row["max_id"] if row is not None else cursor)
            relevant = bool(int(row["relevant"] if row is not None else 0))

            if relevant:
                self._refresh_activity_pathways()
            elif max_id > cursor:
                # ActivityPathwayEngine ignores these event kinds anyway. Advance
                # its cursor so ordinary combat/chat spam cannot accumulate into a
                # large future catch-up scan.
                engine._last_event_id = max_id

        self.after(500, self._activity_pathway_tick)

    def _start(self) -> None:
        current_start(self)
        engine = getattr(self, "activity_pathway_engine", None)
        if engine is not None and getattr(self, "tailer", None) is not None:
            boundary = engine.latest_observed_event_id()
            self._activity_session_start_event_id = boundary
            self._activity_session_start_zone = getattr(
                self.state_model,
                "current_zone",
                None,
            )
            engine.reset_session(
                boundary,
                starting_zone=self._activity_session_start_zone,
            )
            self._activity_pathway_signature = None

            # Starting the tail establishes a session boundary; it does not create
            # any new pathway evidence.  Do not synchronously force the entire
            # composed Live intelligence stack here.  The event-driven tick will
            # refresh after the first relevant live observation.
            status = getattr(self, "activity_pathway_status", None)
            if status is not None:
                status.set(
                    "Monitoring live activity. Potential pathways appear when "
                    "relevant source-backed kill/loot observations arrive."
                )

    def _stop(self) -> None:
        """Stop monitoring without running expensive knowledge projections.

        Stopping creates no new evidence.  Preserve the already-rendered session
        results and update only the lightweight status text.
        """
        current_stop(self)

        status = getattr(self, "activity_pathway_status", None)
        if status is None:
            return

        visible = len(
            getattr(self, "_activity_pathway_by_item", {})
        )

        if visible:
            status.set(
                f"Last monitoring session: {visible} potential pathway(s). "
                "Nothing is auto-tracked."
            )
        else:
            status.set(
                "Monitoring stopped. No potential pathways were recorded "
                "for the last session."
            )

    chain_live_build(current_app, _build_activity_pathways)
    current_app._selected_activity_pathway = _selected_pathway
    current_app._activity_pathway_view_selected = _activity_pathway_view_selected
    current_app._activity_pathway_track_selected = _activity_pathway_track_selected
    current_app._activity_pathway_navigate_contact = _activity_pathway_navigate_contact
    current_app._activity_pathway_navigate_match = _activity_pathway_navigate_match
    current_app._activity_pathway_explain_selected = _activity_pathway_explain_selected
    current_app._activity_session_recap = _activity_session_recap
    current_app._refresh_activity_pathways = _refresh_activity_pathways
    current_app._activity_pathway_tick = _activity_pathway_tick
    current_app._start = _start
    current_app._stop = _stop
    setattr(current_app, _ACTIVITY_PATHWAYS_MARKER, True)