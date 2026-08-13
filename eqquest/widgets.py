from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class VerticalScrolledFrame(ttk.Frame):
    """A vertically scrollable container for long option/source pages.

    ``content`` is the frame callers populate.  The interior is always at least as
    wide as the viewport, while its natural requested height determines the scroll
    region.  A normal scrollbar is always visible so users are not dependent on a
    mouse wheel.
    """

    def __init__(
        self,
        master,
        *,
        padding: int | tuple[int, ...] = 0,
        content_style: str | None = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vscroll.grid(row=0, column=1, sticky="ns")

        self.content = ttk.Frame(self.canvas, padding=padding, style=content_style or "TFrame")
        self._window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.content.bind("<Configure>", self._content_configured, add="+")
        self.canvas.bind("<Configure>", self._canvas_configured, add="+")
        self.canvas.bind("<MouseWheel>", self._mousewheel, add="+")
        self.content.bind("<MouseWheel>", self._mousewheel, add="+")
        self.canvas.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"), add="+")
        self.canvas.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"), add="+")

    def _content_configured(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_configured(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _mousewheel(self, event):
        # Windows reports multiples of 120; touchpads can report smaller deltas.
        delta = int(event.delta)
        if not delta:
            return None
        units = -max(1, abs(delta) // 120) if delta > 0 else max(1, abs(delta) // 120)
        self.canvas.yview_scroll(units, "units")
        return "break"

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0.0)
