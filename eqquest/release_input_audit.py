from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Any

from .travel_supplement import (
    TRAVEL_SUPPLEMENT_SCHEMA_VERSION,
    TRAVEL_SUPPLEMENT_SOURCE_KIND,
)
from .zone_alias_supplement import (
    ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
    ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
)


ZONE_ALIAS_RELEASE_META_KEYS = (
    "approved_zone_alias_supplement_count",
    "approved_zone_alias_count",
)
TRAVEL_RELEASE_META_KEYS = (
    "approved_travel_supplement_count",
    "approved_travel_supplement_edge_count",
)
REVIEWED_RELEASE_META_KEYS = ZONE_ALIAS_RELEASE_META_KEYS + TRAVEL_RELEASE_META_KEYS
_RELEASE_META_FAMILIES = (
    ("zone-alias", ZONE_ALIAS_RELEASE_META_KEYS),
    ("travel", TRAVEL_RELEASE_META_KEYS),
)


@dataclass(frozen=True, slots=True)
class ReviewedReleaseInputAudit:
    recorded: bool
    status: str
    metadata: dict[str, int | None]
    actual: dict[str, int]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "recorded": self.recorded,
            "status": self.status,
            "metadata": dict(self.metadata),
            "actual": dict(self.actual),
            "errors": list(self.errors),
        }


def _knowledge_schema(db) -> str:
    """Return the immutable knowledge schema when auditing RuntimeDatabase.

    RuntimeDatabase exposes a unioned TEMP ``app_meta`` view where user metadata can
    shadow knowledge metadata. Release provenance must never use that view. When the
    packaged knowledge attachment exists, address it directly instead.
    """
    if getattr(db, "knowledge_writable", True):
        return ""
    try:
        db.conn.execute("SELECT 1 FROM knowledge.sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error:
        return ""
    return "knowledge."


def _table_exists(db, table: str, schema: str) -> bool:
    if schema:
        row = db.conn.execute(
            "SELECT 1 FROM knowledge.sqlite_master "
            "WHERE type IN ('table','view') AND name=? LIMIT 1",
            (table,),
        ).fetchone()
        return row is not None
    row = db.conn.execute(
        "SELECT 1 FROM sqlite_temp_master "
        "WHERE type IN ('table','view') AND name=? "
        "UNION ALL "
        "SELECT 1 FROM sqlite_master "
        "WHERE type IN ('table','view') AND name=? LIMIT 1",
        (table, table),
    ).fetchone()
    return row is not None


def _recorded_metadata(
    db,
    schema: str,
) -> tuple[bool, dict[str, int | None], frozenset[str], list[str]]:
    """Read reviewed counters as independently optional, internally atomic families."""
    metadata = {key: None for key in REVIEWED_RELEASE_META_KEYS}
    errors: list[str] = []
    if not _table_exists(db, "app_meta", schema):
        return False, metadata, frozenset(), errors

    placeholders = ",".join("?" for _ in REVIEWED_RELEASE_META_KEYS)
    rows = db.conn.execute(
        f"SELECT key,value FROM {schema}app_meta WHERE key IN ({placeholders})",
        REVIEWED_RELEASE_META_KEYS,
    ).fetchall()
    raw = {str(row["key"]): str(row["value"]).strip() for row in rows}
    if not raw:
        return False, metadata, frozenset(), errors

    recorded_families: set[str] = set()
    for family, keys in _RELEASE_META_FAMILIES:
        present = [key for key in keys if key in raw]
        if not present:
            continue
        recorded_families.add(family)
        missing = [key for key in keys if key not in raw]
        if missing:
            errors.append(
                f"reviewed {family} release-input metadata is incomplete; missing "
                + ", ".join(missing)
            )

    for key in REVIEWED_RELEASE_META_KEYS:
        if key not in raw:
            continue
        try:
            value = int(raw[key])
        except ValueError:
            errors.append(f"{key} is not an integer: {raw[key]!r}")
            continue
        if value < 0:
            errors.append(f"{key} must be non-negative, found {value}")
            continue
        metadata[key] = value

    return True, metadata, frozenset(recorded_families), errors


def _alias_actuals(db, schema: str, errors: list[str]) -> tuple[int, int]:
    if not _table_exists(db, "source_pages", schema):
        errors.append("source_pages is missing while reviewed zone-alias metadata is recorded")
        return 0, 0
    if not _table_exists(db, "entity_aliases", schema):
        errors.append("entity_aliases is missing while reviewed zone-alias metadata is recorded")
        return 0, 0

    pages = db.conn.execute(
        f"SELECT id,source_name,source_key,source_version,entity_type "
        f"FROM {schema}source_pages WHERE source_kind=? ORDER BY id",
        (ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,),
    ).fetchall()
    page_ids = {int(row["id"]): row for row in pages}
    supplement_names = {str(row["source_name"] or "").strip() for row in pages}
    supplement_names.discard("")

    for row in pages:
        page_id = int(row["id"])
        if not str(row["source_name"] or "").strip():
            errors.append(f"reviewed zone-alias source page {page_id} has no source_name")
        if not str(row["source_key"] or "").strip():
            errors.append(f"reviewed zone-alias source page {page_id} has no source_key")
        if not str(row["source_version"] or "").strip():
            errors.append(f"reviewed zone-alias source page {page_id} has no source_version")
        if str(row["entity_type"] or "") != "zone_alias":
            errors.append(
                f"reviewed zone-alias source page {page_id} has unexpected entity_type "
                f"{str(row['entity_type'] or '')!r}"
            )

    aliases = db.conn.execute(
        f"SELECT ea.id,ea.source_page_id,sp.source_kind "
        f"FROM {schema}entity_aliases ea "
        f"LEFT JOIN {schema}source_pages sp ON sp.id=ea.source_page_id "
        "WHERE ea.alias_type=? ORDER BY ea.id",
        (ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,),
    ).fetchall()

    matching_aliases = []
    aliases_per_page: dict[int, int] = {}
    outside_source = 0
    for row in aliases:
        source_page_id = row["source_page_id"]
        if (
            source_page_id is None
            or str(row["source_kind"] or "") != ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND
        ):
            outside_source += 1
            continue
        page_id = int(source_page_id)
        if page_id not in page_ids:
            outside_source += 1
            continue
        matching_aliases.append(row)
        aliases_per_page[page_id] = aliases_per_page.get(page_id, 0) + 1

    if outside_source:
        errors.append(
            f"{outside_source} reviewed zone alias row(s) are not owned by "
            f"{ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND} provenance"
        )
    for page_id in sorted(page_ids):
        count = aliases_per_page.get(page_id, 0)
        if count != 1:
            errors.append(
                f"reviewed zone-alias source page {page_id} owns {count} alias row(s); expected 1"
            )

    return len(supplement_names), len(matching_aliases)


def _travel_actuals(db, schema: str, errors: list[str]) -> tuple[int, int]:
    if not _table_exists(db, "zone_travel_edges", schema):
        errors.append("zone_travel_edges is missing while reviewed travel metadata is recorded")
        return 0, 0

    rows = db.conn.execute(
        f"SELECT id,source_name,source_key,source_version,status,target_zone_entity_id,"
        f"evidence,data_json FROM {schema}zone_travel_edges "
        "WHERE source_kind=? ORDER BY id",
        (TRAVEL_SUPPLEMENT_SOURCE_KIND,),
    ).fetchall()
    supplement_names = {str(row["source_name"] or "").strip() for row in rows}
    supplement_names.discard("")
    key_counts: dict[tuple[str, str], int] = {}

    for row in rows:
        row_id = int(row["id"])
        source_name = str(row["source_name"] or "").strip()
        source_key = str(row["source_key"] or "").strip()
        source_version = str(row["source_version"] or "").strip()
        if not source_name:
            errors.append(f"reviewed travel row {row_id} has no source_name")
        if not source_key:
            errors.append(f"reviewed travel row {row_id} has no source_key")
        if not source_version:
            errors.append(f"reviewed travel row {row_id} has no source_version")
        if str(row["status"] or "") != "linked" or row["target_zone_entity_id"] is None:
            errors.append(f"reviewed travel row {row_id} is not a linked canonical transition")
        if not str(row["evidence"] or "").strip():
            errors.append(f"reviewed travel row {row_id} has no explicit evidence")

        key = (source_name, source_key)
        key_counts[key] = key_counts.get(key, 0) + 1

        try:
            payload = json.loads(str(row["data_json"] or "{}"))
        except json.JSONDecodeError:
            errors.append(f"reviewed travel row {row_id} has invalid data_json")
            continue
        if not isinstance(payload, dict):
            errors.append(f"reviewed travel row {row_id} data_json is not an object")
            continue
        if payload.get("manifest_schema_version") != TRAVEL_SUPPLEMENT_SCHEMA_VERSION:
            errors.append(
                f"reviewed travel row {row_id} has manifest_schema_version "
                f"{payload.get('manifest_schema_version')!r}; expected "
                f"{TRAVEL_SUPPLEMENT_SCHEMA_VERSION}"
            )
        if str(payload.get("manifest_source_key") or "") != source_key:
            errors.append(
                f"reviewed travel row {row_id} manifest_source_key does not match source_key"
            )

    duplicates = [key for key, count in key_counts.items() if count != 1]
    for source_name, source_key in sorted(duplicates):
        errors.append(
            f"reviewed travel manifest key {source_name!r}/{source_key!r} is stored "
            f"{key_counts[(source_name, source_key)]} times; expected 1"
        )

    return len(supplement_names), len(rows)


def audit_reviewed_release_inputs(db) -> ReviewedReleaseInputAudit:
    """Compare retained reviewed-input counters with persisted release evidence.

    The audit is read-only. Zone-alias and travel counters are independent release-input
    families because lower-level builders may compile either family without the other.
    Within a recorded family both counters are required and must match persisted curated
    evidence. Missing families remain uncontracted for backward compatibility with old
    snapshots and the supported lower-level build helpers.
    """
    schema = _knowledge_schema(db)
    recorded, metadata, recorded_families, errors = _recorded_metadata(db, schema)

    # Old snapshots deliberately did not retain these counters. Do not reinterpret
    # their surviving provenance as a new release contract after the fact.
    if not recorded:
        return ReviewedReleaseInputAudit(
            recorded=False,
            status="not_recorded",
            metadata=metadata,
            actual={
                "zone_alias_supplements": 0,
                "zone_aliases": 0,
                "travel_supplements": 0,
                "travel_edges": 0,
            },
            errors=(),
        )

    actual = {
        "zone_alias_supplements": 0,
        "zone_aliases": 0,
        "travel_supplements": 0,
        "travel_edges": 0,
    }

    if "zone-alias" in recorded_families:
        alias_supplements, aliases = _alias_actuals(db, schema, errors)
        actual["zone_alias_supplements"] = alias_supplements
        actual["zone_aliases"] = aliases
        comparisons = (
            ("approved_zone_alias_supplement_count", "zone_alias_supplements"),
            ("approved_zone_alias_count", "zone_aliases"),
        )
        for meta_key, actual_key in comparisons:
            expected = metadata.get(meta_key)
            if expected is None:
                continue
            found = actual[actual_key]
            if expected != found:
                errors.append(
                    f"{meta_key} records {expected}, but persisted reviewed evidence contains {found}"
                )

    if "travel" in recorded_families:
        travel_supplements, travel_edges = _travel_actuals(db, schema, errors)
        actual["travel_supplements"] = travel_supplements
        actual["travel_edges"] = travel_edges
        comparisons = (
            ("approved_travel_supplement_count", "travel_supplements"),
            ("approved_travel_supplement_edge_count", "travel_edges"),
        )
        for meta_key, actual_key in comparisons:
            expected = metadata.get(meta_key)
            if expected is None:
                continue
            found = actual[actual_key]
            if expected != found:
                errors.append(
                    f"{meta_key} records {expected}, but persisted reviewed evidence contains {found}"
                )

    return ReviewedReleaseInputAudit(
        recorded=True,
        status="ok" if not errors else "error",
        metadata=metadata,
        actual=actual,
        errors=tuple(errors),
    )
