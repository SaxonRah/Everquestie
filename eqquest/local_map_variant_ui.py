from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import simpledialog, ttk


class _LocalMapVariantDialog(simpledialog.Dialog):
    def __init__(self, parent, *, zone_name: str, candidates: tuple[Path, ...]):
        self.zone_name = str(zone_name)
        self.candidates = tuple(candidates)
        self.result: Path | None = None
        self._listbox = None
        super().__init__(parent, title=f"Choose map variant — {self.zone_name}")

    def body(self, master):
        ttk.Label(
            master,
            text=(
                f"Multiple canonical local map files are valid for {self.zone_name}.\n"
                "Choose the one this local map pack should use."
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._listbox = tk.Listbox(master, exportselection=False, height=min(10, max(3, len(self.candidates))))
        self._listbox.grid(row=1, column=0, sticky="nsew")
        master.rowconfigure(1, weight=1)
        master.columnconfigure(0, weight=1)
        for path in self.candidates:
            self._listbox.insert("end", path.name)
        if self.candidates:
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
        if 0 <= index < len(self.candidates):
            self.result = self.candidates[index]


def ask_local_map_variant(
    parent,
    zone_name: str,
    candidates: tuple[Path, ...],
) -> Path | None:
    """Ask the player to choose only among an already-safe canonical candidate set."""
    ordered = tuple(sorted((Path(path) for path in candidates), key=lambda path: path.name.casefold()))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    dialog = _LocalMapVariantDialog(parent, zone_name=zone_name, candidates=ordered)
    return dialog.result
