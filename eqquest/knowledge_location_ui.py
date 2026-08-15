from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, ttk

from .knowledge_map_choices import KnowledgeMapChoice, KnowledgeRouteChoice


def knowledge_map_choice_labels(
    choices: tuple[KnowledgeMapChoice, ...],
) -> tuple[str, ...]:
    labels: list[str] = []
    for choice in choices:
        source = ", ".join(choice.source_labels) if choice.source_labels else "knowledge"
        evidence = (
            f"{choice.evidence_count} evidence rows"
            if choice.evidence_count != 1
            else "1 evidence row"
        )
        labels.append(
            f"{choice.map_label} — {choice.loc_text} — {source} — {evidence}"
        )
    return tuple(labels)


def knowledge_route_choice_labels(
    choices: tuple[KnowledgeRouteChoice, ...],
) -> tuple[str, ...]:
    labels: list[str] = []
    for choice in choices:
        targets = ", ".join(choice.target_labels) if choice.target_labels else choice.selected_entity_name
        source = ", ".join(choice.source_labels) if choice.source_labels else "knowledge"
        mapped = (
            f"{choice.location_choice_count} mapped locations"
            if choice.location_choice_count != 1
            else "1 mapped location"
        )
        evidence = (
            f"{choice.evidence_count} evidence rows"
            if choice.evidence_count != 1
            else "1 evidence row"
        )
        labels.append(
            f"{choice.zone_name} — {targets} — {source} — {mapped}; {evidence}"
        )
    return tuple(labels)


class _KnowledgeLocationDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent,
        *,
        entity_name: str,
        zone_name: str,
        choices: tuple[KnowledgeMapChoice, ...],
    ):
        self.entity_name = str(entity_name)
        self.zone_name = str(zone_name)
        self.choices = tuple(choices)
        self.result: KnowledgeMapChoice | None = None
        self._listbox = None
        super().__init__(parent, title=f"Choose map location — {self.entity_name}")

    def body(self, master):
        ttk.Label(
            master,
            text=(
                f"Multiple safe locations are known for {self.entity_name} in {self.zone_name}.\n"
                "Choose the exact evidence-backed point to focus on the current map."
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._listbox = tk.Listbox(
            master,
            exportselection=False,
            width=100,
            height=min(12, max(4, len(self.choices))),
        )
        self._listbox.grid(row=1, column=0, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        for label in knowledge_map_choice_labels(self.choices):
            self._listbox.insert("end", label)
        if self.choices:
            self._listbox.selection_set(0)
            self._listbox.activate(0)
        self._listbox.bind("<Double-1>", lambda _event: self.ok())
        return self._listbox

    def validate(self) -> bool:
        return bool(self._listbox is not None and self._listbox.curselection())

    def apply(self) -> None:
        if self._listbox is None:
            return
        selected = self._listbox.curselection()
        if not selected:
            return
        index = int(selected[0])
        if 0 <= index < len(self.choices):
            self.result = self.choices[index]


class _KnowledgeRouteDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent,
        *,
        entity_name: str,
        current_zone_name: str,
        choices: tuple[KnowledgeRouteChoice, ...],
    ):
        self.entity_name = str(entity_name)
        self.current_zone_name = str(current_zone_name)
        self.choices = tuple(choices)
        self.result: KnowledgeRouteChoice | None = None
        self._listbox = None
        super().__init__(parent, title=f"Choose route destination — {self.entity_name}")

    def body(self, master):
        ttk.Label(
            master,
            text=(
                f"Safe locations for {self.entity_name} exist outside {self.current_zone_name}.\n"
                "Choose the canonical destination zone to hand to Travel."
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._listbox = tk.Listbox(
            master,
            exportselection=False,
            width=110,
            height=min(12, max(4, len(self.choices))),
        )
        self._listbox.grid(row=1, column=0, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        for label in knowledge_route_choice_labels(self.choices):
            self._listbox.insert("end", label)
        if self.choices:
            self._listbox.selection_set(0)
            self._listbox.activate(0)
        self._listbox.bind("<Double-1>", lambda _event: self.ok())
        return self._listbox

    def validate(self) -> bool:
        return bool(self._listbox is not None and self._listbox.curselection())

    def apply(self) -> None:
        if self._listbox is None:
            return
        selected = self._listbox.curselection()
        if not selected:
            return
        index = int(selected[0])
        if 0 <= index < len(self.choices):
            self.result = self.choices[index]


def ask_knowledge_map_choice(
    parent,
    entity_name: str,
    zone_name: str,
    choices: tuple[KnowledgeMapChoice, ...],
) -> KnowledgeMapChoice | None:
    """Choose only among an already-safe canonical current-zone candidate set."""
    ordered = tuple(
        sorted(
            choices,
            key=lambda choice: (
                0 if choice.origin == "entity" else 1,
                choice.relation_label.casefold(),
                choice.location_entity_name.casefold(),
                choice.y,
                choice.x,
                choice.z if choice.z is not None else 0.0,
            ),
        )
    )
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    dialog = _KnowledgeLocationDialog(
        parent,
        entity_name=entity_name,
        zone_name=zone_name,
        choices=ordered,
    )
    return dialog.result


def ask_knowledge_route_choice(
    parent,
    entity_name: str,
    current_zone_name: str,
    choices: tuple[KnowledgeRouteChoice, ...],
) -> KnowledgeRouteChoice | None:
    """Choose among already-safe canonical remote-zone destinations only."""
    ordered = tuple(
        sorted(
            choices,
            key=lambda choice: (
                choice.zone_name.casefold(),
                choice.target_labels,
            ),
        )
    )
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    dialog = _KnowledgeRouteDialog(
        parent,
        entity_name=entity_name,
        current_zone_name=current_zone_name,
        choices=ordered,
    )
    return dialog.result
