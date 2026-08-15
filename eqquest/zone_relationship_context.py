from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .db import Database


ZONE_CONTEXT_RELATIONS = ("found_in", "starts_in", "occurs_in")


@dataclass(frozen=True, slots=True)
class ZoneRelatedEntity:
    """One evidence statement relating a canonical entity to a gameplay zone.

    ``zone_entity_id`` is always the canonical gameplay-zone identity exposed to the
    caller. ``original_zone_entity_id`` identifies the zone row the relationship was
    actually stored against. When those differ, the statement crossed a finalized
    provider-zone binding and ``projected_from_zone_entity_id`` names that provider row.
    """

    relationship_id: int
    entity_id: int
    name: str
    kind: str
    relation: str
    zone_entity_id: int
    zone_name: str
    original_zone_entity_id: int
    original_zone_name: str
    projected_from_zone_entity_id: int | None
    source_name: str
    source_kind: str
    source_key: str
    source_version: str
    source_page_id: int | None
    evidence: str
    confidence: str
    preview: bool
    shown: int | None
    total: int | None
    source_field: str
    data: dict[str, Any]

    @property
    def source_label(self) -> str:
        source = self.source_name or "EverQuestie knowledge"
        if self.source_version:
            source += f" {self.source_version}"
        return source

    @property
    def preview_text(self) -> str:
        if not self.preview:
            return ""
        if self.shown is not None and self.total is not None:
            return f"preview {self.shown} of {self.total}"
        if self.total is not None:
            return f"preview of {self.total} total"
        if self.shown is not None:
            return f"preview showing {self.shown}"
        return "preview"


def _relation_exists(db: Database, name: str) -> bool:
    return db.conn.execute(
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


def _data(row) -> dict[str, Any]:
    try:
        value = json.loads(row["data_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _maybe_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _structured_provider_evidence(row, data: dict[str, Any]) -> bool:
    """Gate facts that cross from a provider zone into gameplay context.

    Allakhazam's supported zone/NPC/item/quest extractors are structured parsers and
    legacy rows may predate explicit confidence metadata. Other/future sources need the
    structured marker. Missing source provenance never qualifies for projection.
    """
    source_name = str(row["source_name"] or "").strip()
    if not source_name:
        return False
    if source_name.casefold() == "allakhazam":
        return True
    return str(data.get("confidence") or "").casefold() == "structured"


def related_entities_for_zone(
    db: Database,
    gameplay_zone_entity_id: int,
    projected_zone_entity_ids: tuple[int, ...],
    *,
    limit: int = 1000,
) -> tuple[ZoneRelatedEntity, ...]:
    """Project structured entity→zone relationships into canonical gameplay space.

    This is read-only and intentionally limited to relationship kinds whose orientation
    is already unambiguous in the normalized graph. Travel ``connected_to`` evidence is
    handled by the travel catalog instead of being duplicated here.
    """
    if not _relation_exists(db, "entity_relationships"):
        return ()

    canonical = int(gameplay_zone_entity_id)
    zone_ids = tuple(dict.fromkeys(int(value) for value in projected_zone_entity_ids))
    if canonical not in zone_ids:
        zone_ids = (canonical, *zone_ids)
    if not zone_ids:
        return ()

    canonical_row = db.entity(canonical)
    canonical_name = str(canonical_row["name"] or "") if canonical_row is not None else ""
    zone_placeholders = ",".join("?" for _ in zone_ids)
    relation_placeholders = ",".join("?" for _ in ZONE_CONTEXT_RELATIONS)
    rows = db.conn.execute(
        f"""
        SELECT r.id AS relationship_id,r.source_entity_id AS entity_id,
               r.target_entity_id AS stored_zone_entity_id,r.relation,r.evidence,r.data_json,
               e.name AS entity_name,e.kind AS entity_kind,
               z.name AS stored_zone_name,
               sp.id AS source_page_id,sp.source_name,sp.source_kind,
               sp.source_key,sp.source_version,sp.url
        FROM entity_relationships r
        JOIN entities e ON e.id=r.source_entity_id
        JOIN entities z ON z.id=r.target_entity_id
        LEFT JOIN source_pages sp ON sp.id=r.source_page_id
        WHERE r.target_entity_id IN ({zone_placeholders})
          AND r.relation IN ({relation_placeholders})
          AND e.kind<>'zone'
        ORDER BY r.relation,e.kind,e.name,
                 COALESCE(sp.source_name,''),COALESCE(sp.source_key,''),r.id
        LIMIT ?
        """,
        (*zone_ids, *ZONE_CONTEXT_RELATIONS, max(1, int(limit))),
    ).fetchall()

    result: list[ZoneRelatedEntity] = []
    for row in rows:
        original_zone_id = int(row["stored_zone_entity_id"])
        data = _data(row)
        projected_from = original_zone_id if original_zone_id != canonical else None
        if projected_from is not None and not _structured_provider_evidence(row, data):
            continue

        result.append(
            ZoneRelatedEntity(
                relationship_id=int(row["relationship_id"]),
                entity_id=int(row["entity_id"]),
                name=str(row["entity_name"] or ""),
                kind=str(row["entity_kind"] or ""),
                relation=str(row["relation"] or ""),
                zone_entity_id=canonical,
                zone_name=canonical_name or str(row["stored_zone_name"] or ""),
                original_zone_entity_id=original_zone_id,
                original_zone_name=str(row["stored_zone_name"] or ""),
                projected_from_zone_entity_id=projected_from,
                source_name=str(row["source_name"] or "EverQuestie knowledge"),
                source_kind=str(row["source_kind"] or ""),
                source_key=str(row["source_key"] or row["url"] or ""),
                source_version=str(row["source_version"] or ""),
                source_page_id=(
                    int(row["source_page_id"])
                    if row["source_page_id"] is not None
                    else None
                ),
                evidence=str(row["evidence"] or ""),
                confidence=str(data.get("confidence") or ""),
                preview=bool(data.get("preview", False)),
                shown=_maybe_int(data.get("shown")),
                total=_maybe_int(data.get("total")),
                source_field=str(data.get("source_field") or ""),
                data=data,
            )
        )
    return tuple(result)
