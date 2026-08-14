from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any

from .db import Database, normalize_name
from .eqmap import normalize_map_name


ZONE_MAP_CATALOG_VERSION = "1"
_SHORT_NAME_KEYS = (
    "map_short_name",
    "short_name",
    "shortName",
    "zone_short_name",
    "zoneShortName",
)
_STOP_WORDS = {"the", "of", "a", "an", "and"}


@dataclass(frozen=True, slots=True)
class ZoneMapBinding:
    source_name: str
    source_version: str
    map_stem: str
    zone_entity_id: int | None
    zone_name: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class ZoneMapBindingStats:
    maps: int
    linked: int
    ambiguous: int
    unresolved: int
    changed: int


@dataclass(frozen=True, slots=True)
class _ZoneSignals:
    entity_id: int
    name: str
    normalized_name: str
    exact_tokens: frozenset[str]
    words: frozenset[str]


class ZoneMapCatalog:
    """Canonical map-stem -> zone identity compiled into EverQuestie knowledge.

    Map packs normally use client short names while logs and knowledge providers tend
    to expose display names. This catalog makes that join explicit and source-aware.
    It deliberately stores unresolved/ambiguous results rather than promoting fuzzy
    guesses into canonical identity.
    """

    def __init__(self, db: Database):
        self.db = db
        if getattr(db, "knowledge_writable", True):
            self.ensure_schema()

    def ensure_schema(self) -> None:
        self.db.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS zone_map_bindings (
                source_name TEXT NOT NULL,
                source_version TEXT NOT NULL DEFAULT '',
                map_stem TEXT NOT NULL,
                zone_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
                zone_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unresolved',
                reason TEXT NOT NULL DEFAULT '',
                catalog_version TEXT NOT NULL DEFAULT '1',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(source_name, map_stem)
            );
            CREATE INDEX IF NOT EXISTS ix_zone_map_bindings_zone
            ON zone_map_bindings(zone_entity_id, source_name);
            CREATE INDEX IF NOT EXISTS ix_zone_map_bindings_status
            ON zone_map_bindings(status, source_name);
            """
        )
        self.db.conn.commit()

    def _table_exists(self) -> bool:
        return self.db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='zone_map_bindings'"
        ).fetchone() is not None

    @staticmethod
    def _meaningful_words(value: str) -> set[str]:
        return {
            normalize_map_name(word)
            for word in re.findall(r"[A-Za-z0-9`']+", value or "")
            if normalize_map_name(word)
            and normalize_map_name(word) not in _STOP_WORDS
            and len(normalize_map_name(word)) >= 4
        }

    def _zone_signals(self) -> list[_ZoneSignals]:
        aliases_by_entity: dict[int, list[str]] = {}
        for row in self.db.conn.execute(
            "SELECT entity_id,alias,alias_type FROM entity_aliases ORDER BY entity_id,id"
        ).fetchall():
            alias = str(row["alias"] or "").strip()
            if not alias:
                continue
            # Numeric IDs are useful identity aliases, but never map-file names.
            if alias.isdigit() or str(row["alias_type"] or "").casefold() == "eq_zone_id":
                continue
            aliases_by_entity.setdefault(int(row["entity_id"]), []).append(alias)

        result: list[_ZoneSignals] = []
        for row in self.db.conn.execute(
            "SELECT id,name,normalized_name,data_json FROM entities "
            "WHERE kind='zone' ORDER BY id"
        ).fetchall():
            entity_id = int(row["id"])
            name = str(row["name"])
            exact = {normalize_map_name(name)}
            words = self._meaningful_words(name)
            for alias in aliases_by_entity.get(entity_id, []):
                token = normalize_map_name(alias)
                if token:
                    exact.add(token)
                words.update(self._meaningful_words(alias))
            try:
                data: Any = json.loads(row["data_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                data = {}
            if isinstance(data, dict):
                for key in _SHORT_NAME_KEYS:
                    value = str(data.get(key) or "").strip()
                    token = normalize_map_name(value)
                    if token:
                        exact.add(token)
            exact.discard("")
            result.append(
                _ZoneSignals(
                    entity_id=entity_id,
                    name=name,
                    normalized_name=str(row["normalized_name"] or normalize_name(name)),
                    exact_tokens=frozenset(exact),
                    words=frozenset(words),
                )
            )
        return result

    @staticmethod
    def _unique(candidates: list[_ZoneSignals]) -> _ZoneSignals | None:
        by_id = {candidate.entity_id: candidate for candidate in candidates}
        return next(iter(by_id.values())) if len(by_id) == 1 else None

    def _resolve(
        self,
        map_stem: str,
        existing_zone_name: str,
        zones: list[_ZoneSignals],
    ) -> tuple[_ZoneSignals | None, str, str]:
        stem = normalize_map_name(map_stem)
        if not stem:
            return None, "unresolved", "empty map stem"

        if existing_zone_name:
            normalized_existing = normalize_name(existing_zone_name)
            existing = [z for z in zones if z.normalized_name == normalized_existing]
            chosen = self._unique(existing)
            if chosen is not None:
                return chosen, "linked", "existing canonical map-zone name"
            if len({z.entity_id for z in existing}) > 1:
                return None, "ambiguous", "existing map-zone name matches multiple zones"

        exact = [z for z in zones if stem in z.exact_tokens]
        chosen = self._unique(exact)
        if chosen is not None:
            return chosen, "linked", "exact canonical name/alias/short-name match"
        if len({z.entity_id for z in exact}) > 1:
            return None, "ambiguous", f"map stem exactly matches {len({z.entity_id for z in exact})} zones"

        word = [z for z in zones if stem in z.words]
        chosen = self._unique(word)
        if chosen is not None:
            return chosen, "linked", "unique significant zone-name word"
        if len({z.entity_id for z in word}) > 1:
            return None, "ambiguous", f"map stem is shared by {len({z.entity_id for z in word})} zone names"

        # Containment is accepted only when it uniquely identifies one canonical
        # exact token. It handles benign decoration such as map stems that append a
        # numeric/variant suffix, while refusing broad fuzzy spelling guesses.
        contained = [
            z
            for z in zones
            if any(
                len(token) >= 5 and (stem in token or token in stem)
                for token in z.exact_tokens
            )
        ]
        chosen = self._unique(contained)
        if chosen is not None:
            return chosen, "linked", "unique canonical-name containment"
        if len({z.entity_id for z in contained}) > 1:
            return None, "ambiguous", f"map stem overlaps {len({z.entity_id for z in contained})} zones"

        return None, "unresolved", "no conservative canonical zone match"

    def reconcile(self, *, source_name: str | None = None) -> ZoneMapBindingStats:
        """Reconcile all indexed map stems (or one source) to canonical zone entities."""
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("zone/map reconciliation is builder-only")
        self.ensure_schema()
        clauses = ""
        args: tuple[object, ...] = ()
        if source_name:
            clauses = " WHERE source_name=?"
            args = (source_name,)
        rows = self.db.conn.execute(
            "SELECT source_name,map_stem,MAX(source_version) AS source_version,"
            "MAX(zone_name) AS zone_name FROM map_sources"
            + clauses
            + " GROUP BY source_name,map_stem ORDER BY source_name,map_stem",
            args,
        ).fetchall()
        zones = self._zone_signals()
        now = datetime.now().isoformat(timespec="seconds")
        linked = ambiguous = unresolved = changed = 0
        seen: set[tuple[str, str]] = set()

        with self.db.batch():
            for row in rows:
                source = str(row["source_name"] or "")
                stem = str(row["map_stem"] or "")
                version = str(row["source_version"] or "")
                existing_name = str(row["zone_name"] or "")
                seen.add((source, stem))
                chosen, status, reason = self._resolve(stem, existing_name, zones)
                zone_id = chosen.entity_id if chosen is not None else None
                zone_name = chosen.name if chosen is not None else existing_name

                previous = self.db.conn.execute(
                    "SELECT zone_entity_id,zone_name,status,reason,source_version "
                    "FROM zone_map_bindings WHERE source_name=? AND map_stem=?",
                    (source, stem),
                ).fetchone()
                state = (zone_id, zone_name, status, reason, version)
                if previous is None or state != (
                    previous["zone_entity_id"],
                    str(previous["zone_name"] or ""),
                    str(previous["status"] or ""),
                    str(previous["reason"] or ""),
                    str(previous["source_version"] or ""),
                ):
                    changed += 1

                self.db.conn.execute(
                    """
                    INSERT INTO zone_map_bindings(
                        source_name,source_version,map_stem,zone_entity_id,zone_name,
                        status,reason,catalog_version,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_name,map_stem) DO UPDATE SET
                        source_version=excluded.source_version,
                        zone_entity_id=excluded.zone_entity_id,
                        zone_name=excluded.zone_name,
                        status=excluded.status,
                        reason=excluded.reason,
                        catalog_version=excluded.catalog_version,
                        updated_at=excluded.updated_at
                    """,
                    (
                        source,
                        version,
                        stem,
                        zone_id,
                        zone_name,
                        status,
                        reason,
                        ZONE_MAP_CATALOG_VERSION,
                        now,
                    ),
                )

                if chosen is not None:
                    # Backfill the canonical zone name into the existing map catalog so
                    # current zone filtering and entity reconciliation benefit without
                    # maintaining a second query path.
                    self.db.conn.execute(
                        "UPDATE map_sources SET zone_name=? "
                        "WHERE source_name=? AND map_stem=? AND zone_name<>?",
                        (chosen.name, source, stem, chosen.name),
                    )
                    self.db.conn.execute(
                        """
                        UPDATE map_labels SET zone_name=?
                        WHERE source_id IN (
                            SELECT id FROM map_sources WHERE source_name=? AND map_stem=?
                        ) AND zone_name<>?
                        """,
                        (chosen.name, source, stem, chosen.name),
                    )

                if status == "linked":
                    linked += 1
                elif status == "ambiguous":
                    ambiguous += 1
                else:
                    unresolved += 1

            stale = self.db.conn.execute(
                "SELECT source_name,map_stem FROM zone_map_bindings"
                + (" WHERE source_name=?" if source_name else ""),
                args,
            ).fetchall()
            for row in stale:
                key = (str(row["source_name"]), str(row["map_stem"]))
                if key not in seen:
                    self.db.conn.execute(
                        "DELETE FROM zone_map_bindings WHERE source_name=? AND map_stem=?",
                        key,
                    )
                    changed += 1

        return ZoneMapBindingStats(
            maps=len(rows),
            linked=linked,
            ambiguous=ambiguous,
            unresolved=unresolved,
            changed=changed,
        )

    def binding_for_map(self, source_name: str, map_stem: str) -> ZoneMapBinding | None:
        if not self._table_exists():
            return None
        row = self.db.conn.execute(
            "SELECT * FROM zone_map_bindings WHERE source_name=? AND map_stem=?",
            (source_name, map_stem),
        ).fetchone()
        if row is None:
            return None
        return ZoneMapBinding(
            source_name=str(row["source_name"]),
            source_version=str(row["source_version"] or ""),
            map_stem=str(row["map_stem"]),
            zone_entity_id=(int(row["zone_entity_id"]) if row["zone_entity_id"] is not None else None),
            zone_name=str(row["zone_name"] or ""),
            status=str(row["status"]),
            reason=str(row["reason"] or ""),
        )

    def maps_for_zone(self, zone_entity_id: int) -> list[ZoneMapBinding]:
        if not self._table_exists():
            return []
        rows = self.db.conn.execute(
            "SELECT * FROM zone_map_bindings WHERE zone_entity_id=? "
            "ORDER BY source_name,map_stem",
            (int(zone_entity_id),),
        ).fetchall()
        return [
            ZoneMapBinding(
                source_name=str(row["source_name"]),
                source_version=str(row["source_version"] or ""),
                map_stem=str(row["map_stem"]),
                zone_entity_id=int(row["zone_entity_id"]),
                zone_name=str(row["zone_name"] or ""),
                status=str(row["status"]),
                reason=str(row["reason"] or ""),
            )
            for row in rows
        ]
