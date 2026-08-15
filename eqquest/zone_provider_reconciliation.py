from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
from typing import Any

from .db import Database


PROVIDER_ZONE_CATALOG_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ProviderZoneBinding:
    provider_zone_entity_id: int
    gameplay_zone_entity_id: int | None
    provider_zone_name: str
    gameplay_zone_name: str
    status: str
    reason: str
    corroboration_count: int
    evidence: tuple[dict[str, Any], ...]

    @property
    def projection_safe(self) -> bool:
        return self.status == "linked" and self.gameplay_zone_entity_id is not None


@dataclass(frozen=True, slots=True)
class ProviderZoneReconciliationStats:
    provider_zones: int
    linked: int
    candidate: int
    ambiguous: int
    unresolved: int
    corroborating_relationships: int

    def as_dict(self) -> dict[str, int]:
        return {
            "provider_zones": self.provider_zones,
            "linked": self.linked,
            "candidate": self.candidate,
            "ambiguous": self.ambiguous,
            "unresolved": self.unresolved,
            "corroborating_relationships": self.corroborating_relationships,
        }


class ProviderZoneReconciliationCatalog:
    """Builder-owned bindings from provider zone entities to gameplay zone identity.

    Provider entities are intentionally preserved.  A binding is a projection rule,
    not an entity merge: provenance, provider external IDs, source pages and graph rows
    continue to point at the original provider entity.

    Exact same-name matching alone is deliberately insufficient for automatic
    projection.  The first conservative linker requires exactly one EQ-client-backed
    zone with the same normalized canonical name *and* at least one structured
    provider ``connected_to`` relationship whose neighboring zone independently has a
    unique EQ-client same-name target.  This turns the provider's own topology into
    corroborating identity evidence instead of treating a display name as proof.
    """

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

    def ensure_schema(self) -> None:
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("provider zone reconciliation is builder-only")
        self.db.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS zone_provider_bindings (
                provider_zone_entity_id INTEGER PRIMARY KEY
                    REFERENCES entities(id) ON DELETE CASCADE,
                gameplay_zone_entity_id INTEGER
                    REFERENCES entities(id) ON DELETE SET NULL,
                provider_zone_name TEXT NOT NULL,
                gameplay_zone_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                corroboration_count INTEGER NOT NULL DEFAULT 0,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                catalog_version TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_zone_provider_bindings_gameplay
            ON zone_provider_bindings(gameplay_zone_entity_id,status);
            CREATE INDEX IF NOT EXISTS ix_zone_provider_bindings_status
            ON zone_provider_bindings(status);
            """
        )
        self.db._commit()

    def _zone_inventory(self):
        zones = self.db.conn.execute(
            "SELECT id,name,normalized_name FROM entities WHERE kind='zone' ORDER BY id"
        ).fetchall()
        client_ids: dict[int, list[str]] = defaultdict(list)
        if self._relation_exists("entity_external_ids"):
            for row in self.db.conn.execute(
                """
                SELECT entity_id,external_id
                FROM entity_external_ids
                WHERE namespace='eqclient:zone'
                ORDER BY entity_id,external_id
                """
            ).fetchall():
                client_ids[int(row["entity_id"])].append(str(row["external_id"]))

        by_name: dict[str, list[int]] = defaultdict(list)
        names: dict[int, str] = {}
        normalized: dict[int, str] = {}
        for row in zones:
            entity_id = int(row["id"])
            names[entity_id] = str(row["name"])
            normalized[entity_id] = str(row["normalized_name"])
            by_name[normalized[entity_id]].append(entity_id)

        client_targets_by_name: dict[str, tuple[int, ...]] = {}
        for key, entity_ids in by_name.items():
            client_targets_by_name[key] = tuple(
                entity_id for entity_id in entity_ids if client_ids.get(entity_id)
            )
        return zones, client_ids, names, normalized, client_targets_by_name

    @staticmethod
    def _structured_provider_relationship(row) -> bool:
        source_name = str(row["source_name"] or "")
        if not source_name:
            return False
        try:
            data = json.loads(row["data_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        # Allakhazam's Connected Zones extractor has always represented explicit table
        # rows as connected_to relationships.  Newer rows also carry confidence=structured.
        return source_name.casefold() == "allakhazam" or data.get("confidence") == "structured"

    def _corroboration_for_provider_zone(
        self,
        provider_zone_entity_id: int,
        *,
        normalized: dict[int, str],
        client_targets_by_name: dict[str, tuple[int, ...]],
        names: dict[int, str],
    ) -> tuple[dict[str, Any], ...]:
        if not (
            self._relation_exists("entity_relationships")
            and self._relation_exists("source_pages")
        ):
            return ()
        rows = self.db.conn.execute(
            """
            SELECT r.id,r.source_entity_id,r.target_entity_id,r.evidence,r.data_json,
                   sp.source_name,sp.source_kind,sp.source_key,sp.source_version
            FROM entity_relationships r
            LEFT JOIN source_pages sp ON sp.id=r.source_page_id
            WHERE r.relation='connected_to'
              AND (r.source_entity_id=? OR r.target_entity_id=?)
            ORDER BY r.id
            """,
            (int(provider_zone_entity_id), int(provider_zone_entity_id)),
        ).fetchall()

        evidence: list[dict[str, Any]] = []
        for row in rows:
            if not self._structured_provider_relationship(row):
                continue
            source_id = int(row["source_entity_id"])
            target_id = int(row["target_entity_id"])
            neighbor_id = target_id if source_id == int(provider_zone_entity_id) else source_id
            neighbor_key = normalized.get(neighbor_id, "")
            client_targets = client_targets_by_name.get(neighbor_key, ())
            if len(client_targets) != 1:
                continue
            client_neighbor_id = int(client_targets[0])
            evidence.append(
                {
                    "relationship_id": int(row["id"]),
                    "direction": "outgoing" if source_id == int(provider_zone_entity_id) else "incoming",
                    "provider_neighbor_entity_id": neighbor_id,
                    "provider_neighbor_name": names.get(neighbor_id, ""),
                    "gameplay_neighbor_entity_id": client_neighbor_id,
                    "gameplay_neighbor_name": names.get(client_neighbor_id, ""),
                    "source_name": str(row["source_name"] or ""),
                    "source_kind": str(row["source_kind"] or ""),
                    "source_key": str(row["source_key"] or ""),
                    "source_version": str(row["source_version"] or ""),
                    "evidence": str(row["evidence"] or ""),
                }
            )
        return tuple(evidence)

    def reconcile(self) -> ProviderZoneReconciliationStats:
        if not getattr(self.db, "knowledge_writable", True):
            raise RuntimeError("provider zone reconciliation is builder-only")
        self.ensure_schema()
        zones, client_ids, names, normalized, client_targets_by_name = self._zone_inventory()
        now = datetime.now().isoformat(timespec="seconds")

        provider_zone_ids = [int(row["id"]) for row in zones if not client_ids.get(int(row["id"]))]
        counts = {"linked": 0, "candidate": 0, "ambiguous": 0, "unresolved": 0}
        corroborating_relationship_ids: set[int] = set()

        with self.db.batch():
            self.db.conn.execute("DELETE FROM zone_provider_bindings")
            for provider_id in provider_zone_ids:
                key = normalized.get(provider_id, "")
                client_targets = client_targets_by_name.get(key, ())
                target_id: int | None = None
                target_name = ""
                corroboration: tuple[dict[str, Any], ...] = ()

                if not client_targets:
                    status = "unresolved"
                    reason = "no EQ-client-backed zone has this exact canonical name"
                elif len(client_targets) > 1:
                    status = "ambiguous"
                    reason = "multiple EQ-client-backed zones share this exact canonical name"
                else:
                    target_id = int(client_targets[0])
                    target_name = names.get(target_id, "")
                    corroboration = self._corroboration_for_provider_zone(
                        provider_id,
                        normalized=normalized,
                        client_targets_by_name=client_targets_by_name,
                        names=names,
                    )
                    if corroboration:
                        status = "linked"
                        reason = (
                            "unique exact-name EQ-client target corroborated by structured "
                            "provider connected-zone evidence"
                        )
                    else:
                        status = "candidate"
                        reason = (
                            "unique exact-name EQ-client target exists but lacks independent "
                            "structured provider corroboration"
                        )

                counts[status] += 1
                corroborating_relationship_ids.update(
                    int(item["relationship_id"])
                    for item in corroboration
                    if item.get("relationship_id") is not None
                )
                self.db.conn.execute(
                    """
                    INSERT INTO zone_provider_bindings(
                        provider_zone_entity_id,gameplay_zone_entity_id,
                        provider_zone_name,gameplay_zone_name,status,reason,
                        corroboration_count,evidence_json,catalog_version,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        provider_id,
                        target_id,
                        names.get(provider_id, ""),
                        target_name,
                        status,
                        reason,
                        len(corroboration),
                        json.dumps(corroboration, ensure_ascii=False, sort_keys=True),
                        PROVIDER_ZONE_CATALOG_VERSION,
                        now,
                    ),
                )

            stats = ProviderZoneReconciliationStats(
                provider_zones=len(provider_zone_ids),
                linked=counts["linked"],
                candidate=counts["candidate"],
                ambiguous=counts["ambiguous"],
                unresolved=counts["unresolved"],
                corroborating_relationships=len(corroborating_relationship_ids),
            )
            self.db.set_meta("provider_zone_catalog_version", PROVIDER_ZONE_CATALOG_VERSION)
            self.db.set_meta(
                "provider_zone_catalog_coverage",
                json.dumps(stats.as_dict(), sort_keys=True, separators=(",", ":")),
            )
        return stats

    @staticmethod
    def _binding(row) -> ProviderZoneBinding:
        try:
            raw = json.loads(row["evidence_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            raw = []
        if not isinstance(raw, list):
            raw = []
        evidence = tuple(item for item in raw if isinstance(item, dict))
        return ProviderZoneBinding(
            provider_zone_entity_id=int(row["provider_zone_entity_id"]),
            gameplay_zone_entity_id=(
                int(row["gameplay_zone_entity_id"])
                if row["gameplay_zone_entity_id"] is not None
                else None
            ),
            provider_zone_name=str(row["provider_zone_name"] or ""),
            gameplay_zone_name=str(row["gameplay_zone_name"] or ""),
            status=str(row["status"] or "unresolved"),
            reason=str(row["reason"] or ""),
            corroboration_count=int(row["corroboration_count"] or 0),
            evidence=evidence,
        )

    def binding_for_provider_zone(self, provider_zone_entity_id: int) -> ProviderZoneBinding | None:
        if not self._relation_exists("zone_provider_bindings"):
            return None
        row = self.db.conn.execute(
            "SELECT * FROM zone_provider_bindings WHERE provider_zone_entity_id=?",
            (int(provider_zone_entity_id),),
        ).fetchone()
        return self._binding(row) if row is not None else None

    def bindings_for_gameplay_zone(
        self,
        gameplay_zone_entity_id: int,
        *,
        linked_only: bool = True,
    ) -> tuple[ProviderZoneBinding, ...]:
        if not self._relation_exists("zone_provider_bindings"):
            return ()
        sql = "SELECT * FROM zone_provider_bindings WHERE gameplay_zone_entity_id=?"
        args: list[object] = [int(gameplay_zone_entity_id)]
        if linked_only:
            sql += " AND status='linked'"
        sql += " ORDER BY provider_zone_name,provider_zone_entity_id"
        return tuple(self._binding(row) for row in self.db.conn.execute(sql, args).fetchall())

    def projected_zone_entity_ids(self, gameplay_zone_entity_id: int) -> tuple[int, ...]:
        """Return canonical gameplay zone first, then projection-safe provider zones."""
        canonical = int(gameplay_zone_entity_id)
        provider_ids = [
            binding.provider_zone_entity_id
            for binding in self.bindings_for_gameplay_zone(canonical, linked_only=True)
        ]
        return tuple(dict.fromkeys([canonical, *provider_ids]))
