from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from .entity_lifecycle import entity_expansion_evidence, entity_lifecycle_decision


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


class _EntityReadAdapter:
    """Minimal adapter so lifecycle projection can run on sqlite mode=ro handles."""

    def __init__(self, conn):
        self.conn = conn

    def entity(self, entity_id: int):
        return self.conn.execute("SELECT * FROM entities WHERE id=?", (int(entity_id),)).fetchone()


def profile_lifecycle_audit(db) -> LifecycleAuditSummary:
    adapter = db if hasattr(db, "entity") else _EntityReadAdapter(db.conn)
    entities = db.conn.execute(
        "SELECT id,kind FROM entities ORDER BY id"
    ).fetchall()

    kind_entities: Counter[str] = Counter()
    kind_with: Counter[str] = Counter()
    kind_evidence: Counter[str] = Counter()
    kind_available: Counter[str] = Counter()
    kind_blocked: Counter[str] = Counter()
    kind_conflict: Counter[str] = Counter()
    source_kinds: Counter[str] = Counter()
    expansions: Counter[str] = Counter()

    with_evidence = 0
    evidence_rows = 0
    available = 0
    blocked = 0
    conflict = 0

    for row in entities:
        entity_id = int(row["id"])
        kind = str(row["kind"] or "unknown")
        kind_entities[kind] += 1
        evidence = entity_expansion_evidence(adapter, entity_id)
        if not evidence:
            continue

        with_evidence += 1
        kind_with[kind] += 1
        evidence_rows += len(evidence)
        kind_evidence[kind] += len(evidence)
        for item in evidence:
            source_kinds[item.source_kind or "unknown"] += 1
            expansions[item.expansion] += 1

        decision = entity_lifecycle_decision(adapter, entity_id, "p99")
        if decision.status == "conflict":
            conflict += 1
            kind_conflict[kind] += 1
        elif decision.compatibility is True:
            available += 1
            kind_available[kind] += 1
        elif decision.compatibility is False:
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
        total_entities=len(entities),
        entities_with_expansion_evidence=with_evidence,
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
