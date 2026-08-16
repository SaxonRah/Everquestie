from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from typing import Any

from .db import normalize_name
from .entity_lifecycle import lifecycle_field, lifecycle_field_policy
from .entity_lifecycle_records import lifecycle_record_table_exists
from .world_profiles import profile_expansion_allowed, world_profile


@dataclass(frozen=True, slots=True)
class LifecycleKindCoverage:
    kind: str
    entities: int
    with_expansion_evidence: int
    evidence_rows: int
    profile_available: int
    profile_blocked: int
    profile_conflict: int
    profile_undetermined: int

    @property
    def p99_available(self) -> int:
        return self.profile_available

    @property
    def p99_blocked(self) -> int:
        return self.profile_blocked

    @property
    def p99_conflict(self) -> int:
        return self.profile_conflict

    @property
    def p99_undetermined(self) -> int:
        return self.profile_undetermined

    def as_dict(self, *, include_p99_aliases: bool = False) -> dict[str, Any]:
        result = {
            "kind": self.kind,
            "entities": self.entities,
            "with_expansion_evidence": self.with_expansion_evidence,
            "evidence_rows": self.evidence_rows,
            "profile_available": self.profile_available,
            "profile_blocked": self.profile_blocked,
            "profile_conflict": self.profile_conflict,
            "profile_undetermined": self.profile_undetermined,
        }
        if include_p99_aliases:
            result.update(
                {
                    "p99_available": self.profile_available,
                    "p99_blocked": self.profile_blocked,
                    "p99_conflict": self.profile_conflict,
                    "p99_undetermined": self.profile_undetermined,
                }
            )
        return result


@dataclass(frozen=True, slots=True)
class LifecycleAuditSummary:
    profile_id: str
    profile_label: str
    expansion_cap: str
    expansion_cap_label: str
    total_entities: int
    entities_with_expansion_evidence: int
    evidence_rows: int
    rejected_lifecycle_candidates: int
    entities_with_rejected_lifecycle_candidates: int
    available_direct: int
    blocked_direct: int
    conflict: int
    undetermined_direct: int
    by_kind: tuple[LifecycleKindCoverage, ...]
    by_source_kind: tuple[tuple[str, int], ...]
    by_expansion: tuple[tuple[str, int], ...]
    by_unclassified_expansion: tuple[tuple[str, int], ...]
    by_rejected_source_kind: tuple[tuple[str, int], ...]
    by_rejected_reason: tuple[tuple[str, int], ...]

    @property
    def p99_available_direct(self) -> int:
        return self.available_direct

    @property
    def p99_blocked_direct(self) -> int:
        return self.blocked_direct

    @property
    def p99_conflict(self) -> int:
        return self.conflict

    @property
    def p99_undetermined_direct(self) -> int:
        return self.undetermined_direct

    def as_dict(self) -> dict[str, Any]:
        include_p99_aliases = self.profile_id == "p99"
        result: dict[str, Any] = {
            "profile_id": self.profile_id,
            "profile_label": self.profile_label,
            "expansion_cap": self.expansion_cap,
            "expansion_cap_label": self.expansion_cap_label,
            "total_entities": self.total_entities,
            "entities_with_expansion_evidence": self.entities_with_expansion_evidence,
            "evidence_rows": self.evidence_rows,
            "rejected_lifecycle_candidates": self.rejected_lifecycle_candidates,
            "entities_with_rejected_lifecycle_candidates": self.entities_with_rejected_lifecycle_candidates,
            "available_direct": self.available_direct,
            "blocked_direct": self.blocked_direct,
            "conflict": self.conflict,
            "undetermined_direct": self.undetermined_direct,
            "by_kind": [
                row.as_dict(include_p99_aliases=include_p99_aliases)
                for row in self.by_kind
            ],
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
        if include_p99_aliases:
            result.update(
                {
                    "p99_available_direct": self.available_direct,
                    "p99_blocked_direct": self.blocked_direct,
                    "p99_conflict": self.conflict,
                    "p99_undetermined_direct": self.undetermined_direct,
                }
            )
        return result


def _json_object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _audit_profile(profile_id: str):
    profile = world_profile(profile_id)
    if profile.profile_id != str(profile_id or "").strip().casefold():
        raise ValueError(f"unknown gameplay profile: {profile_id}")
    if profile.availability_mode != "expansion_cap" or not profile.expansion_cap:
        raise ValueError(
            f"gameplay profile '{profile.profile_id}' is not an expansion-capped profile"
        )
    return profile


def profile_lifecycle_audit(db, profile_id: str = "p99") -> LifecycleAuditSummary:
    """Measure reviewed direct lifecycle coverage for one expansion-capped profile.

    Lifecycle-looking fields are passed through the same source policy used at runtime.
    Source-granular records are also resolved read-only using exact canonical identity,
    so provider order does not change audit results. Rejected candidates remain visible
    without being promoted into gameplay-profile truth.
    """
    profile = _audit_profile(profile_id)
    cap_label = profile.expansion_cap_label or profile.expansion_cap or "expansion cap"

    entity_rows = db.conn.execute(
        """
        SELECT e.id,e.kind,e.name,e.data_json,e.source_page_id,
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
    entity_name: dict[int, str] = {}
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
            "entity_data"
            if origin == "entity.data_json"
            else ("entity_lifecycle_record" if origin == "entity_lifecycle_records" else "entity_detail")
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
        entity_name[entity_id] = str(row["name"] or "")
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

    if lifecycle_record_table_exists(db):
        spell_identity_rows = db.conn.execute(
            """
            SELECT x.external_id,e.id,e.name
            FROM entity_external_ids x
            JOIN entities e ON e.id=x.entity_id
            WHERE x.namespace='eqclient:spell' AND e.kind='spell'
            """
        ).fetchall()
        spell_by_external_id = {
            str(row["external_id"] or ""): (int(row["id"]), str(row["name"] or ""))
            for row in spell_identity_rows
        }
        lifecycle_rows = db.conn.execute(
            """
            SELECT r.source_page_id,r.entity_id,r.entity_kind,r.source_external_id,
                   r.source_entity_name,r.field_name,r.field_value,
                   COALESCE(sp.source_name,'') AS source_name,
                   COALESCE(sp.source_kind,'') AS source_kind
            FROM entity_lifecycle_records r
            JOIN source_pages sp ON sp.id=r.source_page_id
            ORDER BY r.source_page_id,r.entity_kind,r.source_external_id,r.field_name
            """
        ).fetchall()
        for row in lifecycle_rows:
            resolved_entity_id = (
                int(row["entity_id"]) if row["entity_id"] is not None else None
            )
            kind = str(row["entity_kind"] or "unknown")
            if resolved_entity_id is None and kind == "spell":
                source_external_id = str(row["source_external_id"] or "")
                numeric_id = (
                    source_external_id.split(":", 1)[1]
                    if source_external_id.casefold().startswith("spell:")
                    else source_external_id
                ).strip()
                canonical = spell_by_external_id.get(numeric_id)
                if canonical is None:
                    continue
                canonical_id, canonical_name = canonical
                if normalize_name(str(row["source_entity_name"] or "")) != normalize_name(canonical_name):
                    continue
                resolved_entity_id = canonical_id
            if resolved_entity_id is None or resolved_entity_id not in entity_kind:
                continue
            consider_candidate(
                resolved_entity_id,
                entity_kind.get(resolved_entity_id, kind),
                str(row["field_name"] or ""),
                str(row["field_value"] or ""),
                origin="entity_lifecycle_records",
                source_page_id=int(row["source_page_id"]),
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
            value = profile_expansion_allowed(profile.profile_id, expansion)
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
        profile_id=profile.profile_id,
        profile_label=profile.label,
        expansion_cap=str(profile.expansion_cap),
        expansion_cap_label=cap_label,
        total_entities=len(entity_rows),
        entities_with_expansion_evidence=len(evidence_by_entity),
        evidence_rows=evidence_rows,
        rejected_lifecycle_candidates=rejected_candidates,
        entities_with_rejected_lifecycle_candidates=len(rejected_by_entity),
        available_direct=available,
        blocked_direct=blocked,
        conflict=conflict,
        undetermined_direct=undetermined,
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


def profile_lifecycle_audit_text(db, profile_id: str = "p99") -> str:
    summary = profile_lifecycle_audit(db, profile_id)
    decision_label = "P99" if summary.profile_id == "p99" else summary.profile_label
    lines = [
        "EverQuestie direct entity lifecycle audit",
        f"Gameplay profile: {summary.profile_label} [{summary.profile_id}]",
        f"Expansion cap: {summary.expansion_cap_label}",
        f"Entities: {summary.total_entities:,}",
        f"Entities with reviewed expansion/era evidence: {summary.entities_with_expansion_evidence:,}",
        f"Reviewed direct expansion evidence rows: {summary.evidence_rows:,}",
        (
            "Rejected lifecycle-looking candidates: "
            f"{summary.rejected_lifecycle_candidates:,} across "
            f"{summary.entities_with_rejected_lifecycle_candidates:,} entities"
        ),
        (
            f"{decision_label} direct lifecycle decisions: "
            f"available={summary.available_direct:,} "
            f"blocked={summary.blocked_direct:,} "
            f"conflict={summary.conflict:,} "
            f"undetermined={summary.undetermined_direct:,}"
        ),
        "",
        "Coverage by entity kind:",
    ]
    for row in summary.by_kind:
        if row.with_expansion_evidence <= 0:
            continue
        if summary.profile_id == "p99":
            decision_counts = (
                f"p99_available={row.profile_available:,} "
                f"p99_blocked={row.profile_blocked:,} conflict={row.profile_conflict:,} "
                f"undetermined={row.profile_undetermined:,}"
            )
        else:
            decision_counts = (
                f"profile_available={row.profile_available:,} "
                f"profile_blocked={row.profile_blocked:,} conflict={row.profile_conflict:,} "
                f"undetermined={row.profile_undetermined:,}"
            )
        lines.append(
            f"  {row.kind}: entities={row.entities:,} with_evidence={row.with_expansion_evidence:,} "
            f"evidence_rows={row.evidence_rows:,} {decision_counts}"
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
            "Reviewed source-granular lifecycle records are counted only after exact canonical identity resolution.",
            "Rejected lifecycle-looking fields remain diagnostic candidates and do not affect gameplay profiles.",
            (
                f"Only reviewed expansion labels cross the {summary.expansion_cap_label} boundary for "
                f"{summary.profile_label}; unrecognized accepted values remain undetermined."
            ),
            "Locations, prose, names, dates, nested metadata, and fuzzy inference are excluded from this audit.",
        ]
    )
    return "\n".join(lines)
