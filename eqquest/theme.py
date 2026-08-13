from __future__ import annotations

import tkinter as tk
from tkinter import ttk

THEME_SYSTEM = "system"
THEME_CLASSIC_EQ_STONE = "classic_eq_stone"
THEME_LABELS = {
    THEME_CLASSIC_EQ_STONE: "Classic EQ Stone",
    THEME_SYSTEM: "System",
}
DEFAULT_THEME = THEME_CLASSIC_EQ_STONE


class ThemeManager:
    """EverQuestie's runtime theme switcher.

    The classic theme is original EverQuestie styling; it does not bundle game UI art.
    """

    def __init__(self, root: tk.Misc):
        self.root = root
        self.style = ttk.Style(root)
        self.system_theme = self.style.theme_use()
        self.system_background = str(root.cget("background"))
        self.current_theme = THEME_SYSTEM

    @staticmethod
    def label_for(theme_id: str) -> str:
        return THEME_LABELS.get(theme_id, THEME_LABELS[DEFAULT_THEME])

    @staticmethod
    def id_for_label(label: str) -> str:
        for theme_id, theme_label in THEME_LABELS.items():
            if theme_label == label:
                return theme_id
        return DEFAULT_THEME

    @staticmethod
    def labels() -> list[str]:
        return list(THEME_LABELS.values())

    def apply(self, theme_id: str) -> None:
        if theme_id == THEME_SYSTEM:
            try:
                self.style.theme_use(self.system_theme)
            except tk.TclError:
                pass
            self.root.configure(background=self.system_background)
            self.current_theme = THEME_SYSTEM
            return

        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        root = "#3b4350"
        panel = "#545d6c"
        panel2 = "#626b78"
        dark = "#222832"
        text = "#eee7cb"
        gold = "#d1bd7a"
        parchment = "#d5ccb0"
        parchment_text = "#1c1d1d"
        select = "#776a49"

        self.root.configure(background=root)
        self.style.configure(".", background=panel, foreground=text)
        self.style.configure("TFrame", background=panel)
        self.style.configure("Stone.TFrame", background=root)
        self.style.configure("TLabel", background=panel, foreground=text)
        self.style.configure("TCheckbutton", background=panel, foreground=text)
        self.style.configure("TRadiobutton", background=panel, foreground=text)
        self.style.configure("TLabelframe", background=panel, foreground=gold)
        self.style.configure("TLabelframe.Label", background=panel, foreground=gold)
        self.style.configure("TButton", background=panel2, foreground=text, padding=(7, 3))
        self.style.configure("TEntry", fieldbackground=parchment, foreground=parchment_text)
        self.style.configure("TCombobox", fieldbackground=parchment, foreground=parchment_text)
        self.style.configure("TNotebook", background=root)
        self.style.configure("TNotebook.Tab", background=panel, foreground=text, padding=(11, 5))
        self.style.map("TNotebook.Tab", foreground=[("selected", gold)])
        self.style.configure("Treeview", background=dark, fieldbackground=dark, foreground=text, rowheight=22)
        self.style.map("Treeview", background=[("selected", select)], foreground=[("selected", text)])
        self.style.configure("Treeview.Heading", background=panel2, foreground=gold)
        self.current_theme = THEME_CLASSIC_EQ_STONE
