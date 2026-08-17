from __future__ import annotations

import sqlite3


def _relation_exists(db, name: str) -> bool:
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


def release_map_catalog_text(db) -> str:
    """Summarize map knowledge already shipped inside an immutable snapshot.

    RuntimeDatabase exposes immutable knowledge tables as TEMP views. Reading
    ``map_sources``/``map_labels`` directly therefore cannot be shadowed by writable
    user metadata and never needs a local Good's/Brewall rendering directory. Older
    snapshots that predate the map catalog remain quiet rather than producing noise.
    """
    if getattr(db, "knowledge_writable", True):
        return ""
    try:
        if not (_relation_exists(db, "map_sources") and _relation_exists(db, "map_labels")):
            return ""
        rows = db.conn.execute(
            """
            SELECT
                ms.source_name,
                ms.source_version,
                COUNT(DISTINCT ms.id) AS files,
                COUNT(ml.id) AS labels
            FROM map_sources ms
            LEFT JOIN map_labels ml ON ml.source_id=ms.id
            GROUP BY ms.source_name,ms.source_version
            ORDER BY ms.source_name COLLATE NOCASE,ms.source_version
            """
        ).fetchall()
    except sqlite3.Error:
        return ""

    if not rows:
        return ""

    lines = ["Release map catalog:"]
    total_labels = 0
    for row in rows:
        source_name = str(row["source_name"] or "Map source")
        source_version = str(row["source_version"] or "").strip()
        files = int(row["files"] or 0)
        labels = int(row["labels"] or 0)
        total_labels += labels
        source = source_name + (f" {source_version}" if source_version else " (unversioned)")
        lines.append(
            f"  {source}: {files} indexed map file(s), {labels} indexed label(s)"
        )
    lines.append(f"  Total indexed labels: {total_labels}")
    return "\n".join(lines)
