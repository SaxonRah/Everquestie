from __future__ import annotations

from datetime import datetime

from .db import Database


def rebuild_compact_search_index(db: Database) -> int:
    """Rebuild FTS without duplicating full structured detail JSON.

    Rich MCP records belong in ``entity_details.detail_json``. Search uses the bounded
    ``detail_text`` projection produced by the importer. Legacy detail rows that have
    no text projection still fall back to their JSON so older knowledge is not made
    unsearchable during migration.
    """
    if not db.fts_available:
        return 0

    inserted = 0
    with db.batch():
        db.conn.execute("DELETE FROM entity_fts")
        cursor = db.conn.execute(
            """
            SELECT e.id, e.kind, e.name, e.notes, e.data_json,
                   COALESCE((
                       SELECT group_concat(a.alias, ' ')
                       FROM entity_aliases a WHERE a.entity_id=e.id
                   ), '') AS aliases,
                   CASE
                       WHEN trim(COALESCE(d.detail_text, ''))<>'' THEN d.detail_text
                       ELSE COALESCE(d.detail_json, '')
                   END AS detail_search,
                   COALESCE((
                       SELECT group_concat(qs.description, ' ')
                       FROM quest_steps qs WHERE qs.quest_entity_id=e.id
                   ), '') AS quest_text
            FROM entities e
            LEFT JOIN entity_details d ON d.entity_id=e.id
            ORDER BY e.id
            """
        )
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            payload = []
            for row in rows:
                body = "\n".join(
                    part
                    for part in (
                        str(row["notes"] or ""),
                        str(row["detail_search"] or ""),
                        str(row["quest_text"] or ""),
                        str(row["data_json"] or ""),
                    )
                    if part
                )
                payload.append(
                    (int(row["id"]), row["kind"], row["name"], row["aliases"], body)
                )
            db.conn.executemany(
                "INSERT INTO entity_fts(entity_id, kind, name, aliases, body) VALUES(?,?,?,?,?)",
                payload,
            )
            inserted += len(payload)
        db.set_meta("fts_last_rebuild", datetime.now().isoformat(timespec="seconds"))
        db.set_meta("fts_dirty", "0")
    return inserted
