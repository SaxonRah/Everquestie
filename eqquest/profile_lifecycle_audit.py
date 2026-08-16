from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from typing import Any

from .db import normalize_name
from .entity_lifecycle import lifecycle_field, lifecycle_field_policy
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
    p99_undetermined: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "entities": self.entities,
            "with_expansion_evidence": self.with_expansion_evidence,
            "evidence_rows": self.evidence_rows,
            "p99_available": self.p99_available,
            "p99_blocked": self.p99_blocked,
            "p99_conflict": self.p99_conflict,
            "p99_undetermined": self.p99_undetermined,
        }


@dataclass(frozen=True, slots=True)
class LifecycleAuditSummary:
    total_entities: int
    entities_with_expansion_evidence: int
    evidence_rows: int
    rejected_lifecycle_candidates: int
    entities_with_rejected_lifecycle_candidates: int
    p99_available_direct: int
    p99_blocked_direct: int
    p99_conflict: int
    p99_undetermined_direct: int
    by_kind: tuple[LifecycleKindCoverage, ...]
    by_source_kind: tuple[tuple[str, int], ...]
    by_expansion: tuple[tuple[str, int], ...]
    by_unclassified_expansion: tuple[tuple[str, int], ...]
    by_rejected_source_kind: tuple[tuple[str, int], ...]
    by_rejected_reason: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_entities": self.total_entities,
            "entities_with_expansion_evidence": self.entities_with_expansion_evidence,
            "evidence_rows": self.evidence_rows,
            "rejected_lifecycle_candidates": self.rejected_lifecycle_candidates,
            "entities_with_rejected_lifecycle_candidates": self.entities_with_rejected_lifecycle_candidates,
            "p99_available_direct": self.p99_available_direct,
            "p99_blocked_direct": self.p99_blocked_direct,
            "p99_conflict": self.p99_conflict,
            "p99_undetermined_direct": self.p99_undetermined_direct,
            "by_kind": [row.as_dict() for row in self.by_kind],
            "by_source_kind": [
                {"source_kind": key, "evidence_rows": count}
                for key, count in self.by_source_kind
            ],
            "by_expansion": [
                {"expansion": key, "evidence_rows": count}
                for key, count in self.by_expansion
            ],
            "by_unclassified_expansion": [
                {"expansion": key, "evidence_rows": count}
                for key, count in self.by_unclassified_expansion
            ],
            "by_rejected_source_kind": [
                {"source_kind": key, "candidate_rows": count}
                for key, count in self.by_rejected_source_kind
            ],
            "by_rejected_reason": [
                {"reason": key, "candidate_rows": count}
                for key, count in self.by_rejected_reason
            ],
        }


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def profile_lifecycle_audit(db) -> LifecycleAuditSummary:
    """Measure reviewed direct lifecycle coverage with set-based knowledge reads.

    Lifecycle-looking fields are passed through the same source policy used at runtime.
    Rejected candidates are counted separately so source drift is visible without being
    promoted into gameplay-profile truth.
    """
    entity_rows = db.conn.execute(
        """
        SELECT e.id,e.kind,e.data_json,e.source_page_id,
               COALESCE(sp.source_name,'') AS source_name,
               COALESCE(sp.source_kind,'') AS source_kind
        FROM entities e
        LEFT JOIN source_pages sp ON sp.id=e.source_page_id
        ORDER BY e.id
        """
    ).fetchall()
    detail_rows = db.conn.execute(
        """
        SELECT d.entity_id,d.detail_json,d.source_page_id,
               COALESCE(sp.source_name,'') AS source_name,
               COALESCE(sp.source_kind,'') AS source_kind
        FROM entity_details d
        LEFT JOIN source_pages sp ON sp.id=d.source_page_id
        ORDER BY d.entity_id
        """
    ).fetchall()

    kind_entities: Counter[str] = Counter()
    entity_kind: dict[int, str] = {}
    # Runtime deduplication key: normalized lifecycle text, surface/origin, source page,
    # and exact top-level lifecycle field.
    evidence_by_entity: dict[
        int,
        dict[tuple[str, str, int | None, str], tuple[str, str]],
    ] = defaultdict(dict)
    rejected_by_entity: dict[
        int,
        dict[tuple[str, str, int | None, str], tuple[str, str]],
    ] = defaultdict(dict)

    def consider_candidate(
        entity_id: int,
        entity_kind_value: str,
        field_name: str,
        expansion: str,
        *,
        origin: str,
        source_page_id: int | None,
        source_name: str,
        source_kind: str,
    ) -> None:
        text = " ".join(str(expansion or "").split()).strip()
        if not text:
            return
        fallback_source_kind = source_kind or (
            "entity_data" if origin == "entity.data_json" else "entity_detail"
        )
        key = (normalize_name(text), origin, source_page_id, field_name.casefold())
        policy = lifecycle_field_policy(
            entity_kind=entity_kind_value,
            origin=origin,
            field_name=field_name,
            source_name=source_name,
            source_kind=source_kind,
            source_page_id=source_page_id,
        )
        if policy.allowed:
            evidence_by_entity[int(entity_id)][key] = (text, fallback_source_kind)
        else:
            rejected_by_entity[int(entity_id)][key] = (
                fallback_source_kind,
                policy.reason,
            )

    for row in entity_rows:
        entity_id = int(row["id"])
        kind = str(row["kind"] or "unknown")
        entity_kind[entity_id] = kind
        kind_entities[kind] += 1
        found = lifecycle_field(_json_object(row["data_json"]))
        if found is not None:
            consider_candidate(
                entity_id,
                kind,
                found[0],
                found[1],
                origin="entity.data_json",
                source_page_id=(
                    int(row["source_page_id"])
                    if row["source_page_id"] is not None
                    else None
                ),
                source_name=str(row["source_name"] or ""),
                source_kind=str(row["source_kind"] or ""),
            )

    for row in detail_rows:
        entity_id = int(row["entity_id"])
        kind = entity_kind.get(entity_id, "unknown")
        found = lifecycle_field(_json_object(row["detail_json"]))
        if found is not None:
            consider_candidate(
                entity_id,
                kind,
                found[0],
                found[1],
                origin="entity_details.detail_json",
                source_page_id=(
                    int(row["source_page_id"])
                    if row["source_page_id"] is not None
                    else None
                ),
                source_name=str(row["source_name"] or ""),
                source_kind=str(row["source_kind"] or ""),
            )

    kind_with: Counter[str] = Counter()
    kind_evidence: Counter[str] = Counter()
    kind_available: Counter[str] = Counter()
    kind_blocked: Counter[str] = Counter()
    kind_conflict: Counter[str] = Counter()
    kind_undetermined: Counter[str] = Counter()
    source_kinds: Counter[str] = Counter()
    expansions: Counter[str] = Counter()
    unclassified_expansions: Counter[str] = Counter()
    rejected_source_kinds: Counter[str] = Counter()
    rejected_reasons: Counter[str] = Counter()

    available = 0
    blocked = 0
    conflict = 0
    undetermined = 0
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
            if value is None:
                unclassified_expansions[expansion] += 1
            else:
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
        else:
            undetermined += 1
            kind_undetermined[kind] += 1

    rejected_candidates = 0
    for records in rejected_by_entity.values():
        rejected_candidates += len(records)
        for source_kind, reason in records.values():
            rejected_source_kinds[source_kind] += 1
            rejected_reasons[reason] += 1

    kinds = tuple(
        LifecycleKindCoverage(
            kind,
            kind_entities[kind],
            kind_with[kind],
            kind_evidence[kind],
            kind_available[kind],
            kind_blocked[kind],
            kind_conflict[kind],
            kind_undetermined[kind],
        )
        for kind in sorted(kind_entities)
    )

    return LifecycleAuditSummary(
        total_entities=len(entity_rows),
        entities_with_expansion_evidence=len(evidence_by_entity),
        evidence_rows=evidence_rows,
        rejected_lifecycle_candidates=rejected_candidates,
        entities_with_rejected_lifecycle_candidates=len(rejected_by_entity),
        p99_available_direct=available,
        p99_blocked_direct=blocked,
        p99_conflict=conflict,
        p99_undetermined_direct=undetermined,
        by_kind=kinds,
        by_source_kind=tuple(
            sorted(source_kinds.items(), key=lambda item: (-item[1], item[0]))
        ),
        by_expansion=tuple(
            sorted(expansions.items(), key=lambda item: (-item[1], item[0].casefold()))
        ),
        by_unclassified_expansion=tuple(
            sorted(
                unclassified_expansions.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )
        ),
        by_rejected_source_kind=tuple(
            sorted(rejected_source_kinds.items(), key=lambda item: (-item[1], item[0]))
        ),
        by_rejected_reason=tuple(
            sorted(rejected_reasons.items(), key=lambda item: (-item[1], item[0]))
        ),
    )


def profile_lifecycle_audit_text(db) -> str:
    summary = profile_lifecycle_audit(db)
    lines = [
        "EverQuestie direct entity lifecycle audit",
        f"Entities: {summary.total_entities:,}",
        f"Entities with reviewed expansion/era evidence: {summary.entities_with_expansion_evidence:,}",
        f"Reviewed direct expansion evidence rows: {summary.evidence_rows:,}",
        (
            "Rejected lifecycle-looking candidates: "
            f"{summary.rejected_lifecycle_candidates:,} across "
            f"{summary.entities_with_rejected_lifecycle_candidates:,} entities"
        ),
        (
            "P99 direct lifecycle decisions: "
            f"available={summary.p99_available_direct:,} "
            f"blocked={summary.p99_blocked_direct:,} "
            f"conflict={summary.p99_conflict:,} "
            f"undetermined={summary.p99_undetermined_direct:,}"
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
            f"p99_blocked={row.p99_blocked:,} conflict={row.p99_conflict:,} "
            f"undetermined={row.p99_undetermined:,}"
        )

    if summary.by_source_kind:
        lines.extend(["", "Accepted evidence rows by source kind:"])
        for source_kind, count in summary.by_source_kind:
            lines.append(f"  {source_kind}: {count:,}")

    if summary.by_rejected_source_kind:
        lines.extend(["", "Rejected lifecycle-looking candidates by source kind:"])
        for source_kind, count in summary.by_rejected_source_kind:
            lines.append(f"  {source_kind}: {count:,}")

    if summary.by_rejected_reason:
        lines.extend(["", "Rejected candidate policy reasons:"])
        for reason, count in summary.by_rejected_reason:
            lines.append(f"  {reason}: {count:,}")

    if summary.by_unclassified_expansion:
        lines.extend(["", "Unclassified reviewed expansion values:"])
        for expansion, count in summary.by_unclassified_expansion[:30]:
            lines.append(f"  {expansion}: {count:,}")

    if summary.by_expansion:
        lines.extend(["", "Most common reviewed expansion values:"])
        for expansion, count in summary.by_expansion[:30]:
            lines.append(f"  {expansion}: {count:,}")

    lines.extend(
        [
            "",
            "Boundary: field presence alone is not lifecycle evidence; source + field + parser semantics must be reviewed.",
            "Only explicit top-level fields accepted by the shared lifecycle source policy are counted as direct evidence.",
            "Rejected lifecycle-looking fields remain diagnostic candidates and do not affect gameplay profiles.",
            "Only reviewed expansion labels cross the P99 boundary; unrecognized accepted values remain undetermined.",
            "Locations, prose, names, dates, nested metadata, and fuzzy inference are excluded from this audit.",
        ]
    )
    return "\n".join(lines)
