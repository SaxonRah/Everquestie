from __future__ import annotations

from .db import Database


def identity_audit_text(db: Database, *, sample_limit: int = 15) -> str:
    """Read-only audit for identity/merge problems before large source imports."""
    duplicate_groups = db.conn.execute(
        """
        SELECT kind, normalized_name, COUNT(*) AS count,
               group_concat(id, ',') AS ids,
               group_concat(name, ' | ') AS names
        FROM entities
        GROUP BY kind, normalized_name
        HAVING COUNT(*) > 1
        ORDER BY count DESC, kind, normalized_name
        """
    ).fetchall()
    ambiguous_aliases = db.conn.execute(
        """
        SELECT normalized_alias, COUNT(DISTINCT entity_id) AS count,
               group_concat(DISTINCT entity_id) AS ids
        FROM entity_aliases
        GROUP BY normalized_alias
        HAVING COUNT(DISTINCT entity_id) > 1
        ORDER BY count DESC, normalized_alias
        """
    ).fetchall()
    missing_sources = int(db.conn.execute(
        """
        SELECT COUNT(*) FROM entities e
        WHERE e.source_page_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM entity_sources es WHERE es.entity_id=e.id)
        """
    ).fetchone()[0])
    self_relationships = int(db.conn.execute(
        "SELECT COUNT(*) FROM entity_relationships WHERE source_entity_id=target_entity_id"
    ).fetchone()[0])
    locations_without_zone = int(db.conn.execute(
        """
        SELECT COUNT(*)
        FROM entity_locations l
        JOIN entities e ON e.id=l.entity_id
        WHERE l.zone_entity_id IS NULL AND trim(COALESCE(e.zone,''))=''
        """
    ).fetchone()[0])
    entities_without_aliases = int(db.conn.execute(
        """
        SELECT COUNT(*) FROM entities e
        WHERE NOT EXISTS (SELECT 1 FROM entity_aliases a WHERE a.entity_id=e.id)
        """
    ).fetchone()[0])
    detail_without_source = int(db.conn.execute(
        "SELECT COUNT(*) FROM entity_details WHERE source_page_id IS NULL"
    ).fetchone()[0])

    lines = [
        "EverQuestie identity / merge audit",
        "",
        "This is read-only. It does not scan configured mirror folders or modify the database.",
        "",
        f"Duplicate kind+normalized-name groups: {len(duplicate_groups):,}",
        f"Aliases resolving to multiple entities: {len(ambiguous_aliases):,}",
        f"Entities with no provenance link: {missing_sources:,}",
        f"Self-referential relationships: {self_relationships:,}",
        f"Locations with no resolvable zone: {locations_without_zone:,}",
        f"Entities with no aliases: {entities_without_aliases:,}",
        f"Rich detail rows without source_page_id: {detail_without_source:,}",
    ]

    if duplicate_groups:
        lines += ["", "Potential duplicate identities (sample):"]
        for row in duplicate_groups[:sample_limit]:
            lines.append(
                f"  [{row['kind']}] {row['normalized_name']} — {row['count']} rows — IDs {row['ids']}"
            )
            if row["names"]:
                lines.append(f"      {row['names']}")
    if ambiguous_aliases:
        lines += ["", "Ambiguous aliases (sample):"]
        for row in ambiguous_aliases[:sample_limit]:
            lines.append(
                f"  {row['normalized_alias']} — {row['count']} entities — IDs {row['ids']}"
            )

    if not duplicate_groups and not ambiguous_aliases and not self_relationships:
        lines += ["", "No obvious identity collisions were found in the normalized graph."]
    lines += [
        "",
        "Interpretation:",
        "  • Duplicate names are not automatically errors; EverQuest can legitimately reuse names.",
        "  • Ambiguous aliases should stay ambiguous unless provenance provides a stronger identity key.",
        "  • The audit is intended to expose merge pressure before a large local-mirror import, not auto-fix it.",
    ]
    return "\n".join(lines)
