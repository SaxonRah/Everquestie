from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, ttk

from .current_zone_dashboard import (
    CurrentZoneDashboard,
    CurrentZoneDashboardChoice,
)


class _CurrentZoneDashboardDialog(simpledialog.Dialog):
    def __init__(self, parent, dashboard: CurrentZoneDashboard):
        self.dashboard = dashboard
        self.choices = dashboard.choices
        self.result: CurrentZoneDashboardChoice | None = None
        self._tree = None
        super().__init__(parent, title=f"What's here — {dashboard.zone_name}")

    def body(self, master):
        summary = (
            f"{self.dashboard.zone_name}: {len(self.dashboard.entities)} known entity/entities, "
            f"{self.dashboard.located_entity_count} with location evidence, "
            f"{self.dashboard.usable_exit_count} usable exit(s), "
            f"{self.dashboard.mappable_exit_count} with source-side map coordinates.\n"
            "Knowledge is evidence-backed and may be incomplete. Select a row to open its exact entity ID."
        )
        ttk.Label(master, text=summary, justify="left", wraplength=900).grid(
            row=0, column=0, sticky="ew", pady=(0, 8)
        )

        columns = ("category", "role", "located", "source")
        self._tree = ttk.Treeview(
            master,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            height=min(18, max(6, len(self.choices))),
        )
        self._tree.heading("#0", text="Name")
        self._tree.heading("category", text="Type")
        self._tree.heading("role", text="Known role / travel evidence")
        self._tree.heading("located", text="Location / exit")
        self._tree.heading("source", text="Source")
        self._tree.column("#0", width=240, minwidth=140, stretch=True)
        self._tree.column("category", width=90, minwidth=70, stretch=False)
        self._tree.column("role", width=280, minwidth=150, stretch=True)
        self._tree.column("located", width=150, minwidth=100, stretch=False)
        self._tree.column("source", width=220, minwidth=120, stretch=True)
        self._tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(master, orient="vertical", command=self._tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self._tree.configure(yscrollcommand=scroll.set)
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)

        for index, choice in enumerate(self.choices):
            if choice.kind == "zone":
                action = (
                    "mappable exit"
                    if choice.mappable_exit
                    else "usable exit"
                    if choice.usable_exit
                    else "incoming only"
                )
            else:
                pieces = []
                if choice.location_count:
                    pieces.append(f"{choice.location_count} location row(s)")
                if choice.preview_fact_count:
                    pieces.append(f"{choice.preview_fact_count} preview fact(s)")
                action = ", ".join(pieces) or "knowledge only"
            iid = f"choice:{index}"
            self._tree.insert(
                "",
                "end",
                iid=iid,
                text=choice.name,
                values=(choice.category, choice.role_text, action, choice.source_text),
            )
        if self.choices:
            self._tree.selection_set("choice:0")
            self._tree.focus("choice:0")
            self._tree.see("choice:0")
        self._tree.bind("<Double-1>", lambda _event: self.ok())
        return self._tree

    def validate(self) -> bool:
        return bool(self._tree is not None and self._tree.selection())

    def apply(self) -> None:
        if self._tree is None:
            return
        selected = tuple(self._tree.selection())
        if not selected:
            return
        try:
            index = int(str(selected[0]).split(":", 1)[1])
        except (IndexError, ValueError):
            return
        if 0 <= index < len(self.choices):
            self.result = self.choices[index]


def ask_current_zone_dashboard(
    parent,
    dashboard: CurrentZoneDashboard,
) -> CurrentZoneDashboardChoice | None:
    if not dashboard.choices:
        return None
    return _CurrentZoneDashboardDialog(parent, dashboard).result
