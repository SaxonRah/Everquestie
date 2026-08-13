from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Iterable

from ..db import Database


@dataclass(slots=True)
class EQClientImportResult:
    zones: int = 0
    help_topics: int = 0
    skill_caps: int = 0
    base_stats: int = 0
    ac_mitigation: int = 0
    spell_stacking: int = 0
    dbstring_entities: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return (
            self.zones + self.help_topics + self.skill_caps + self.base_stats
            + self.ac_mitigation + self.spell_stacking + self.dbstring_entities
        )


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.parts.append(data)

    @property
    def title(self) -> str:
        return " ".join(" ".join(self.parts).split())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clean_help_text(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def parse_zone_names(text: str) -> Iterable[tuple[int, str, int | None, int | None]]:
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("^")]
        if len(parts) < 2:
            continue
        try:
            zone_id = int(parts[0])
        except ValueError:
            continue
        name = parts[1]
        if not name:
            continue

        def maybe_int(index: int) -> int | None:
            if index >= len(parts) or not parts[index]:
                return None
            try:
                return int(parts[index])
            except ValueError:
                return None

        yield zone_id, name, maybe_int(2), maybe_int(3)


def _parse_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def _parse_float(value: str) -> float | None:
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return None


def parse_skill_caps(text: str) -> list[tuple[int, int, int, int]]:
    rows: list[tuple[int, int, int, int]] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        p = line.split("^")
        if len(p) < 4:
            continue
        values = [_parse_int(x) for x in p[:4]]
        if any(v is None for v in values):
            continue
        rows.append(tuple(int(v) for v in values))
    return rows


def parse_base_stats(text: str) -> list[tuple]:
    rows: list[tuple] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        p = line.split("^")
        if len(p) < 10:
            continue
        level, class_id = _parse_int(p[0]), _parse_int(p[1])
        if level is None or class_id is None:
            continue
        rows.append((
            level, class_id,
            _parse_float(p[2]), _parse_float(p[3]), _parse_float(p[4]),
            _parse_float(p[7]), _parse_float(p[8]), _parse_float(p[9]),
        ))
    return rows


def parse_ac_mitigation(text: str) -> list[tuple]:
    rows: list[tuple] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        p = line.split("^")
        if len(p) < 4:
            continue
        class_id, level = _parse_int(p[0]), _parse_int(p[1])
        if class_id is None or level is None:
            continue
        rows.append((class_id, level, _parse_float(p[2]), _parse_float(p[3])))
    return rows


def parse_spell_stacking(text: str) -> list[tuple]:
    rows: list[tuple] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        p = line.split("^")
        if len(p) < 4:
            continue
        values = [_parse_int(x) for x in p[:4]]
        if values[0] is None:
            continue
        rows.append(tuple(values))
    return rows


DBSTR_NAME_TYPES: dict[int, str] = {
    12: "creature_type",
    17: "alt_currency",
    20: "expansion",
    30: "game_event",
}
DBSTR_DESCRIPTION_TYPES: dict[int, tuple[int, str]] = {
    31: (30, "description"),
    47: (17, "description"),
}


def parse_dbstrings(text: str) -> tuple[dict[tuple[int, int], str], int]:
    values: dict[tuple[int, int], str] = {}
    bad = 0
    for raw in text.splitlines():
        line = raw.rstrip("\r\n").lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        p = line.split("^")
        if len(p) < 3:
            bad += 1
            continue
        object_id, string_type = _parse_int(p[0]), _parse_int(p[1])
        if object_id is None or string_type is None:
            bad += 1
            continue
        value = p[2].strip()
        if value:
            values[(string_type, object_id)] = value
    return values, bad


class EQClientImporter:
    """Import authoritative data that is physically present in an EQ install."""

    def __init__(self, db: Database):
        self.db = db

    def import_installation(self, eq_path: str | Path) -> EQClientImportResult:
        root = Path(eq_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"EverQuest directory does not exist: {root}")

        result = EQClientImportResult()
        with self.db.batch():
            zone_file = root / "Resources" / "ZoneNames.txt"
            if zone_file.is_file():
                result.zones = self._import_zones(zone_file)
            else:
                result.skipped += 1

            help_dir = root / "Help"
            if help_dir.is_dir():
                result.help_topics = self._import_help(help_dir)
            else:
                result.skipped += 1

            table_specs = [
                (root / "Resources" / "skillcaps.txt", "skill_caps", self._import_skill_caps),
                (root / "Resources" / "basedata.txt", "base_stats", self._import_base_stats),
                (root / "Resources" / "ACMitigation.txt", "ac_mitigation", self._import_ac_mitigation),
                (root / "Resources" / "SpellStackingGroups.txt", "spell_stacking", self._import_spell_stacking),
            ]
            for file_path, attr, loader in table_specs:
                if file_path.is_file():
                    setattr(result, attr, loader(file_path))
                else:
                    result.skipped += 1

            dbstr = root / "dbstr_us.txt"
            if dbstr.is_file():
                result.dbstring_entities = self._import_dbstrings(dbstr)
            else:
                result.skipped += 1

            self.db.set_meta("eq_game_path", str(root))
        return result

    def _import_zones(self, path: Path) -> int:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8", errors="replace")
        source_url = "eqclient://Resources/ZoneNames.txt"
        source_id = self.db.upsert_source_page(
            url=source_url,
            title="EverQuest Resources/ZoneNames.txt",
            entity_type="zone",
            sha256=_sha256_bytes(raw_bytes),
            plain_text=text,
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/ZoneNames.txt",
            local_path=str(path),
        )

        count = 0
        for zone_id, name, min_level, max_level in parse_zone_names(text):
            data = {
                "eq_zone_id": zone_id,
                "client_level_field_1": min_level,
                "client_level_field_2": max_level,
                "authoritative_identity_source": "EverQuest Client",
            }
            entity_id = self.db.upsert_entity(
                kind="zone",
                name=name,
                source_page_id=source_id,
                source_url=source_url,
                external_id=str(zone_id),
                merge_by_name=True,
                level_min=min_level if min_level and min_level > 0 else None,
                level_max=max_level if max_level and max_level > 0 else None,
                notes="Zone identity imported from the installed EverQuest client.",
                data=data,
            )
            self.db.add_alias(
                entity_id,
                str(zone_id),
                alias_type="eq_zone_id",
                source_page_id=source_id,
            )
            count += 1
        return count

    def _import_help(self, help_dir: Path) -> int:
        count = 0
        for path in sorted(help_dir.glob("*.html")):
            raw_bytes = path.read_bytes()
            html = raw_bytes.decode("utf-8", errors="replace")
            parser = _TitleParser()
            parser.feed(html)
            title = parser.title or path.stem
            plain = _clean_help_text(html)
            source_url = f"eqclient://Help/{path.name}"
            source_id = self.db.upsert_source_page(
                url=source_url,
                title=title,
                entity_type="help",
                sha256=_sha256_bytes(raw_bytes),
                plain_text=plain,
                raw_html=html,
                source_name="EverQuest Client",
                source_kind="local_game_files",
                source_key=f"Help/{path.name}",
                local_path=str(path),
            )
            self.db.upsert_entity(
                kind="help",
                name=title,
                source_page_id=source_id,
                source_url=source_url,
                external_id=path.stem,
                notes="Official in-game help topic imported from the installed client.",
                data={"filename": path.name},
            )
            count += 1
        return count

    def _table_source(self, path: Path, *, entity_type: str, title: str) -> tuple[int, str]:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        rel = path.name
        try:
            rel = str(path.relative_to(path.parents[1])).replace("\\", "/")
        except Exception:
            pass
        source_url = f"eqclient://{rel}"
        source_id = self.db.upsert_source_page(
            url=source_url,
            title=title,
            entity_type=entity_type,
            sha256=_sha256_bytes(raw),
            plain_text=text,
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key=rel,
            local_path=str(path),
        )
        return source_id, text

    def _import_skill_caps(self, path: Path) -> int:
        source_id, text = self._table_source(
            path, entity_type="skill_cap", title="EverQuest Resources/skillcaps.txt"
        )
        return self.db.replace_skill_caps(source_id, parse_skill_caps(text))

    def _import_base_stats(self, path: Path) -> int:
        source_id, text = self._table_source(
            path, entity_type="base_stats", title="EverQuest Resources/basedata.txt"
        )
        return self.db.replace_base_stats(source_id, parse_base_stats(text))

    def _import_ac_mitigation(self, path: Path) -> int:
        source_id, text = self._table_source(
            path, entity_type="ac_mitigation", title="EverQuest Resources/ACMitigation.txt"
        )
        return self.db.replace_ac_mitigation(source_id, parse_ac_mitigation(text))

    def _import_spell_stacking(self, path: Path) -> int:
        source_id, text = self._table_source(
            path, entity_type="spell_stacking", title="EverQuest Resources/SpellStackingGroups.txt"
        )
        return self.db.replace_spell_stacking(source_id, parse_spell_stacking(text))

    def _import_dbstrings(self, path: Path) -> int:
        source_id, text = self._table_source(
            path, entity_type="multi", title="EverQuest dbstr_us.txt selected identities"
        )
        values, _bad = parse_dbstrings(text)
        imported = 0
        for string_type, kind in DBSTR_NAME_TYPES.items():
            for (stype, object_id), raw_name in values.items():
                if stype != string_type:
                    continue
                name = " ".join(raw_name.split()).strip()
                if not name or name.upper().startswith("UNKNOWN"):
                    continue
                data = {
                    "dbstr_type": string_type,
                    "authoritative_identity_source": "EverQuest Client",
                }
                description = None
                for desc_type, (name_type, field) in DBSTR_DESCRIPTION_TYPES.items():
                    if name_type == string_type:
                        description = values.get((desc_type, object_id))
                        if description:
                            data[field] = description
                entity_id = self.db.upsert_entity(
                    kind=kind,
                    name=name,
                    source_page_id=source_id,
                    source_url=f"eqclient://dbstr_us.txt#{string_type}:{object_id}",
                    external_id=str(object_id),
                    external_namespace=f"eqclient:{kind}",
                    merge_by_name=False,
                    notes="Identity imported from the installed EverQuest client's dbstr_us.txt.",
                    data=data,
                )
                if description:
                    self.db.upsert_entity_detail(
                        entity_id,
                        source_page_id=source_id,
                        detail_format="text",
                        detail_text=description,
                        detail_json=data,
                    )
                imported += 1
        return imported
