from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .locations import LocationEvidence, location_evidence_for_entity
from .zone_authority import resolve_authoritative_zone


@dataclass(frozen=True, slots=True)
class KnowledgeMapTarget:
    entity_id: int
    entity_name: str
    zone_entity_id: int
    zone_name: str
    x: float
    y: float
    z: float | None
    label: str
    evidence_count: int
    source_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeMapTargetResult:
    status: str
    reason: str
    target: KnowledgeMapTarget | None = None
    current_zone_entity_id: int | None = None
    current_zone_name: str = ""
    current_zone_candidate_count: int = 0
    other_zone_candidate_count: int = 0

    @property
    def ready(self) -> bool:
        return self.status == "ready" and self.target is not None


def _coordinate_key(row: LocationEvidence) -> tuple[int, float, float, float | None]:
    assert row.zone_entity_id is not None
    assert row.x is not None and row.y is not None
    return (
        int(row.zone_entity_id),
        float(row.x),
        float(row.y),
        (float(row.z) if row.z is not None else None),
    )


def select_knowledge_map_target(
    db: Database,
    entity_id: int,
    current_zone: str | None,
) -> KnowledgeMapTargetResult:
    """Choose one unambiguous, current-zone map target for a selected entity.

    This is a read-only selection layer. It never loads a local map and never knows
    map-pack paths/variants. Provider coordinates are eligible only when the shared
    ``LocationEvidence`` projection has already assigned a safe canonical gameplay
    ``zone_entity_id``.
    """
    entity = db.entity(int(entity_id))
    if entity is None:
        return KnowledgeMapTargetResult("missing_entity", "Selected knowledge entity no longer exists.")

    zone_text = " ".join(str(current_zone or "").split()).strip()
    if not zone_text:
        return KnowledgeMapTargetResult(
            "no_current_zone",
            "Current zone is not known from the log yet.",
        )

    resolution = resolve_authoritative_zone(db, zone_text)
    if resolution.identity is None:
        if resolution.status == "ambiguous":
            return KnowledgeMapTargetResult(
                "current_zone_ambiguous",
                f"Current canonical zone identity is ambiguous for {zone_text}; EverQuestie will not guess a map target.",
            )
        return KnowledgeMapTargetResult(
            "current_zone_unresolved",
            f"Current canonical zone identity is not known for {zone_text}.",
        )

    current_zone_id = int(resolution.identity.entity_id)
    current_zone_name = str(resolution.identity.name or zone_text)
    rows = location_evidence_for_entity(db, int(entity_id))
    navigable = [row for row in rows if row.navigable]
    current = [row for row in navigable if int(row.zone_entity_id) == current_zone_id]
    elsewhere = [row for row in navigable if int(row.zone_entity_id) != current_zone_id]

    if not current:
        if elsewhere:
            return KnowledgeMapTargetResult(
                "not_in_current_zone",
                f"{entity['name']} has safe mapped location evidence, but none is in the current zone {current_zone_name}.",
                current_zone_entity_id=current_zone_id,
                current_zone_name=current_zone_name,
                other_zone_candidate_count=len({_coordinate_key(row) for row in elsewhere}),
            )
        if rows:
            return KnowledgeMapTargetResult(
                "no_navigable_location",
                f"Location evidence exists for {entity['name']}, but none has both a safe gameplay-zone identity and explicit X/Y coordinates.",
                current_zone_entity_id=current_zone_id,
                current_zone_name=current_zone_name,
            )
        return KnowledgeMapTargetResult(
            "no_location",
            f"No confirmed location evidence is known for {entity['name']}.",
            current_zone_entity_id=current_zone_id,
            current_zone_name=current_zone_name,
        )

    grouped: dict[tuple[int, float, float, float | None], list[LocationEvidence]] = {}
    for row in current:
        grouped.setdefault(_coordinate_key(row), []).append(row)

    if len(grouped) > 1:
        return KnowledgeMapTargetResult(
            "multiple_current_zone_locations",
            f"{entity['name']} has {len(grouped)} distinct safe locations in {current_zone_name}; EverQuestie will not choose one automatically.",
            current_zone_entity_id=current_zone_id,
            current_zone_name=current_zone_name,
            current_zone_candidate_count=len(grouped),
            other_zone_candidate_count=len({_coordinate_key(row) for row in elsewhere}),
        )

    (_zone_id, x, y, z), evidence_rows = next(iter(grouped.items()))
    sources = tuple(
        dict.fromkeys(
            row.source_label
            for row in evidence_rows
            if row.source_label
        )
    )
    label = str(entity["name"] or "Knowledge location")
    target = KnowledgeMapTarget(
        entity_id=int(entity_id),
        entity_name=str(entity["name"] or ""),
        zone_entity_id=current_zone_id,
        zone_name=current_zone_name,
        x=float(x),
        y=float(y),
        z=(float(z) if z is not None else None),
        label=label,
        evidence_count=len(evidence_rows),
        source_labels=sources,
    )
    return KnowledgeMapTargetResult(
        "ready",
        f"One safe current-zone location is available for {target.entity_name}.",
        target=target,
        current_zone_entity_id=current_zone_id,
        current_zone_name=current_zone_name,
        current_zone_candidate_count=1,
        other_zone_candidate_count=len({_coordinate_key(row) for row in elsewhere}),
    )
