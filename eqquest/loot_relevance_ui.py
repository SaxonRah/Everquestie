from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .loot_relevance import LootQuestUse, LootRelevance, loot_relevance_text, recent_loot_relevance


_LOOT_RELEVANCE_MARKER = "_everquestie_loot_relevance_ui"


def install_loot_relevance_ui() -> None:
    """Add source-backed quest relevance for recently looted items to Live."""
    from . import app as app_module

    current_app = app_module.EverQuestieApp
    if getattr(current_app, _LOOT_RELEVANCE_MARKER, False):
        return

    current_build_live = current_app._build_live
    current_refresh_pathways = current_app._refresh_activity_pathways

    def _build_live(self) -> None:
        current_build_live(self)

        panel = ttk.LabelFrame(self.live_tab, text="Recent Loot Relevance", padding=6)
        panel.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        panel.columnconfigure(0, weight=1)

        self.loot_relevance_status = tk.StringVar(
            value=(
                "Start monitoring to see source-backed quest uses for items you loot. "
                "No displayed use never means an item is automatically vendor trash."
            )
        )
        ttk.Label(
            panel,
            textvariable=self.loot_relevance_status,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))

        self.loot_relevance_tree = ttk.Treeview(
            panel,
            columns=("quest", "use", "observed"),
            show="tree headings",
            selectmode="browse",
            height=4,
        )
        self.loot_relevance_tree.heading("#0", text="Looted item")
        self.loot_relevance_tree.heading("quest", text="Known quest use")
        self.loot_relevance_tree.heading("use", text="Relationship")
        self.loot_relevance_tree.heading("observed", text="Session")
        self.loot_relevance_tree.column("#0", width=260, minwidth=160, stretch=True)
        self.loot_relevance_tree.column("quest", width=300, minwidth=180, stretch=True)
        self.loot_relevance_tree.column("use", width=150, minwidth=120, stretch=False)
        self.loot_relevance_tree.column(
            "observed", width=75, minwidth=65, stretch=False, anchor="center"
        )
        self.loot_relevance_tree.grid(row=1, column=0, sticky="ew")
        scroll = ttk.Scrollbar(
            panel,
            orient="vertical",
            command=self.loot_relevance_tree.yview,
        )
        scroll.grid(row=1, column=1, sticky="ns")
        self.loot_relevance_tree.configure(yscrollcommand=scroll.set)
        self.loot_relevance_tree.bind(
            "<Double-1>", lambda _event: self._loot_relevance_view_item()
        )

        buttons = ttk.Frame(panel)
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        ttk.Button(
            buttons,
            text="View item",
            command=self._loot_relevance_view_item,
        ).pack(side="left")
        ttk.Button(
            buttons,
            text="View quest",
            command=self._loot_relevance_view_quest,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Track quest",
            command=self._loot_relevance_track_quest,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            buttons,
            text="Why relevant?",
            command=self._loot_relevance_explain,
        ).pack(side="left", padx=(6, 0))

        self._loot_relevance_by_item: dict[str, tuple[LootRelevance, LootQuestUse]] = {}
        self._loot_relevance_signature = None

    def _selected_loot_relevance(self) -> tuple[LootRelevance, LootQuestUse] | None:
        tree = getattr(self, "loot_relevance_tree", None)
        if tree is None:
            return None
        selected = tree.selection()
        if not selected:
            return None
        return getattr(self, "_loot_relevance_by_item", {}).get(selected[0])

    def _open_exact(self, entity_id: int) -> None:
        opener = getattr(self, "_open_knowledge_entity_exact", None)
        if callable(opener):
            opener(int(entity_id))
        else:
            self._map_entity_selected(int(entity_id))

    def _loot_relevance_view_item(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            return
        item, _use = selected
        _open_exact(self, int(item.item_id))

    def _loot_relevance_view_quest(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            return
        _item, use = selected
        _open_exact(self, int(use.quest_id))

    def _loot_relevance_track_quest(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            return
        _item, use = selected
        if use.tracked:
            self.status.set(f"{use.quest_name} is already tracked.")
            return
        self._track_and_reconcile(
            int(use.quest_id),
            announce="LOOT RELEVANCE | tracking selected quest",
        )
        self._refresh_guidance()
        self._refresh_activity_pathways(force=True)

    def _loot_relevance_explain(self) -> None:
        selected = _selected_loot_relevance(self)
        if selected is None:
            return
        item, _use = selected
        messagebox.showinfo("Recent Loot Relevance", loot_relevance_text(item))

    def _refresh_loot_relevance(self, *, force: bool = False) -> None:
        tree = getattr(self, "loot_relevance_tree", None)
        status = getattr(self, "loot_relevance_status", None)
        if tree is None or status is None:
            return

        boundary = int(getattr(self, "_activity_session_start_event_id", 0) or 0)
        rows = recent_loot_relevance(self.db, boundary, limit_items=10)
        signature = tuple(
            (
                item.item_id,
                item.observed_count,
                item.last_event_id,
                tuple(
                    (
                        use.quest_id,
                        use.relation,
                        use.quantity,
                        use.tracked,
                        use.profile_status,
                    )
                    for use in item.uses
                ),
            )
            for item in rows
        )
        if force or signature != getattr(self, "_loot_relevance_signature", None):
            previous = tree.selection()
            previous_key = previous[0] if previous else None
            tree.delete(*tree.get_children(""))
            self._loot_relevance_by_item = {}

            for item in rows:
                for use in item.uses:
                    iid = f"loot-relevance:{item.item_id}:{use.quest_id}:{use.relation}"
                    relationship = use.relation_label
                    if use.quantity:
                        relationship += f" x{use.quantity}"
                    if use.tracked:
                        relationship += "; tracked"
                    if use.profile_status not in {"", "available"}:
                        relationship += f"; {use.profile_status}"
                    tree.insert(
                        "",
                        "end",
                        iid=iid,
                        text=item.item_name,
                        values=(
                            use.quest_name,
                            relationship,
                            f"x{item.observed_count}",
                        ),
                    )
                    self._loot_relevance_by_item[iid] = (item, use)
                    if iid == previous_key:
                        tree.selection_set(iid)
                        tree.focus(iid)
            self._loot_relevance_signature = signature

        monitoring = getattr(self, "tailer", None) is not None
        if rows:
            quest_ids = {
                int(use.quest_id)
                for item in rows
                for use in item.uses
            }
            prefix = "Watching live loot" if monitoring else "Last monitoring session"
            status.set(
                f"{prefix}: {len(rows)} looted item(s) have {len(quest_ids)} known "
                "profile-compatible quest connection(s). Exact source-backed relationships only."
            )
        elif monitoring:
            status.set(
                "Watching live loot. Relevant items appear only when an exact canonical item "
                "has a reviewed source-backed quest relationship. No match does not mean vendor trash."
            )
        else:
            status.set(
                "Start monitoring to see source-backed quest uses for items you loot. "
                "No displayed use never means an item is automatically vendor trash."
            )

    def _refresh_activity_pathways(self, *, force: bool = False) -> None:
        current_refresh_pathways(self, force=force)
        _refresh_loot_relevance(self, force=force)

    current_app._build_live = _build_live
    current_app._selected_loot_relevance = _selected_loot_relevance
    current_app._loot_relevance_view_item = _loot_relevance_view_item
    current_app._loot_relevance_view_quest = _loot_relevance_view_quest
    current_app._loot_relevance_track_quest = _loot_relevance_track_quest
    current_app._loot_relevance_explain = _loot_relevance_explain
    current_app._refresh_loot_relevance = _refresh_loot_relevance
    current_app._refresh_activity_pathways = _refresh_activity_pathways
    setattr(current_app, _LOOT_RELEVANCE_MARKER, True)
