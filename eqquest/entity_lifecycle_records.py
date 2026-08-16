from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_TABLE = "entity_lifecycle_records"


@dataclass(frozen=True, slots=True)
class EntityLifecycleRecord:
    entity_id: int
    source_page_id: int
    field_name: str
    field_value: str
    evidence: str
    source_name: str
    source_kind: str
    source_key: str


def lifecycle_record_table_exists(db: Any) -> bool:
    row = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (_TABLE,),
    ).fetchone()
    return row is not None


def ensure_lifecycle_record_schema(db: Any) -> None:
    """Create builder-owned source-granular lifecycle storage.

    Runtime readers never call this helper. Finalized snapshots simply preserve the
    table when a builder source has populated it; older snapshots without the table
    remain readable and mean "no source-granular lifecycle records compiled".
    """
    db.conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entity_lifecycle_records (
            entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            source_page_id INTEGER NOT NULL REFERENCES source_pages(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL,
            field_value TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(entity_id, source_page_id, field_name)
        );
        CREATE INDEX IF NOT EXISTS ix_entity_lifecycle_records_source
        ON entity_lifecycle_records(source_page_id);
        CREATE INDEX IF NOT EXISTS ix_entity_lifecycle_records_entity
        ON entity_lifecycle_records(entity_id);
        """
    )
    commit = getattr(db, "_commit", None)
    if callable(commit):
        commit()
    else:
        db.conn.commit()


def clear_lifecycle_records_for_source(db: Any, source_page_id: int) -> None:
    ensure_lifecycle_record_schema(db)
    db.conn.execute(
        "DELETE FROM entity_lifecycle_records WHERE source_page_id=?",
        (int(source_page_id),),
    )
    commit = getattr(db, "_commit", None)
    if callable(commit):
        commit()
    else:
        db.conn.commit()


def upsert_lifecycle_record(
    db: Any,
    *,
    entity_id: int,
    source_page_id: int,
    field_name: str,
    field_value: str,
    evidence: str = "",
) -> None:
    ensure_lifecycle_record_schema(db)
    field = str(field_name or "").strip().casefold()
    value = " ".join(str(field_value or "").split()).strip()
    if not field or not value:
        return
    db.conn.execute(
        """
        INSERT INTO entity_lifecycle_records(
            entity_id, source_page_id, field_name, field_value, evidence
        ) VALUES(?,?,?,?,?)
        ON CONFLICT(entity_id, source_page_id, field_name) DO UPDATE SET
            field_value=excluded.field_value,
            evidence=excluded.evidence
        """,
        (int(entity_id), int(source_page_id), field, value, str(evidence or "")),
    )
    if hasattr(db, "link_entity_source"):
        db.link_entity_source(
            int(entity_id),
            int(source_page_id),
            role="lifecycle",
        )
    commit = getattr(db, "_commit", None)
    if callable(commit):
        commit()
    else:
        db.conn.commit()


def lifecycle_records_for_entity(db: Any, entity_id: int) -> tuple[EntityLifecycleRecord, ...]:
    if not lifecycle_record_table_exists(db):
        return ()
    rows = db.conn.execute(
        """
        SELECT r.entity_id,r.source_page_id,r.field_name,r.field_value,r.evidence,
               COALESCE(sp.source_name,'') AS source_name,
               COALESCE(sp.source_kind,'') AS source_kind,
               COALESCE(sp.source_key,'') AS source_key
        FROM entity_lifecycle_records r
        JOIN source_pages sp ON sp.id=r.source_page_id
        WHERE r.entity_id=?
        ORDER BY r.field_name, sp.source_name, sp.source_key, r.source_page_id
        """,
        (int(entity_id),),
    ).fetchall()
    return tuple(
        EntityLifecycleRecord(
            entity_id=int(row["entity_id"]),
            source_page_id=int(row["source_page_id"]),
            field_name=str(row["field_name"] or ""),
            field_value=str(row["field_value"] or ""),
            evidence=str(row["evidence"] or ""),
            source_name=str(row["source_name"] or ""),
            source_kind=str(row["source_kind"] or ""),
            source_key=str(row["source_key"] or ""),
        )
        for row in rows
    )
