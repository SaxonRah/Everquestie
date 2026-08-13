from __future__ import annotations

import base64
import bz2
from pathlib import Path
import tkinter as tk

_ASSET_DIR = Path(__file__).resolve().parent / "assets"
_THEME_ARCHIVE = _ASSET_DIR / "v012_theme.py.bz2.b64"

# Execute the exact v0.12 theme source. Keeping the archived source lets this
# checkout preserve the original theme implementation byte-for-byte.
_source = bz2.decompress(base64.b64decode(_THEME_ARCHIVE.read_text(encoding="ascii").strip()))
exec(compile(_source, str(_THEME_ARCHIVE), "exec"), globals())


def _stone_bytes() -> bytes:
    parts = sorted(_ASSET_DIR.glob("classic_eq_stone.bz2.b64.part*"))
    encoded = "".join(p.read_text(encoding="ascii").strip() for p in parts)
    return bz2.decompress(base64.b64decode(encoded))


def _ensure_v012_stone_element(self) -> None:
    if self._classic_stone is None:
        try:
            self._classic_stone = tk.PhotoImage(
                master=self.root,
                data=_stone_bytes(),
                format="PPM",
            )
        except (OSError, ValueError, EOFError, tk.TclError):
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
            self._stone_element_created = True

    if self._classic_stone is not None:
        try:
            self.style.layout("Stone.TFrame", [("EverQuestie.Stone", {"sticky": "nsew"})])
        except tk.TclError:
            self.style.configure("Stone.TFrame", background=self.CLASSIC["root"])


ThemeManager._ensure_stone_element = _ensure_v012_stone_element
