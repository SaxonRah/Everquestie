from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk
from typing import Iterable


THEME_SYSTEM = "system"
THEME_CLASSIC_EQ_STONE = "classic_eq_stone"

THEME_LABELS: dict[str, str] = {
    THEME_CLASSIC_EQ_STONE: "Classic EQ Stone",
    THEME_SYSTEM: "System",
}
LABEL_TO_THEME = {label: key for key, label in THEME_LABELS.items()}
DEFAULT_THEME = THEME_CLASSIC_EQ_STONE


class ThemeManager:
    """Small runtime theme layer for EverQuestie.

    ttk handles most controls.  Classic EQ Stone additionally recolors the handful
    of classic Tk widgets (Text/Listbox) which ttk cannot style.  The stone texture
    is an original EverQuestie asset inspired by the blue/gray marble character of
    the original EverQuest interface; no game UI artwork is bundled or copied.
    """

    CLASSIC = {
        "root": "#3b4350",
        "panel": "#545d6c",
        "panel2": "#626b78",
        "dark": "#222832",
        "darker": "#171c24",
        "light": "#8e98a4",
        "text": "#eee7cb",
        "muted": "#c7c0a8",
        "gold": "#d1bd7a",
        "gold_dark": "#7d6a3e",
        "parchment": "#d5ccb0",
        "parchment_text": "#1c1d1d",
        "select": "#776a49",
    }

    def __init__(self, root: tk.Misc):
        self.root = root
        self.style = ttk.Style(root)
        self.system_theme = self.style.theme_use()
        self._root_bg = str(root.cget("background"))
        self._classic_stone: tk.PhotoImage | None = None
        self._stone_element_created = False
        self._original_classic_widget_options: dict[tk.Misc, dict[str, object]] = {}
        self.current_theme = THEME_SYSTEM

    @staticmethod
    def label_for(theme_id: str) -> str:
        return THEME_LABELS.get(theme_id, THEME_LABELS[DEFAULT_THEME])

    @staticmethod
    def id_for_label(label: str) -> str:
        return LABEL_TO_THEME.get(label, DEFAULT_THEME)

    @staticmethod
    def labels() -> list[str]:
        return list(THEME_LABELS.values())

    def apply(self, theme_id: str) -> None:
        theme_id = theme_id if theme_id in THEME_LABELS else DEFAULT_THEME
        if theme_id == THEME_CLASSIC_EQ_STONE:
            self._apply_classic_eq_stone()
        else:
            self._apply_system()
        self.current_theme = theme_id

    def _apply_classic_eq_stone(self) -> None:
        # clam is the most predictable cross-platform ttk base for custom colors.
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")

        c = self.CLASSIC
        self.root.configure(background=c["root"])
        self._ensure_stone_element()

        self.style.configure(".", background=c["panel"], foreground=c["text"])
        self.style.configure("TFrame", background=c["panel"])
        self.style.configure("Stone.TFrame", background=c["root"])
        self.style.configure("TLabel", background=c["panel"], foreground=c["text"])
        self.style.configure("TCheckbutton", background=c["panel"], foreground=c["text"])
        self.style.configure("TRadiobutton", background=c["panel"], foreground=c["text"])
        self.style.configure(
            "TLabelframe",
            background=c["panel"],
            foreground=c["gold"],
            bordercolor=c["dark"],
            lightcolor=c["light"],
            darkcolor=c["darker"],
            relief="groove",
        )
        self.style.configure(
            "TLabelframe.Label",
            background=c["panel"],
            foreground=c["gold"],
            font=("Times New Roman", 10, "bold"),
        )
        self.style.configure(
            "TButton",
            background=c["panel2"],
            foreground=c["text"],
            bordercolor=c["darker"],
            lightcolor=c["light"],
            darkcolor=c["dark"],
            padding=(7, 3),
            relief="raised",
        )
        self.style.map(
            "TButton",
            background=[("active", c["light"]), ("pressed", c["dark"])],
            foreground=[("disabled", c["muted"])],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=c["parchment"],
            foreground=c["parchment_text"],
            insertcolor=c["parchment_text"],
            bordercolor=c["darker"],
            lightcolor=c["light"],
            darkcolor=c["dark"],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=c["parchment"],
            background=c["panel2"],
            foreground=c["parchment_text"],
            arrowcolor=c["text"],
            bordercolor=c["darker"],
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["parchment"])],
            foreground=[("readonly", c["parchment_text"])],
            selectbackground=[("readonly", c["parchment"])],
            selectforeground=[("readonly", c["parchment_text"])],
        )
        self.style.configure(
            "TNotebook",
            background=c["root"],
            bordercolor=c["dark"],
            tabmargins=(2, 5, 2, 0),
        )
        self.style.configure(
            "TNotebook.Tab",
            background=c["panel"],
            foreground=c["text"],
            padding=(11, 5),
            bordercolor=c["dark"],
            lightcolor=c["light"],
            darkcolor=c["darker"],
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", c["panel2"]), ("active", c["light"])],
            foreground=[("selected", c["gold"])],
        )
        self.style.configure(
            "Treeview",
            background=c["dark"],
            fieldbackground=c["dark"],
            foreground=c["text"],
            bordercolor=c["darker"],
            rowheight=22,
        )
        self.style.map(
            "Treeview",
            background=[("selected", c["select"])],
            foreground=[("selected", c["text"])],
        )
        self.style.configure(
            "Treeview.Heading",
            background=c["panel2"],
            foreground=c["gold"],
            relief="raised",
        )
        self.style.configure(
            "TScrollbar",
            background=c["panel2"],
            troughcolor=c["dark"],
            bordercolor=c["darker"],
            arrowcolor=c["text"],
        )
        self.style.configure("TPanedwindow", background=c["root"])
        self.style.configure("Sash", sashthickness=6)

        self._recolor_classic_widgets(self.root, classic=True)

    def _apply_system(self) -> None:
        try:
            self.style.theme_use(self.system_theme)
        except tk.TclError:
            pass
        try:
            self.style.layout("Stone.TFrame", self.style.layout("TFrame"))
            self.style.configure(
                "Stone.TFrame",
                background=self.style.lookup("TFrame", "background"),
            )
        except tk.TclError:
            pass
        self.root.configure(background=self._root_bg)
        self._recolor_classic_widgets(self.root, classic=False)

    def _ensure_stone_element(self) -> None:
        if self._classic_stone is None:
            asset = Path(__file__).resolve().parent / "assets" / "classic_eq_stone.ppm"
            try:
                self._classic_stone = tk.PhotoImage(master=self.root, file=str(asset))
            except tk.TclError:
                self._classic_stone = None

        if self._classic_stone is not None and not self._stone_element_created:
            try:
                self.style.element_create(
                    "EverQuestie.Stone",
                    "image",
                    self._classic_stone,
                    border=12,
                    sticky="nsew",
                )
                self._stone_element_created = True
            except tk.TclError:
                # The element can already exist when toggling themes repeatedly.
                self._stone_element_created = True

        if self._classic_stone is not None:
            try:
                self.style.layout("Stone.TFrame", [("EverQuestie.Stone", {"sticky": "nsew"})])
            except tk.TclError:
                self.style.configure("Stone.TFrame", background=self.CLASSIC["root"])

    def _walk(self, widget: tk.Misc) -> Iterable[tk.Misc]:
        yield widget
        for child in widget.winfo_children():
            yield from self._walk(child)

    def _remember(self, widget: tk.Misc, keys: tuple[str, ...]) -> None:
        if widget in self._original_classic_widget_options:
            return
        values: dict[str, object] = {}
        for key in keys:
            try:
                values[key] = widget.cget(key)
            except tk.TclError:
                pass
        self._original_classic_widget_options[widget] = values

    def _recolor_classic_widgets(self, root: tk.Misc, *, classic: bool) -> None:
        c = self.CLASSIC
        for widget in self._walk(root):
            if isinstance(widget, tk.Text):
                keys = (
                    "background", "foreground", "insertbackground", "selectbackground",
                    "selectforeground", "relief", "borderwidth",
                )
                self._remember(widget, keys)
                if classic:
                    try:
                        widget.configure(
                            background=c["dark"], foreground=c["text"],
                            insertbackground=c["gold"], selectbackground=c["select"],
                            selectforeground=c["text"], relief="sunken", borderwidth=2,
                        )
                    except tk.TclError:
                        pass
                else:
                    try:
                        widget.configure(**self._original_classic_widget_options.get(widget, {}))
                    except tk.TclError:
                        pass
            elif isinstance(widget, tk.Listbox):
                keys = (
                    "background", "foreground", "selectbackground", "selectforeground",
                    "relief", "borderwidth",
                )
                self._remember(widget, keys)
                if classic:
                    try:
                        widget.configure(
                            background=c["dark"], foreground=c["text"],
                            selectbackground=c["select"], selectforeground=c["text"],
                            relief="sunken", borderwidth=2,
                        )
                    except tk.TclError:
                        pass
                else:
                    try:
                        widget.configure(**self._original_classic_widget_options.get(widget, {}))
                    except tk.TclError:
                        pass
            elif widget.__class__.__name__ == "VerticalScrolledFrame" and hasattr(widget, "canvas"):
                try:
                    if classic:
                        widget.canvas.configure(background=c["root"])
                    else:
                        widget.canvas.configure(background=self.style.lookup("TFrame", "background"))
                except tk.TclError:
                    pass
