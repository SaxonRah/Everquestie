from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Protocol


class DatabaseLike(Protocol):
    conn: sqlite3.Connection


@dataclass(frozen=True, slots=True)
class ProviderNormalizationCoverage:
    source_name: str
    source_kind: str
    source_pages: int
    classified_pages: int
    normalized_pages: int
    entity_links: int
    primary_entity_links: int
    external_ids: int
    aliases: int
    relationships: int
    locations: int
    quest_steps: int
    details: int
    support_rows: int
    lifecycle_records: int = 0
    page_types: tuple[tuple[str, int], ...] = ()
    normalized_page_types: tuple[tuple[str, int], ...] = ()
    entity_kinds: tuple[tuple[str, int], ...] = ()
    relation_types: tuple[tuple[str, int], ...] = ()

    @property
    def unclassified_pages(self) -> int:
        return max(0, self.source_pages - self.classified_pages)

    @property
    def unnormalized_pages(self) -> int:
        return max(0, self.source_pages - self.normalized_pages)

    @property
    def normalized_fraction(self) -> float:
        if not self.source_pages:
            return 0.0
        return self.normalized_pages / self.source_pages

    def as_dict(self) -> dict[str, object]:
        return {
            "source_name": self.source_name,
            "source_kind": self.source_kind,
            "source_pages": self.source_pages,
            "classified_pages": self.classified_pages,
            "unclassified_pages": self.unclassified_pages,
            "normalized_pages": self.normalized_pages,
            "unnormalized_pages": self.unnormalized_pages,
            "normalized_fraction": self.normalized_fraction,
            "entity_links": self.entity_links,
            "primary_entity_links": self.primary_entity_links,
            "external_ids": self.external_ids,
            "aliases": self.aliases,
            "relationships": self.relationships,
            "locations": self.locations,
            "quest_steps": self.quest_steps,
            "details": self.details,
            "support_rows": self.support_rows,
            "lifecycle_records": self.lifecycle_records,
            "page_types": dict(self.page_types),
            "normalized_page_types": dict(self.normalized_page_types),
            "entity_kinds": dict(self.entity_kinds),
            "relation_types": dict(self.relation_types),
        }


@dataclass(frozen=True, slots=True)
class KnowledgeNormalizationCoverage:
    providers: tuple[ProviderNormalizationCoverage, ...]

    @property
    def source_pages(self) -> int:
        return sum(provider.source_pages for provider in self.providers)

    @property
    def normalized_pages(self) -> int:
        return sum(provider.normalized_pages for provider in self.providers)

    @property
    def relationships(self) -> int:
        return sum(provider.relationships for provider in self.providers)

    def provider(
        self, source_name: str, source_kind: str
    ) -> ProviderNormalizationCoverage | None:
        name = str(source_name or "").casefold()
        kind = str(source_kind or "").casefold()
        return next(
            (
                provider
                for provider in self.providers
                if provider.source_name.casefold() == name
                and provider.source_kind.casefold() == kind
            ),
            None,
        )


# A source page is considered normalized when at least one persistent canonical or
# support-table derivative points back to it. This is deliberately source-agnostic:
# identity inventories can normalize with no graph edges, while quest/NPC/item pages
# may also produce relationships, locations, task steps, aliases and rich details.
_BASE_DERIVATIVE_SOURCE_QUERIES = (
    "SELECT source_page_id AS id FROM entity_sources WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM entity_external_ids WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM entity_aliases WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM entity_relationships WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM entity_locations WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM quest_steps WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM entity_details WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM skill_caps WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM base_stats WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM ac_mitigation WHERE source_page_id IS NOT NULL",
    "SELECT source_page_id AS id FROM spell_stacking WHERE source_page_id IS NOT NULL",
)


def _relation_exists(db: DatabaseLike, name: str) -> bool:
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


def _derivative_source_queries(db: DatabaseLike) -> tuple[str, ...]:
    queries = list(_BASE_DERIVATIVE_SOURCE_QUERIES)
    # Source-granular lifecycle evidence is a real normalized derivative even before
    # exact canonical attachment. Allakhazam spell facts intentionally support this
    # state while client identity is unavailable or the name corroboration fails.
    if _relation_exists(db, "entity_lifecycle_records"):
        queries.append(
            "SELECT source_page_id AS id FROM entity_lifecycle_records "
            "WHERE source_page_id IS NOT NULL"
        )
    return tuple(queries)


def _count_for_provider(
    db: DatabaseLike,
    table: str,
    source_name: str,
    source_kind: str,
    *,
    expression: str = "COUNT(*)",
    extra_where: str = "",
) -> int:
    where = f" AND ({extra_where})" if extra_where else ""
    row = db.conn.execute(
        f"""
        SELECT {expression} AS n
        FROM {table} record
        JOIN source_pages sp ON sp.id=record.source_page_id
        WHERE sp.source_name=? AND sp.source_kind=?{where}
        """,
        (source_name, source_kind),
    ).fetchone()
    return int(row["n"] or 0)


def _breakdown(
    db: DatabaseLike,
    sql: str,
    source_name: str,
    source_kind: str,
) -> tuple[tuple[str, int], ...]:
    rows = db.conn.execute(sql, (source_name, source_kind)).fetchall()
    return tuple(
        (str(row["label"] or "(unclassified)"), int(row["n"] or 0))
        for row in rows
    )


def _normalized_page_count(
    db: DatabaseLike, source_name: str, source_kind: str
) -> int:
    union_sql = "\nUNION\n".join(_derivative_source_queries(db))
    row = db.conn.execute(
        f"""
        WITH derivative_pages AS (
            {union_sql}
        )
        SELECT COUNT(*) AS n
        FROM derivative_pages d
        JOIN source_pages sp ON sp.id=d.id
        WHERE sp.source_name=? AND sp.source_kind=?
        """,
        (source_name, source_kind),
    ).fetchone()
    return int(row["n"] or 0)


def _normalized_page_types(
    db: DatabaseLike, source_name: str, source_kind: str
) -> tuple[tuple[str, int], ...]:
    union_sql = "\nUNION\n".join(_derivative_source_queries(db))
    return _breakdown(
        db,
        f"""
        WITH derivative_pages AS (
            {union_sql}
        )
        SELECT COALESCE(NULLIF(trim(sp.entity_type),''),'(unclassified)') AS label,
               COUNT(*) AS n
        FROM derivative_pages d
        JOIN source_pages sp ON sp.id=d.id
        WHERE sp.source_name=? AND sp.source_kind=?
        GROUP BY label
        ORDER BY n DESC, label
        """,
        source_name,
        source_kind,
    )


def provider_normalization_coverage(
    db: DatabaseLike,
    source_name: str,
    source_kind: str,
) -> ProviderNormalizationCoverage:
    page_row = db.conn.execute(
        """
        SELECT COUNT(*) AS source_pages,
               SUM(CASE WHEN trim(COALESCE(entity_type,''))<>'' THEN 1 ELSE 0 END)
                   AS classified_pages
        FROM source_pages
        WHERE source_name=? AND source_kind=?
        """,
        (source_name, source_kind),
    ).fetchone()
    source_pages = int(page_row["source_pages"] or 0)
    classified_pages = int(page_row["classified_pages"] or 0)

    entity_links = _count_for_provider(
        db,
        "entity_sources",
        source_name,
        source_kind,
        expression="COUNT(DISTINCT record.entity_id)",
    )
    primary_entity_links = _count_for_provider(
        db,
        "entity_sources",
        source_name,
        source_kind,
        expression="COUNT(DISTINCT record.entity_id)",
        extra_where="record.role='primary'",
    )
    external_ids = _count_for_provider(
        db, "entity_external_ids", source_name, source_kind
    )
    aliases = _count_for_provider(db, "entity_aliases", source_name, source_kind)
    relationships = _count_for_provider(
        db, "entity_relationships", source_name, source_kind
    )
    locations = _count_for_provider(db, "entity_locations", source_name, source_kind)
    quest_steps = _count_for_provider(db, "quest_steps", source_name, source_kind)
    details = _count_for_provider(db, "entity_details", source_name, source_kind)
    support_rows = sum(
        _count_for_provider(db, table, source_name, source_kind)
        for table in ("skill_caps", "base_stats", "ac_mitigation", "spell_stacking")
    )
    lifecycle_records = (
        _count_for_provider(
            db, "entity_lifecycle_records", source_name, source_kind
        )
        if _relation_exists(db, "entity_lifecycle_records")
        else 0
    )

    page_types = _breakdown(
        db,
        """
        SELECT COALESCE(NULLIF(trim(sp.entity_type),''),'(unclassified)') AS label,
               COUNT(*) AS n
        FROM source_pages sp
        WHERE sp.source_name=? AND sp.source_kind=?
        GROUP BY label
        ORDER BY n DESC, label
        """,
        source_name,
        source_kind,
    )
    entity_kinds = _breakdown(
        db,
        """
        SELECT e.kind AS label, COUNT(DISTINCT es.entity_id) AS n
        FROM entity_sources es
        JOIN source_pages sp ON sp.id=es.source_page_id
        JOIN entities e ON e.id=es.entity_id
        WHERE sp.source_name=? AND sp.source_kind=?
        GROUP BY e.kind
        ORDER BY n DESC, e.kind
        """,
        source_name,
        source_kind,
    )
    relation_types = _breakdown(
        db,
        """
        SELECT r.relation AS label, COUNT(*) AS n
        FROM entity_relationships r
        JOIN source_pages sp ON sp.id=r.source_page_id
        WHERE sp.source_name=? AND sp.source_kind=?
        GROUP BY r.relation
        ORDER BY n DESC, r.relation
        """,
        source_name,
        source_kind,
    )

    return ProviderNormalizationCoverage(
        source_name=source_name,
        source_kind=source_kind,
        source_pages=source_pages,
        classified_pages=classified_pages,
        normalized_pages=_normalized_page_count(db, source_name, source_kind),
        entity_links=entity_links,
        primary_entity_links=primary_entity_links,
        external_ids=external_ids,
        aliases=aliases,
        relationships=relationships,
        locations=locations,
        quest_steps=quest_steps,
        details=details,
        support_rows=support_rows,
        lifecycle_records=lifecycle_records,
        page_types=page_types,
        normalized_page_types=_normalized_page_types(db, source_name, source_kind),
        entity_kinds=entity_kinds,
        relation_types=relation_types,
    )


def knowledge_normalization_coverage(
    db: DatabaseLike,
) -> KnowledgeNormalizationCoverage:
    rows = db.conn.execute(
        """
        SELECT source_name, source_kind, COUNT(*) AS n
        FROM source_pages
        GROUP BY source_name, source_kind
        ORDER BY n DESC, source_name, source_kind
        """
    ).fetchall()
    providers = tuple(
        provider_normalization_coverage(
            db,
            str(row["source_name"] or ""),
            str(row["source_kind"] or ""),
        )
        for row in rows
    )
    return KnowledgeNormalizationCoverage(providers=providers)


def normalization_coverage_text(
    db: DatabaseLike,
    *,
    breakdown_limit: int = 8,
) -> str:
    report = knowledge_normalization_coverage(db)
    lines = [
        "EverQuestie source normalization coverage",
        "",
        "Read-only DB projection. This does not scan mirror folders or modify knowledge.",
    ]
    if not report.providers:
        lines += ["", "No source pages are present yet."]
        return "\n".join(lines)

    for provider in report.providers:
        pct = 100.0 * provider.normalized_fraction
        lines += [
            "",
            f"{provider.source_name} [{provider.source_kind}]",
            f"  source pages: {provider.source_pages:,}",
            f"  classified pages: {provider.classified_pages:,}",
            f"  pages with normalized DB derivatives: {provider.normalized_pages:,} ({pct:.1f}%)",
            f"  canonical entity links: {provider.entity_links:,} ({provider.primary_entity_links:,} primary)",
            f"  external IDs / aliases: {provider.external_ids:,} / {provider.aliases:,}",
            f"  relationships / locations / quest steps: {provider.relationships:,} / {provider.locations:,} / {provider.quest_steps:,}",
            f"  rich details / support rows / lifecycle records: {provider.details:,} / {provider.support_rows:,} / {provider.lifecycle_records:,}",
        ]
        if provider.page_types:
            lines.append(
                "  page types: "
                + ", ".join(
                    f"{label}={count:,}"
                    for label, count in provider.page_types[: max(0, breakdown_limit)]
                )
            )
        if provider.normalized_page_types:
            lines.append(
                "  normalized page types: "
                + ", ".join(
                    f"{label}={count:,}"
                    for label, count in provider.normalized_page_types[: max(0, breakdown_limit)]
                )
            )
        if provider.entity_kinds:
            lines.append(
                "  canonical entity kinds: "
                + ", ".join(
                    f"{label}={count:,}"
                    for label, count in provider.entity_kinds[: max(0, breakdown_limit)]
                )
            )
        if provider.relation_types:
            lines.append(
                "  relationship types: "
                + ", ".join(
                    f"{label}={count:,}"
                    for label, count in provider.relation_types[: max(0, breakdown_limit)]
                )
            )

    lines += [
        "",
        "Interpretation:",
        "  • Source pages count only records already persisted in EverQuestie's DB; an unfinished mirror may contain many more files on disk.",
        "  • A normalized page has at least one canonical identity/graph/support/lifecycle derivative tied back to its source_page_id.",
        "  • Source-granular lifecycle evidence counts as normalized even when conservative identity reconciliation intentionally leaves it unattached.",
        "  • Low relationship counts are not automatically a parser defect: identity inventories and support-table sources can normalize correctly without producing graph edges.",
    ]
    return "\n".join(lines)
