from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any
import urllib.parse

from .db import normalize_name


_TABLE = "entity_lifecycle_records"


@dataclass(frozen=True, slots=True)
class EntityLifecycleRecord:
    entity_id: int
    source_page_id: int
    entity_kind: str
    source_external_id: str
    source_entity_name: str
    field_name: str
    field_value: str
    evidence: str
    source_name: str
    source_kind: str
    source_key: str


@dataclass(frozen=True, slots=True)
class LifecycleReconciliationResult:
    scanned: int = 0
    linked: int = 0
    already_linked: int = 0
    unresolved_identity: int = 0
    name_mismatch: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "linked": self.linked,
            "already_linked": self.already_linked,
            "unresolved_identity": self.unresolved_identity,
            "name_mismatch": self.name_mismatch,
        }


def lifecycle_record_table_exists(db: Any) -> bool:
    row = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (_TABLE,),
    ).fetchone()
    return row is not None


def ensure_lifecycle_record_schema(db: Any) -> None:
    """Create builder-owned source-granular lifecycle storage.

    ``entity_id`` is deliberately nullable. A source such as the Allakhazam mirror may
    run before the canonical EQ-client/MCP identity provider in the same build. Source
    facts are preserved immediately and attached later only after exact reconciliation.

    Runtime readers never call this helper. Finalized snapshots simply preserve the
    table when a builder source has populated it; older snapshots without the table
    remain readable and mean "no source-granular lifecycle records compiled".
    """
    db.conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entity_lifecycle_records (
            source_page_id INTEGER NOT NULL REFERENCES source_pages(id) ON DELETE CASCADE,
            entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
            entity_kind TEXT NOT NULL,
            source_external_id TEXT NOT NULL,
            source_entity_name TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value TEXT NOT NULL,
            evidence TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(source_page_id, entity_kind, source_external_id, field_name)
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
    # Re-imports also withdraw any previous exact canonical attachment from this page.
    db.conn.execute(
        "DELETE FROM entity_sources WHERE source_page_id=? AND role='lifecycle'",
        (int(source_page_id),),
    )
    db.conn.execute(
        "DELETE FROM entity_external_ids WHERE source_page_id=? AND namespace='allakhazam:spell'",
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
    source_page_id: int,
    entity_kind: str,
    source_external_id: str,
    source_entity_name: str,
    field_name: str,
    field_value: str,
    evidence: str = "",
    entity_id: int | None = None,
) -> None:
    ensure_lifecycle_record_schema(db)
    kind = str(entity_kind or "").strip().casefold()
    external_id = str(source_external_id or "").strip()
    source_name = " ".join(str(source_entity_name or "").split()).strip()
    field = str(field_name or "").strip().casefold()
    value = " ".join(str(field_value or "").split()).strip()
    if not kind or not external_id or not source_name or not field or not value:
        return
    db.conn.execute(
        """
        INSERT INTO entity_lifecycle_records(
            source_page_id, entity_id, entity_kind, source_external_id,
            source_entity_name, field_name, field_value, evidence
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(source_page_id, entity_kind, source_external_id, field_name) DO UPDATE SET
            entity_id=excluded.entity_id,
            source_entity_name=excluded.source_entity_name,
            field_value=excluded.field_value,
            evidence=excluded.evidence
        """,
        (
            int(source_page_id),
            (int(entity_id) if entity_id is not None else None),
            kind,
            external_id,
            source_name,
            field,
            value,
            str(evidence or ""),
        ),
    )
    if entity_id is not None and hasattr(db, "link_entity_source"):
        db.link_entity_source(int(entity_id), int(source_page_id), role="lifecycle")
    commit = getattr(db, "_commit", None)
    if callable(commit):
        commit()
    else:
        db.conn.commit()


def _canonical_spell_identity(db: Any, entity_id: int) -> tuple[str, str] | None:
    entity = db.conn.execute(
        "SELECT id,kind,name FROM entities WHERE id=?",
        (int(entity_id),),
    ).fetchone()
    if entity is None or str(entity["kind"] or "") != "spell":
        return None
    external = db.conn.execute(
        """
        SELECT external_id FROM entity_external_ids
        WHERE entity_id=? AND namespace='eqclient:spell'
        LIMIT 1
        """,
        (int(entity_id),),
    ).fetchone()
    if external is None:
        return None
    numeric_id = str(external["external_id"] or "").strip()
    if not numeric_id.isdigit():
        return None
    return numeric_id, str(entity["name"] or "")


def lifecycle_records_for_entity(db: Any, entity_id: int) -> tuple[EntityLifecycleRecord, ...]:
    if not lifecycle_record_table_exists(db):
        return ()

    canonical_spell = _canonical_spell_identity(db, int(entity_id))
    source_spell_key = f"spell:{canonical_spell[0]}" if canonical_spell else ""
    rows = db.conn.execute(
        """
        SELECT r.entity_id,r.source_page_id,r.entity_kind,r.source_external_id,
               r.source_entity_name,r.field_name,r.field_value,r.evidence,
               COALESCE(sp.source_name,'') AS source_name,
               COALESCE(sp.source_kind,'') AS source_kind,
               COALESCE(sp.source_key,'') AS source_key
        FROM entity_lifecycle_records r
        JOIN source_pages sp ON sp.id=r.source_page_id
        WHERE r.entity_id=?
           OR (
                r.entity_id IS NULL
                AND r.entity_kind='spell'
                AND r.source_external_id=?
                AND lower(sp.source_name)='allakhazam'
                AND lower(sp.source_kind)='local_mirror'
           )
        ORDER BY r.field_name, sp.source_name, sp.source_key, r.source_page_id
        """,
        (int(entity_id), source_spell_key),
    ).fetchall()

    result: list[EntityLifecycleRecord] = []
    for row in rows:
        resolved_entity_id = row["entity_id"]
        if resolved_entity_id is None:
            # Read-only fallback makes provider order irrelevant even before an optional
            # builder reconciliation pass. Numeric spell ID AND exact normalized name
            # must both agree; a matching number alone never attaches the source fact.
            if canonical_spell is None or normalize_name(str(row["source_entity_name"] or "")) != normalize_name(canonical_spell[1]):
                continue
            resolved_entity_id = int(entity_id)
        result.append(
            EntityLifecycleRecord(
                entity_id=int(resolved_entity_id),
                source_page_id=int(row["source_page_id"]),
                entity_kind=str(row["entity_kind"] or ""),
                source_external_id=str(row["source_external_id"] or ""),
                source_entity_name=str(row["source_entity_name"] or ""),
                field_name=str(row["field_name"] or ""),
                field_value=str(row["field_value"] or ""),
                evidence=str(row["evidence"] or ""),
                source_name=str(row["source_name"] or ""),
                source_kind=str(row["source_kind"] or ""),
                source_key=str(row["source_key"] or ""),
            )
        )
    return tuple(result)


def _allakhazam_spell_numeric_id(source_external_id: str, source_key: str, url: str) -> str:
    for candidate in (source_external_id, source_key):
        text = str(candidate or "").strip()
        if text.casefold().startswith("spell:"):
            text = text.split(":", 1)[1].strip()
        if text.isdigit():
            return text
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        value = (urllib.parse.parse_qs(parsed.query).get("spell") or [""])[0]
        return str(value).strip() if str(value).strip().isdigit() else ""
    except Exception:
        return ""


def reconcile_allakhazam_spell_lifecycle(db: Any) -> LifecycleReconciliationResult:
    """Persist exact source→canonical attachments when a builder has all providers.

    This is an optimization/provenance projection, not required for correctness:
    runtime readers can resolve still-unattached records read-only using the same exact
    numeric-ID + normalized-name rule.
    """
    if not lifecycle_record_table_exists(db):
        return LifecycleReconciliationResult()

    rows = db.conn.execute(
        """
        SELECT r.source_page_id,r.entity_id,r.source_external_id,r.source_entity_name,
               sp.source_key,sp.url
        FROM entity_lifecycle_records r
        JOIN source_pages sp ON sp.id=r.source_page_id
        WHERE r.entity_kind='spell'
          AND lower(sp.source_name)='allakhazam'
          AND lower(sp.source_kind)='local_mirror'
        ORDER BY r.source_page_id,r.source_external_id,r.field_name
        """
    ).fetchall()

    scanned = linked = already = unresolved = mismatch = 0
    seen: set[tuple[int, str]] = set()
    source_ids = sorted({int(row["source_page_id"]) for row in rows})
    context = db.batch() if hasattr(db, "batch") else nullcontext()
    with context:
        if source_ids:
            placeholders = ",".join("?" for _ in source_ids)
            db.conn.execute(
                f"DELETE FROM entity_sources WHERE role='lifecycle' AND source_page_id IN ({placeholders})",
                source_ids,
            )
            db.conn.execute(
                f"DELETE FROM entity_external_ids WHERE namespace='allakhazam:spell' AND source_page_id IN ({placeholders})",
                source_ids,
            )

        for row in rows:
            source_page_id = int(row["source_page_id"])
            source_external_id = str(row["source_external_id"] or "")
            record_key = (source_page_id, source_external_id)
            if record_key in seen:
                continue
            seen.add(record_key)
            scanned += 1

            numeric_id = _allakhazam_spell_numeric_id(
                source_external_id,
                str(row["source_key"] or ""),
                str(row["url"] or ""),
            )
            canonical = (
                db.entity_by_namespaced_external_id("eqclient:spell", numeric_id)
                if numeric_id
                else None
            )
            if canonical is None:
                unresolved += 1
                db.conn.execute(
                    """
                    UPDATE entity_lifecycle_records SET entity_id=NULL
                    WHERE source_page_id=? AND entity_kind='spell' AND source_external_id=?
                    """,
                    record_key,
                )
                continue

            if normalize_name(str(canonical["name"] or "")) != normalize_name(
                str(row["source_entity_name"] or "")
            ):
                mismatch += 1
                db.conn.execute(
                    """
                    UPDATE entity_lifecycle_records SET entity_id=NULL
                    WHERE source_page_id=? AND entity_kind='spell' AND source_external_id=?
                    """,
                    record_key,
                )
                continue

            canonical_id = int(canonical["id"])
            if row["entity_id"] is not None and int(row["entity_id"]) == canonical_id:
                already += 1
            else:
                linked += 1
            db.conn.execute(
                """
                UPDATE entity_lifecycle_records SET entity_id=?
                WHERE source_page_id=? AND entity_kind='spell' AND source_external_id=?
                """,
                (canonical_id, source_page_id, source_external_id),
            )
            if hasattr(db, "link_entity_source"):
                db.link_entity_source(canonical_id, source_page_id, role="lifecycle")
            if hasattr(db, "add_external_id"):
                db.add_external_id(
                    canonical_id,
                    "allakhazam:spell",
                    f"spell:{numeric_id}",
                    source_page_id=source_page_id,
                )

    return LifecycleReconciliationResult(
        scanned=scanned,
        linked=linked,
        already_linked=already,
        unresolved_identity=unresolved,
        name_mismatch=mismatch,
    )
