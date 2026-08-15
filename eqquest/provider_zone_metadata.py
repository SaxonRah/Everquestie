from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .db import Database


@dataclass(frozen=True, slots=True)
class ProviderZoneMetadata:
    """One source-specific zone metadata statement projected onto gameplay identity.

    The provider zone remains a distinct entity. These values are evidence attached to
    that provider row and must not be interpreted as mutations of the canonical
    EQ-client gameplay-zone entity.
    """

    provider_zone_entity_id: int
    gameplay_zone_entity_id: int
    provider_zone_name: str
    gameplay_zone_name: str
    provider_external_id: str
    level_min: int | None
    level_max: int | None
    zone_type: str
    expansion: str
    instanced: str
    keyed: str
    hot_zone: bool | None
    source_name: str
    source_kind: str
    source_key: str
    source_version: str
    source_page_id: int | None
    source_url: str
    binding_reason: str
    corroboration_count: int
    data: dict[str, Any]

    @property
    def source_label(self) -> str:
        source = self.source_name or "Provider knowledge"
        if self.source_version:
            source += f" {self.source_version}"
        return source

    @property
    def level_range_text(self) -> str:
        if self.level_min is None and self.level_max is None:
            return ""
        lo = str(self.level_min) if self.level_min is not None else "?"
        hi = str(self.level_max) if self.level_max is not None else "?"
        return f"{lo}-{hi}"


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


def _data(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _optional_bool(data: dict[str, Any], key: str) -> bool | None:
    if key not in data:
        return None
    value = data.get(key)
    if isinstance(value, bool):
        return value
    return None


def provider_zone_metadata_for_gameplay_zone(
    db: Database,
    gameplay_zone_entity_id: int,
) -> tuple[ProviderZoneMetadata, ...]:
    """Read finalized provider-zone metadata linked safely to one gameplay zone.

    This function never performs reconciliation and never writes. Only bindings already
    finalized with ``status='linked'`` are eligible, so it is safe to use against the
    immutable packaged RuntimeDatabase views.
    """
    if not _relation_exists(db, "zone_provider_bindings"):
        return ()

    rows = db.conn.execute(
        """
        SELECT b.provider_zone_entity_id,b.gameplay_zone_entity_id,
               b.provider_zone_name,b.gameplay_zone_name,b.reason,
               b.corroboration_count,
               e.external_id,e.level_min,e.level_max,e.data_json,
               e.source_page_id,e.source_url,
               sp.source_name,sp.source_kind,sp.source_key,sp.source_version,sp.url
        FROM zone_provider_bindings b
        JOIN entities e ON e.id=b.provider_zone_entity_id
        LEFT JOIN source_pages sp ON sp.id=e.source_page_id
        WHERE b.gameplay_zone_entity_id=?
          AND b.status='linked'
        ORDER BY COALESCE(sp.source_name,''),b.provider_zone_name,b.provider_zone_entity_id
        """,
        (int(gameplay_zone_entity_id),),
    ).fetchall()

    result: list[ProviderZoneMetadata] = []
    for row in rows:
        data = _data(row["data_json"])
        source_url = _text(row["source_url"]) or _text(row["url"])
        result.append(
            ProviderZoneMetadata(
                provider_zone_entity_id=int(row["provider_zone_entity_id"]),
                gameplay_zone_entity_id=int(row["gameplay_zone_entity_id"]),
                provider_zone_name=_text(row["provider_zone_name"]),
                gameplay_zone_name=_text(row["gameplay_zone_name"]),
                provider_external_id=_text(row["external_id"]),
                level_min=(
                    int(row["level_min"])
                    if row["level_min"] is not None
                    else None
                ),
                level_max=(
                    int(row["level_max"])
                    if row["level_max"] is not None
                    else None
                ),
                zone_type=_text(data.get("zone_type")),
                expansion=_text(data.get("expansion")),
                instanced=_text(data.get("instanced")),
                keyed=_text(data.get("keyed")),
                hot_zone=_optional_bool(data, "hot_zone"),
                source_name=_text(row["source_name"]) or "Provider knowledge",
                source_kind=_text(row["source_kind"]),
                source_key=_text(row["source_key"]) or source_url,
                source_version=_text(row["source_version"]),
                source_page_id=(
                    int(row["source_page_id"])
                    if row["source_page_id"] is not None
                    else None
                ),
                source_url=source_url,
                binding_reason=_text(row["reason"]),
                corroboration_count=int(row["corroboration_count"] or 0),
                data=data,
            )
        )
    return tuple(result)
