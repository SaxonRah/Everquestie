from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from .db import Database
from .zone_travel import ZoneTravelCatalog


PROVIDER_ZONE_TRAVEL_CATALOG_VERSION = "2"


@dataclass(frozen=True, slots=True)
class ProviderZoneTravelStats:
    relationships_scanned: int
    linked: int
    ignored_unstructured: int
    blocked_source: int
    blocked_target: int
    self_edges: int

    def as_dict(self) -> dict[str, int]:
        return {
            "relationships_scanned": self.relationships_scanned,
            "linked": self.linked,
            "ignored_unstructured": self.ignored_unstructured,
            "blocked_source": self.blocked_source,
            "blocked_target": self.blocked_target,
            "self_edges": self.self_edges,
        }


@dataclass(frozen=True, slots=True)
class ProviderTravelDirection:
    """Canonical orientation derived only from structured provider direction text."""

    reverse: bool
    bidirectional: bool
    mode: str
    raw: str


class ProviderZoneTravelCatalog:
    """Compile structured provider zone relationships into canonical travel edges.

    The provider graph remains source evidence. Runtime routes operate only on canonical
    gameplay zone IDs, so each endpoint must either already be an EQ-client-backed zone
    or have a projection-safe ``zone_provider_bindings`` row. No provider relationship
    is used to break an ambiguous/unresolved gameplay identity here.

    ``connected_to`` is compiled according to source-owned structured direction data.
    Allakhazam's Connected Zones table currently uses values such as ``Both``,
    ``Entrance To <zone>`` and ``Exit From <zone>``. ``Both`` is explicit evidence for
    reciprocal travel. ``Exit From <exact target>`` reverses the canonical edge because
    the saved page is naming a route that exits the target into the page's current zone.
    Unknown or descriptive direction strings retain the historical source→target
    orientation and are never promoted to reciprocal travel by inference.
    """

    SOURCE_KIND = "provider_zone_relationship"

    def __init__(self, db: Database):
        self.db = db

    def _relation_exists(self, name: str) -> bool:
        return self.db.conn.execute(
            """
            SELECT 1 FROM sqlite_temp_master
            WHERE type IN ('table','view') AND name=?
            UNION ALL
            SELECT 1 FROM sqlite_master
            WHERE type IN ('table','view') AND name=?
            LIMIT 1
            """,
            (name, name),
        ).fetchone() is not None

    def _client_zone_ids(self) -> set[int]:
        if not self._relation_exists("entity_external_ids"):
            return set()
        return {
            int(row["entity_id"])
            for row in self.db.conn.execute(
                "SELECT DISTINCT entity_id FROM entity_external_ids WHERE namespace='eqclient:zone'"
            ).fetchall()
        }

    def _binding_map(self) -> dict[int, int]:
        if not self._relation_exists("zone_provider_bindings"):
            return {}
        return {
            int(row["provider_zone_entity_id"]): int(row["gameplay_zone_entity_id"])
            for row in self.db.conn.execute(
                """
                SELECT provider_zone_entity_id,gameplay_zone_entity_id
                FROM zone_provider_bindings
                WHERE status='linked' AND gameplay_zone_entity_id IS NOT NULL
                """
            ).fetchall()
        }

    @staticmethod
    def _canonical_endpoint(
        entity_id: int,
        *,
        client_zone_ids: set[int],
        provider_bindings: dict[int, int],
    ) -> int | None:
        entity_id = int(entity_id)
        if entity_id in client_zone_ids:
            return entity_id
        return provider_bindings.get(entity_id)

    @staticmethod
    def _relationship_data(row) -> dict[str, Any]:
        try:
            value = json.loads(row["relationship_data_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _structured_provider_relationship(cls, row) -> bool:
        """Return true only for source-owned structured topology evidence.

        Allakhazam's Connected Zones extractor is itself a structured table parser and
        older rows may predate the explicit confidence marker. Other/future providers
        must mark the relationship ``confidence=structured`` before it is routeable.
        Rows without source provenance are never accepted.
        """
        source_name = str(row["source_name"] or "").strip()
        if not source_name:
            return False
        data = cls._relationship_data(row)
        if source_name.casefold() == "allakhazam":
            return True
        return str(data.get("confidence") or "").casefold() == "structured"

    @staticmethod
    def _direction_name_key(value: str) -> str:
        return " ".join((value or "").casefold().split())

    @classmethod
    def _direction_semantics(cls, row) -> ProviderTravelDirection:
        """Interpret only direction spellings whose topology meaning is explicit.

        The Allakhazam Connected Zones table is source-owned structured data, but the
        contents of its Direction column are not all topology operators. Compass text
        and any future unknown value therefore stay forward-only. Prefix forms are
        accepted only when the embedded zone name exactly matches the relationship's
        structured target name; this prevents prose that merely starts with ``Exit
        From`` or ``Entrance To`` from silently changing graph orientation.
        """
        data = cls._relationship_data(row)
        raw = " ".join(str(data.get("direction") or "").split())
        folded = raw.casefold()
        if folded == "both":
            return ProviderTravelDirection(False, True, "both", raw)

        target_name = str(row["target_name"] or "")
        target_key = cls._direction_name_key(target_name)
        for prefix, reverse, mode in (
            ("exit from ", True, "exit_from_target"),
            ("entrance to ", False, "entrance_to_target"),
        ):
            if not folded.startswith(prefix):
                continue
            named_target = raw[len(prefix):].strip()
            if target_key and cls._direction_name_key(named_target) == target_key:
                return ProviderTravelDirection(reverse, False, mode, raw)

        return ProviderTravelDirection(False, False, "forward_unclassified", raw)

    @staticmethod
    def _source_key(row) -> str:
        page_key = str(row["source_key"] or row["source_url"] or "provider-zone")
        target_key = str(row["target_external_id"] or "").strip()
        if not target_key:
            target_key = str(row["target_normalized_name"] or row["target_name"] or "target")
        return f"{page_key}#connected_to:{target_key}"

    @classmethod
    def _relationship_payload(
        cls,
        row,
        *,
        direction: ProviderTravelDirection | None = None,
    ) -> dict[str, Any]:
        payload = {
            "provider_relationship_id": int(row["relationship_id"]),
            "provider_source_zone_entity_id": int(row["source_entity_id"]),
            "provider_target_zone_entity_id": int(row["target_entity_id"]),
            "provider_source_zone_name": str(row["source_name_entity"] or ""),
            "provider_target_zone_name": str(row["target_name"] or ""),
            "provider_source_external_id": str(row["source_external_id"] or ""),
            "provider_target_external_id": str(row["target_external_id"] or ""),
            "relationship_data": cls._relationship_data(row),
        }
        if direction is not None:
            payload["provider_direction"] = {
                "raw": direction.raw,
                "mode": direction.mode,
                "reversed": direction.reverse,
                "bidirectional": direction.bidirectional,
            }
        return payload

    def reconcile(self, *, source_name: str | None = None) -> ProviderZoneTravelStats:
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("provider zone travel compilation is builder-only")

        ZoneTravelCatalog(self.db).ensure_schema()
        client_zone_ids = self._client_zone_ids()
        provider_bindings = self._binding_map()

        delete_sql = "DELETE FROM zone_travel_edges WHERE source_kind=?"
        delete_args: list[object] = [self.SOURCE_KIND]
        if source_name:
            delete_sql += " AND source_name=?"
            delete_args.append(source_name)

        if not self._relation_exists("entity_relationships"):
            with self.db.batch():
                self.db.conn.execute(delete_sql, delete_args)
            return ProviderZoneTravelStats(0, 0, 0, 0, 0, 0)

        where = "WHERE r.relation='connected_to' AND se.kind='zone' AND te.kind='zone'"
        args: list[object] = []
        if source_name:
            where += " AND sp.source_name=?"
            args.append(source_name)
        rows = self.db.conn.execute(
            """
            SELECT r.id AS relationship_id,r.source_entity_id,r.target_entity_id,
                   r.evidence,r.data_json AS relationship_data_json,
                   se.name AS source_name_entity,se.normalized_name AS source_normalized_name,
                   se.external_id AS source_external_id,
                   te.name AS target_name,te.normalized_name AS target_normalized_name,
                   te.external_id AS target_external_id,
                   sp.id AS source_page_id,sp.source_name,sp.source_kind AS source_page_kind,
                   sp.source_key,sp.source_version,sp.url AS source_url
            FROM entity_relationships r
            JOIN entities se ON se.id=r.source_entity_id
            JOIN entities te ON te.id=r.target_entity_id
            LEFT JOIN source_pages sp ON sp.id=r.source_page_id
            """
            + where
            + " ORDER BY COALESCE(sp.source_name,''),COALESCE(sp.source_key,''),r.id",
            args,
        ).fetchall()

        linked = ignored_unstructured = blocked_source = blocked_target = self_edges = 0
        now = datetime.now().isoformat(timespec="seconds")
        with self.db.batch():
            self.db.conn.execute(delete_sql, delete_args)
            for row in rows:
                if not self._structured_provider_relationship(row):
                    ignored_unstructured += 1
                    continue

                canonical_source = self._canonical_endpoint(
                    int(row["source_entity_id"]),
                    client_zone_ids=client_zone_ids,
                    provider_bindings=provider_bindings,
                )
                if canonical_source is None:
                    blocked_source += 1
                    continue
                canonical_target = self._canonical_endpoint(
                    int(row["target_entity_id"]),
                    client_zone_ids=client_zone_ids,
                    provider_bindings=provider_bindings,
                )
                if canonical_target is None:
                    blocked_target += 1
                    continue
                if canonical_source == canonical_target:
                    self_edges += 1
                    continue

                direction = self._direction_semantics(row)
                edge_source = canonical_target if direction.reverse else canonical_source
                edge_target = canonical_source if direction.reverse else canonical_target

                provider_name = str(row["source_name"] or "Provider knowledge")
                source_key = self._source_key(row)
                payload = self._relationship_payload(row, direction=direction)
                self.db.conn.execute(
                    """
                    INSERT INTO zone_travel_edges(
                        source_zone_entity_id,target_zone_entity_id,connection_kind,
                        bidirectional,status,reason,evidence,source_name,source_kind,
                        source_key,source_version,source_page_id,data_json,
                        catalog_version,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_kind,source_name,source_key,connection_kind)
                    DO UPDATE SET
                        source_zone_entity_id=excluded.source_zone_entity_id,
                        target_zone_entity_id=excluded.target_zone_entity_id,
                        bidirectional=excluded.bidirectional,
                        status='linked',
                        reason=excluded.reason,
                        evidence=excluded.evidence,
                        source_version=excluded.source_version,
                        source_page_id=excluded.source_page_id,
                        data_json=excluded.data_json,
                        catalog_version=excluded.catalog_version,
                        updated_at=excluded.updated_at
                    """,
                    (
                        edge_source,
                        edge_target,
                        "zone_connection",
                        int(direction.bidirectional),
                        "linked",
                        "provider connected-zone relationship mapped through projection-safe zone bindings",
                        str(row["evidence"] or ""),
                        provider_name,
                        self.SOURCE_KIND,
                        source_key,
                        str(row["source_version"] or ""),
                        int(row["source_page_id"]) if row["source_page_id"] is not None else None,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        PROVIDER_ZONE_TRAVEL_CATALOG_VERSION,
                        now,
                    ),
                )
                linked += 1

            stats = ProviderZoneTravelStats(
                relationships_scanned=len(rows),
                linked=linked,
                ignored_unstructured=ignored_unstructured,
                blocked_source=blocked_source,
                blocked_target=blocked_target,
                self_edges=self_edges,
            )
            self.db.set_meta(
                "provider_zone_travel_catalog_version",
                PROVIDER_ZONE_TRAVEL_CATALOG_VERSION,
            )
            self.db.set_meta(
                "provider_zone_travel_catalog_coverage",
                json.dumps(stats.as_dict(), sort_keys=True, separators=(",", ":")),
            )
        return stats
