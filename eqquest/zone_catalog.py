from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json

from .db import Database
from .eqmap import normalize_map_name
from .zone_identity import SHORT_NAME_KEYS, ZoneIdentity, ZoneIdentityIndex


ZONE_MAP_CATALOG_VERSION = "1"


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


class ZoneMapCatalog:
    """Canonical map-stem -> zone identity compiled into EverQuestie knowledge.

    Map packs normally use client short names while logs and knowledge providers tend
    to expose display names. This catalog makes that join explicit and source-aware.
    It deliberately stores unresolved/ambiguous results rather than promoting fuzzy
    guesses into canonical identity.

    Canonical identity signals are owned by :mod:`eqquest.zone_identity`; this class
    only applies the builder-only map-stem inference policy and persists its evidence.
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
        # Builder databases expose a real main-schema table. RuntimeDatabase exposes
        # packaged knowledge tables as TEMP views over its read-only attached DB.
        # Probe both namespaces so the same read API works in either lifecycle.
        return self.db.conn.execute(
            """
            SELECT 1 FROM sqlite_temp_master
            WHERE type IN ('table','view') AND name='zone_map_bindings'
            UNION ALL
            SELECT 1 FROM sqlite_master
            WHERE type IN ('table','view') AND name='zone_map_bindings'
            LIMIT 1
            """
        ).fetchone() is not None

    @staticmethod
    def _resolve(
        map_stem: str,
        existing_zone_name: str,
        identities: ZoneIdentityIndex,
    ) -> tuple[ZoneIdentity | None, str, str]:
        stem = normalize_map_name(map_stem)
        if not stem:
            return None, "unresolved", "empty map stem"

        if existing_zone_name:
            existing = identities.resolve(existing_zone_name)
            if existing.identity is not None:
                return existing.identity, "linked", "existing canonical map-zone name"
            if existing.status == "ambiguous":
                return None, "ambiguous", "existing map-zone name matches multiple zones"

        # Historic map reconciliation intentionally did not treat numeric EQ zone IDs
        # as map filenames. Keep that boundary even though the shared runtime identity
        # service can resolve client IDs when a caller explicitly supplies one.
        if map_stem.strip().isdigit():
            return None, "unresolved", "numeric map stem is not a canonical map identity"

        resolved = identities.resolve(
            map_stem,
            allow_significant_word=True,
            allow_containment=True,
        )
        if resolved.identity is not None:
            reason = {
                "significant_word": "unique significant zone-name word",
                "containment": "unique canonical-name containment",
            }.get(
                resolved.match_kind,
                "exact canonical name/alias/short-name match",
            )
            return resolved.identity, "linked", reason

        if resolved.status == "ambiguous":
            count = len(resolved.candidates)
            if resolved.match_kind == "significant_word":
                return None, "ambiguous", f"map stem is shared by {count} zone names"
            if resolved.match_kind == "containment":
                return None, "ambiguous", f"map stem overlaps {count} zones"
            return None, "ambiguous", f"map stem exactly matches {count} zones"

        return None, "unresolved", "no conservative canonical zone match"

    def _sync_derived_map_short_names(self) -> int:
        """Expose one unambiguous catalog stem to legacy/runtime map-file resolution.

        The map viewer already understands ``data_json.map_short_name``. Builder-owned
        hints let it benefit from the shipped catalog without making runtime rebuild or
        reconcile knowledge. Explicit provider/client hints always win. If map packs
        later disagree, only EverQuestie's own derived hint is removed.
        """
        stems_by_zone: dict[int, dict[str, set[str]]] = {}
        for row in self.db.conn.execute(
            "SELECT zone_entity_id,map_stem FROM zone_map_bindings "
            "WHERE status='linked' AND zone_entity_id IS NOT NULL "
            "ORDER BY zone_entity_id,map_stem"
        ).fetchall():
            zone_id = int(row["zone_entity_id"])
            raw_stem = str(row["map_stem"] or "").strip()
            normalized = normalize_map_name(raw_stem)
            if not normalized:
                continue
            stems_by_zone.setdefault(zone_id, {}).setdefault(normalized, set()).add(raw_stem)

        changed = 0
        for row in self.db.conn.execute(
            "SELECT id,data_json FROM entities WHERE kind='zone' ORDER BY id"
        ).fetchall():
            zone_id = int(row["id"])
            try:
                data = json.loads(row["data_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                data = {}
            if not isinstance(data, dict):
                data = {}

            catalog_owned = str(data.get("map_short_name_source") or "") == "zone_map_catalog"
            explicit_other_hint = any(
                str(data.get(key) or "").strip()
                for key in SHORT_NAME_KEYS
                if key != "map_short_name"
            )
            normalized_stems = stems_by_zone.get(zone_id, {})

            updated = False
            if len(normalized_stems) == 1:
                raw_variants = next(iter(normalized_stems.values()))
                # Equivalent spellings such as stonehive / stone_hive normalize to
                # one identity. Prefer the shortest deterministic filename stem.
                derived = sorted(raw_variants, key=lambda value: (len(value), value.casefold()))[0]
                current = str(data.get("map_short_name") or "").strip()
                if catalog_owned or (not current and not explicit_other_hint):
                    if current != derived or not catalog_owned:
                        data["map_short_name"] = derived
                        data["map_short_name_source"] = "zone_map_catalog"
                        updated = True
            elif catalog_owned:
                data.pop("map_short_name", None)
                data.pop("map_short_name_source", None)
                updated = True

            if updated:
                self.db.conn.execute(
                    "UPDATE entities SET data_json=? WHERE id=?",
                    (json.dumps(data, ensure_ascii=False), zone_id),
                )
                changed += 1
        return changed

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

        # Do not feed the table being derived back into its own identity input. This
        # prevents a stale zone_map_bindings row from preserving itself after stronger
        # provider/client identity evidence changes.
        identities = ZoneIdentityIndex(self.db, include_map_bindings=False)
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
                chosen, status, reason = self._resolve(stem, existing_name, identities)
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

            changed += self._sync_derived_map_short_names()

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
