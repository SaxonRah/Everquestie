from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .db import Database, normalize_name
from .world_profiles import p99_expansion_allowed


@dataclass(frozen=True, slots=True)
class EntityExpansionEvidence:
    entity_id: int
    entity_kind: str
    entity_name: str
    expansion: str
    source_name: str
    source_kind: str
    source_key: str
    source_page_id: int | None
    origin: str

    @property
    def source_label(self) -> str:
        label = self.source_name or self.source_kind or self.origin
        if self.source_key:
            label += f" [{self.source_key}]"
        return label


@dataclass(frozen=True, slots=True)
class EntityLifecycleDecision:
    entity_id: int
    entity_kind: str
    entity_name: str
    profile_id: str
    compatibility: bool | None
    status: str
    reason: str
    evidence: tuple[EntityExpansionEvidence, ...] = ()

    @property
    def definitive(self) -> bool:
        return self.compatibility is not None


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def expansion_text(data: dict[str, Any]) -> str:
    """Return an explicit top-level lifecycle/expansion statement, if present."""
    for key in ("expansion", "expansion_name", "era"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return " ".join(str(value).split())
    return ""


def _source_fields(row, *, fallback_name: str, fallback_kind: str) -> tuple[str, str, str, int | None]:
    source_page_id = (
        int(row["source_page_id"])
        if row["source_page_id"] is not None
        else None
    )
    return (
        str(row["source_name"] or fallback_name),
        str(row["source_kind"] or fallback_kind),
        str(row["source_key"] or ""),
        source_page_id,
    )


def entity_expansion_evidence(
    db: Database,
    entity_id: int,
) -> tuple[EntityExpansionEvidence, ...]:
    """Read explicit source-backed expansion statements already stored for an entity.

    The current shipped corpus can expose expansion evidence through two normalized
    surfaces without a schema migration:

    * ``entities.data_json`` — e.g. structured Allakhazam NPC/zone fields;
    * ``entity_details.detail_json`` — e.g. rich MCP records when their actual local
      getter emits an explicit expansion field.

    Only top-level explicit fields are accepted. Text descriptions, locations, names,
    dates, IDs, and expansion-adjacent prose are never parsed into lifecycle truth.
    """
    entity = db.entity(int(entity_id))
    if entity is None:
        return ()

    base = db.conn.execute(
        """
        SELECT e.id,e.kind,e.name,e.data_json,e.source_page_id,
               sp.source_name,sp.source_kind,sp.source_key
        FROM entities e
        LEFT JOIN source_pages sp ON sp.id=e.source_page_id
        WHERE e.id=?
        """,
        (int(entity_id),),
    ).fetchone()
    if base is None:
        return ()

    result: list[EntityExpansionEvidence] = []
    seen: set[tuple[str, str, int | None]] = set()

    def add(expansion: str, row, origin: str, fallback_name: str, fallback_kind: str) -> None:
        text = " ".join(str(expansion or "").split()).strip()
        if not text:
            return
        source_name, source_kind, source_key, source_page_id = _source_fields(
            row,
            fallback_name=fallback_name,
            fallback_kind=fallback_kind,
        )
        key = (normalize_name(text), origin, source_page_id)
        if key in seen:
            return
        seen.add(key)
        result.append(
            EntityExpansionEvidence(
                entity_id=int(base["id"]),
                entity_kind=str(base["kind"] or ""),
                entity_name=str(base["name"] or ""),
                expansion=text,
                source_name=source_name,
                source_kind=source_kind,
                source_key=source_key,
                source_page_id=source_page_id,
                origin=origin,
            )
        )

    base_expansion = expansion_text(_json_object(base["data_json"]))
    if base_expansion:
        add(
            base_expansion,
            base,
            "entity.data_json",
            "EverQuestie normalized entity",
            "entity_data",
        )

    # entity_details is a one-row canonical projection. The full MCP source-granular
    # records remain preserved elsewhere; this read path intentionally consumes only
    # the canonical detail attached to this exact entity ID.
    try:
        detail = db.conn.execute(
            """
            SELECT d.detail_json,d.source_page_id,
                   sp.source_name,sp.source_kind,sp.source_key
            FROM entity_details d
            LEFT JOIN source_pages sp ON sp.id=d.source_page_id
            WHERE d.entity_id=?
            """,
            (int(entity_id),),
        ).fetchone()
    except Exception:
        detail = None
    if detail is not None:
        detail_expansion = expansion_text(_json_object(detail["detail_json"]))
        if detail_expansion:
            add(
                detail_expansion,
                detail,
                "entity_details.detail_json",
                "EverQuestie structured detail",
                "entity_detail",
            )

    return tuple(
        sorted(
            result,
            key=lambda item: (
                normalize_name(item.expansion),
                item.source_name.casefold(),
                item.origin,
            ),
        )
    )


def entity_lifecycle_decision(
    db: Database,
    entity_id: int,
    profile_id: str,
) -> EntityLifecycleDecision:
    """Classify only direct entity lifecycle evidence for one gameplay profile.

    Live does not currently use expansion alone as a retirement statement: knowing that
    content originated in Classic does not prove it still exists on Live. Unrestricted
    accepts everything. P99 can use an explicit expansion field because the profile has
    a positive Classic-through-Velious era boundary.
    """
    entity = db.entity(int(entity_id))
    kind = str(entity["kind"] or "") if entity is not None else ""
    name = str(entity["name"] or "") if entity is not None else f"entity {entity_id}"
    profile = str(profile_id or "live").strip().casefold()
    evidence = entity_expansion_evidence(db, int(entity_id))

    if profile == "unrestricted":
        return EntityLifecycleDecision(
            int(entity_id), kind, name, profile, True, "available", "unrestricted/custom profile retains all compiled knowledge", evidence
        )

    if profile != "p99" or not evidence:
        return EntityLifecycleDecision(
            int(entity_id),
            kind,
            name,
            profile,
            None,
            "unknown",
            (
                "expansion evidence alone is not a Live retirement statement"
                if profile == "live" and evidence
                else "no explicit entity expansion evidence is currently compiled"
            ),
            evidence,
        )

    classified = [p99_expansion_allowed(item.expansion) for item in evidence]
    known = [value for value in classified if value is not None]
    if not known:
        return EntityLifecycleDecision(
            int(entity_id), kind, name, profile, None, "unknown", "entity expansion evidence is present but not classifiable", evidence
        )
    if any(value is True for value in known) and any(value is False for value in known):
        return EntityLifecycleDecision(
            int(entity_id),
            kind,
            name,
            profile,
            None,
            "conflict",
            "direct source expansion statements disagree across the P99 Velious boundary",
            evidence,
        )
    if all(value is True for value in known):
        return EntityLifecycleDecision(
            int(entity_id),
            kind,
            name,
            profile,
            True,
            "available",
            "direct entity expansion evidence places this content at or before Velious",
            evidence,
        )
    return EntityLifecycleDecision(
        int(entity_id),
        kind,
        name,
        profile,
        False,
        "post_velious",
        "direct entity expansion evidence places this content after Velious",
        evidence,
    )
