from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, ttk

from .target_known_drops import TargetKnownDrop


def target_known_drop_labels(drops: tuple[TargetKnownDrop, ...]) -> tuple[str, ...]:
    labels: list[str] = []
    for drop in drops:
        profile = (
            f" — profile {drop.profile_status}"
            if drop.profile_status not in {"", "available"}
            else ""
        )
        labels.append(
            f"{drop.item_name} — {drop.quest_use_label} — {drop.source_label}{profile}"
        )
    return tuple(labels)


class _TargetKnownDropDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent,
        *,
        target_name: str,
        drops: tuple[TargetKnownDrop, ...],
    ):
        self.target_name = str(target_name)
        self.drops = tuple(drops)
        self.result: TargetKnownDrop | None = None
        self._listbox = None
        super().__init__(parent, title=f"Known drops — {self.target_name}")

    def body(self, master):
        ttk.Label(
            master,
            text=(
                f"Reviewed source-backed drops compiled for {self.target_name}.\n"
                "Choose an exact canonical item to open in Knowledge. "
                "No drop-rate or completeness claim is implied."
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._listbox = tk.Listbox(
            master,
            exportselection=False,
            width=120,
            height=min(16, max(5, len(self.drops))),
        )
        self._listbox.grid(row=1, column=0, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        for label in target_known_drop_labels(self.drops):
            self._listbox.insert("end", label)
        if self.drops:
            self._listbox.selection_set(0)
            self._listbox.activate(0)
        self._listbox.bind("<Double-1>", lambda _event: self.ok())
        return self._listbox

    def buttonbox(self):
        box = ttk.Frame(self)
        ttk.Button(box, text="Open item", width=12, command=self.ok).pack(
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
        if 0 <= index < len(self.drops):
            self.result = self.drops[index]


def ask_target_known_drop(
    parent,
    target_name: str,
    drops: tuple[TargetKnownDrop, ...],
) -> TargetKnownDrop | None:
    """Choose only among already source-backed exact drop identities."""
    ordered = tuple(
        sorted(
            drops,
            key=lambda drop: (
                0 if any(use.tracked for use in drop.quest_uses) else 1,
                0 if drop.quest_uses else 1,
                drop.item_name.casefold(),
                drop.item_id,
            ),
        )
    )
    if not ordered:
        return None
    dialog = _TargetKnownDropDialog(parent, target_name=target_name, drops=ordered)
    return dialog.result
