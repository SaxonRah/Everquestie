from __future__ import annotations

import tkinter as tk
from tkinter import simpledialog, ttk

from .target_personal_sightings import TargetPersonalSighting


def target_personal_sighting_labels(
    rows: tuple[TargetPersonalSighting, ...],
) -> tuple[str, ...]:
    return tuple(
        (
            f"{row.observed_zone_name} — {row.total_count:,} observation(s) — "
            f"{row.action_summary or 'no action summary'} — {row.identity_label}"
        )
        for row in rows
    )


class _TargetPersonalSightingDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent,
        *,
        target_name: str,
        rows: tuple[TargetPersonalSighting, ...],
    ):
        self.target_name = str(target_name)
        self.rows = tuple(rows)
        self.result: TargetPersonalSighting | None = None
        self._listbox = None
        super().__init__(parent, title=f"Personal sightings — {self.target_name}")

    def body(self, master):
        ttk.Label(
            master,
            text=(
                f"Zones where your own log explicitly observed {self.target_name} under a "
                "trusted zone-entry context.\nResolved rows may be handed to Travel, but "
                "they remain personal history rather than canonical spawn evidence."
            ),
            justify="left",
            wraplength=980,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._listbox = tk.Listbox(
            master,
            exportselection=False,
            width=125,
            height=min(16, max(5, len(self.rows))),
        )
        self._listbox.grid(row=1, column=0, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        for label in target_personal_sighting_labels(self.rows):
            self._listbox.insert("end", label)
        if self.rows:
            self._listbox.selection_set(0)
            self._listbox.activate(0)
        self._listbox.bind("<Double-1>", lambda _event: self.ok())
        return self._listbox

    def buttonbox(self):
        box = ttk.Frame(self)
        ttk.Button(box, text="Select", width=12, command=self.ok).pack(
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
        if 0 <= index < len(self.rows):
            self.result = self.rows[index]


def ask_target_personal_sighting(
    parent,
    target_name: str,
    rows: tuple[TargetPersonalSighting, ...],
) -> TargetPersonalSighting | None:
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                0 if row.actionable else 1,
                -row.total_count,
                row.observed_zone_name.casefold(),
            ),
        )
    )
    if not ordered:
        return None
    dialog = _TargetPersonalSightingDialog(parent, target_name=target_name, rows=ordered)
    return dialog.result
