from __future__ import annotations

from configparser import ConfigParser
import os
from pathlib import Path
from typing import Mapping


PATH_SECTION = "paths"
UI_SECTION = "ui"


class SettingsFile:
    """Small INI-backed store for user-selected filesystem locations.

    The knowledge database deliberately remains separate from UI/location settings so
    a user can inspect, copy, or edit paths without opening SQLite. Writes are atomic
    and ConfigParser interpolation is disabled so Windows paths containing ``%`` are
    preserved literally.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else Path.home() / ".eqquest" / "settings.ini"
        self.path = self.path.expanduser()
        self._config = ConfigParser(interpolation=None)
        self._config.optionxform = str.lower
        if self.path.is_file():
            self._config.read(self.path, encoding="utf-8")
        if not self._config.has_section(PATH_SECTION):
            self._config.add_section(PATH_SECTION)
        if not self._config.has_section(UI_SECTION):
            self._config.add_section(UI_SECTION)


    def get(self, section: str, key: str, default: str = "") -> str:
        if not self._config.has_section(section):
            return default
        return self._config.get(section, key.lower(), fallback=default).strip()

    def set(self, section: str, key: str, value: str | None) -> None:
        if not self._config.has_section(section):
            self._config.add_section(section)
        self._config.set(section, key.lower(), "" if value is None else str(value).strip())

    def get_path(self, key: str, default: str = "") -> str:
        value = self._config.get(PATH_SECTION, key.lower(), fallback=default)
        return value.strip()

    def has_path(self, key: str) -> bool:
        return bool(self.get_path(key))

    def set_path(self, key: str, value: str | Path | None) -> None:
        text = "" if value is None else str(value).strip()
        self._config.set(PATH_SECTION, key.lower(), text)

    def update_paths(self, values: Mapping[str, str | Path | None]) -> None:
        for key, value in values.items():
            self.set_path(key, value)

    def migrate_missing_paths(self, values: Mapping[str, str | Path | None]) -> bool:
        """Copy legacy/default values only when the INI does not already own a path."""
        changed = False
        for key, value in values.items():
            if self.has_path(key):
                continue
            text = "" if value is None else str(value).strip()
            if text:
                self.set_path(key, text)
                changed = True
        return changed

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            self._config.write(handle)
        os.replace(tmp, self.path)
