from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from typing import Any

from .db import normalize_name
from .entity_lifecycle import expansion_text
from .world_profiles import p99_expansion_allowed


@dataclass(frozen=True, slots=True)
class LifecycleKindCoverage:
    kind: str
    entities: int
    with_expansion_evidence: int
    evidence_rows: int
    p99_available: int
    p99_blocked: int
    p99_conflict: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "entities": self.entities,
            "with_expansion_evidence": self.with_expansion_evidence,
            "evidence_rows": self.evidence_rows,
            "p99_available": self.p99_available,
            "p99_blocked": self.p99_blocked,
            "p99_conflict": self.p99_conflict,
        }


@dataclass(frozen=True, slots=True)
class LifecycleAuditSummary:
    total_entities: int
    entities_with_expansion_evidence: int
    evidence_rows: int
    p99_available_direct: int
    p99_blocked_direct: int
    p99_conflict: int
    by_kind: tuple[LifecycleKindCoverage, ...]
    by_source_kind: tuple[tuple[str, int], ...]
    by_expansion: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_entities": self.total_entities,
            "entities_with_expansion_evidence": self.entities_with_expansion_evidence,
            "evidence_rows": self.evidence_rows,
            "p99_available_direct": self.p99_available_direct,
            "p99_blocked_direct": self.p99_blocked_direct,
            "p99_conflict": self.p99_conflict,
            "by_kind": [row.as_dict() for row in self.by_kind],
            "by_source_kind": [
                {"source_kind": key, "evidence_rows": count}
                for key, count in self.by_source_kind
            ],
            "by_expansion": [
                {"expansion": key, "evidence_rows": count}
                for key, count in self.by_expansion
            ],
        }


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def profile_lifecycle_audit(db) -> LifecycleAuditSummary:
    """Measure direct lifecycle coverage with two set-based knowledge reads.

    The production snapshot contains well over one hundred thousand entities. Avoid a
    query-per-entity audit: read the entity rows and canonical detail rows once, parse
    their explicit top-level lifecycle fields in Python, and aggregate from memory.
    """
    entity_rows = db.conn.execute(
        """
        SELECT e.id,e.kind,e.data_json,e.source_page_id,
               COALESCE(sp.source_kind,'') AS source_kind
        FROM entities e
        LEFT JOIN source_pages sp ON sp.id=e.source_page_id
        ORDER BY e.id
        """
    ).fetchall()
    detail_rows = db.conn.execute(
        """
        SELECT d.entity_id,d.detail_json,d.source_page_id,
               COALESCE(sp.source_kind,'') AS source_kind
        FROM entity_details d
        LEFT JOIN source_pages sp ON sp.id=d.source_page_id
        ORDER BY d.entity_id
        """
    ).fetchall()

    kind_entities: Counter[str] = Counter()
    entity_kind: dict[int, str] = {}
    # Deduplicate exactly like entity_expansion_evidence(): same normalized expansion,
    # same normalized surface/origin, same source page = one direct evidence row.
    evidence_by_entity: dict[int, dict[tuple[str, str, int | None], tuple[str, str]]] = defaultdict(dict)

    def add_evidence(
        entity_id: int,
        expansion: str,
        *,
        origin: str,
        source_page_id: int | None,
        source_kind: str,
    ) -> None:
        text = " ".join(str(expansion or "").split()).strip()
        if not text:
            return
        key = (normalize_name(text), origin, source_page_id)
        evidence_by_entity[int(entity_id)][key] = (
            text,
            source_kind or ("entity_data" if origin == "entity.data_json" else "entity_detail"),
        )

    for row in entity_rows:
        entity_id = int(row["id"])
        kind = str(row["kind"] or "unknown")
        entity_kind[entity_id] = kind
        kind_entities[kind] += 1
        value = expansion_text(_json_object(row["data_json"]))
        if value:
            add_evidence(
                entity_id,
                value,
                origin="entity.data_json",
                source_page_id=(int(row["source_page_id"]) if row["source_page_id"] is not None else None),
                source_kind=str(row["source_kind"] or ""),
            )

    for row in detail_rows:
        entity_id = int(row["entity_id"])
        value = expansion_text(_json_object(row["detail_json"]))
        if value:
            add_evidence(
                entity_id,
                value,
                origin="entity_details.detail_json",
                source_page_id=(int(row["source_page_id"]) if row["source_page_id"] is not None else None),
                source_kind=str(row["source_kind"] or ""),
            )

    kind_with: Counter[str] = Counter()
    kind_evidence: Counter[str] = Counter()
    kind_available: Counter[str] = Counter()
    kind_blocked: Counter[str] = Counter()
    kind_conflict: Counter[str] = Counter()
    source_kinds: Counter[str] = Counter()
    expansions: Counter[str] = Counter()

    available = 0
    blocked = 0
    conflict = 0
    evidence_rows = 0

    for entity_id, records in evidence_by_entity.items():
        kind = entity_kind.get(entity_id, "unknown")
        values = list(records.values())
        kind_with[kind] += 1
        kind_evidence[kind] += len(values)
        evidence_rows += len(values)

        classified: list[bool] = []
        for expansion, source_kind in values:
            source_kinds[source_kind] += 1
            expansions[expansion] += 1
            value = p99_expansion_allowed(expansion)
            if value is not None:
                classified.append(bool(value))

        if any(classified) and any(not value for value in classified):
            conflict += 1
            kind_conflict[kind] += 1
        elif classified and all(classified):
            available += 1
            kind_available[kind] += 1
        elif classified and all(not value for value in classified):
            blocked += 1
            kind_blocked[kind] += 1

    kinds = tuple(
        LifecycleKindCoverage(
            kind,
            kind_entities[kind],
            kind_with[kind],
            kind_evidence[kind],
            kind_available[kind],
            kind_blocked[kind],
            kind_conflict[kind],
        )
        for kind in sorted(kind_entities)
    )

    return LifecycleAuditSummary(
        total_entities=len(entity_rows),
        entities_with_expansion_evidence=len(evidence_by_entity),
        evidence_rows=evidence_rows,
        p99_available_direct=available,
        p99_blocked_direct=blocked,
        p99_conflict=conflict,
        by_kind=kinds,
        by_source_kind=tuple(sorted(source_kinds.items(), key=lambda item: (-item[1], item[0]))),
        by_expansion=tuple(sorted(expansions.items(), key=lambda item: (-item[1], item[0].casefold()))),
    )


def profile_lifecycle_audit_text(db) -> str:
    summary = profile_lifecycle_audit(db)
    lines = [
        "EverQuestie direct entity lifecycle audit",
        f"Entities: {summary.total_entities:,}",
        f"Entities with explicit expansion/era evidence: {summary.entities_with_expansion_evidence:,}",
        f"Direct expansion evidence rows: {summary.evidence_rows:,}",
        (
            "P99 direct lifecycle decisions: "
            f"available={summary.p99_available_direct:,} "
            f"blocked={summary.p99_blocked_direct:,} "
            f"conflict={summary.p99_conflict:,}"
        ),
        "",
        "Coverage by entity kind:",
    ]
    for row in summary.by_kind:
        if row.with_expansion_evidence <= 0:
            continue
        lines.append(
            f"  {row.kind}: entities={row.entities:,} with_evidence={row.with_expansion_evidence:,} "
            f"evidence_rows={row.evidence_rows:,} p99_available={row.p99_available:,} "
            f"p99_blocked={row.p99_blocked:,} conflict={row.p99_conflict:,}"
        )

    if summary.by_source_kind:
        lines.extend(["", "Evidence rows by source kind:"])
        for source_kind, count in summary.by_source_kind:
            lines.append(f"  {source_kind}: {count:,}")

    if summary.by_expansion:
        lines.extend(["", "Most common explicit expansion values:"])
        for expansion, count in summary.by_expansion[:30]:
            lines.append(f"  {expansion}: {count:,}")

    lines.extend(
        [
            "",
            "Boundary: only explicit top-level expansion/expansion_name/era fields are counted.",
            "Locations, prose, names, dates, and fuzzy inference are excluded from this audit.",
        ]
    )
    return "\n".join(lines)
