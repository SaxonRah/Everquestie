from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

from .db import Database
from .db_audit import identity_audit_text
from .entity_lifecycle_records import reconcile_allakhazam_spell_lifecycle
from .map_catalog import MapCatalog
from .map_portability import normalize_legacy_map_sources
from .mechanics_catalog import MechanicsCatalog
from .provider_zone_travel import ProviderZoneTravelCatalog
from .quest_faction_reconciliation import QuestFactionReconciliationCatalog
from .search_index import rebuild_compact_search_index
from .zone_catalog import ZoneMapCatalog
from .zone_coverage import ZoneCoverageCatalog
from .zone_provider_reconciliation import ProviderZoneReconciliationCatalog
from .zone_travel import ZoneTravelCatalog


# Schema compatibility and content release identity are deliberately separate.
# Bump this only when a packaged knowledge DB requires a different reader contract.
KNOWLEDGE_SCHEMA_VERSION = "1"

USER_STATE_TABLES = (
    "quest_progress",
    "tracked_quests",
    "observed_events",
)

# app_meta currently mixes historical runtime settings with build metadata. A release
# snapshot keeps only values that describe the knowledge artifact itself. Future source
# adapters should put durable provenance/version data in source_pages whenever possible.
KNOWLEDGE_META_KEYS = {
    "database_role",
    "knowledge_schema_version",
    "knowledge_snapshot_version",
    "knowledge_snapshot_built_at",
    "fts_dirty",
    "fts_last_rebuild",
    "map_catalog_version",
    "map_catalog_last_source",
    "map_links_dirty",
    "mechanics_catalog_version",
    "mechanics_catalog_coverage",
    "provider_zone_catalog_version",
    "provider_zone_catalog_coverage",
    "provider_zone_travel_catalog_version",
    "provider_zone_travel_catalog_coverage",
    "zone_coverage_version",
    "zone_catalog_coverage",
    "eq_mcp_last_compile",
    "eq_mcp_version",
    "eq_mcp_commit",
    "eq_mcp_system_counts",
    "eq_mcp_detail_last_compile",
    "eq_mcp_detail_counts",
    "eq_mcp_detail_errors",
    "eq_mcp_detail_missing_systems",
    # Compact reviewed-input provenance is part of the released artifact contract.
    # Keep exact counters rather than a broad approved_* prefix so builder-only fields
    # cannot become distributable metadata by accident.
    "approved_zone_alias_supplement_count",
    "approved_zone_alias_count",
    "approved_travel_supplement_count",
    "approved_travel_supplement_edge_count",
}
KNOWLEDGE_META_PREFIXES = (
    "map_catalog_source_version::",
    "source_version::",
)


@dataclass(slots=True)
class KnowledgeSnapshotReport:
    path: Path
    snapshot_version: str
    schema_version: str
    built_at: str
    stripped_user_rows: dict[str, int]
    stripped_source_paths: int
    stripped_meta_rows: int
    stripped_builder_payloads: int
    mechanics_reconciliation: dict[str, Any]
    lifecycle_reconciliation: dict[str, int]
    quest_faction_reconciliation: dict[str, int]
    provider_zone_reconciliation: dict[str, int]
    provider_zone_travel: dict[str, int]
    zone_coverage: dict[str, Any]
    map_reconciliation: dict[str, int]
    fts_rows: int
    diagnostics: dict[str, Any]
    identity_audit: str


def _table_exists(db: Database, table: str) -> bool:
    row = db.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _looks_absolute_filesystem_path(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    return value.startswith(("/", "\\")) or bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _keep_meta_key(key: str) -> bool:
    return key in KNOWLEDGE_META_KEYS or any(key.startswith(prefix) for prefix in KNOWLEDGE_META_PREFIXES)


def strip_user_state(db: Database) -> dict[str, int]:
    """Delete rows that belong to a player/session rather than global knowledge."""
    removed: dict[str, int] = {}
    with db.batch():
        for table in USER_STATE_TABLES:
            if not _table_exists(db, table):
                removed[table] = 0
                continue
            count = int(db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            db.conn.execute(f"DELETE FROM {table}")
            removed[table] = count
    return removed


def strip_builder_local_state(db: Database) -> tuple[int, int, int]:
    """Remove machine-local paths/settings and raw builder-only payloads.

    Knowledge/provenance identities remain intact. In particular, source_name,
    source_kind, source_key, source_version and source hashes are retained.
    """
    stripped_paths = 0
    stripped_meta = 0
    stripped_payloads = 0
    with db.batch():
        if _table_exists(db, "source_pages"):
            stripped_paths = int(
                db.conn.execute(
                    "SELECT COUNT(*) FROM source_pages WHERE trim(COALESCE(local_path,''))<>''"
                ).fetchone()[0]
            )
            db.conn.execute("UPDATE source_pages SET local_path='' WHERE local_path<>''")

            # MCP snapshot JSON is builder evidence, not runtime knowledge, and can
            # contain the builder's EverQuest installation path. The normalized
            # entities/support rows and source hash/version are the distributable data.
            stripped_payloads = int(
                db.conn.execute(
                    "SELECT COUNT(*) FROM source_pages "
                    "WHERE source_kind='mcp_local_snapshot' AND plain_text<>''"
                ).fetchone()[0]
            )
            db.conn.execute(
                "UPDATE source_pages SET plain_text='' "
                "WHERE source_kind='mcp_local_snapshot' AND plain_text<>''"
            )

        if _table_exists(db, "map_sources"):
            # root is a legacy compatibility column. Fresh portable catalog rows use
            # source_name/source_key for identity; normalize root so it cannot retain
            # an old builder-machine directory.
            cols = {
                str(row["name"])
                for row in db.conn.execute("PRAGMA table_info(map_sources)").fetchall()
            }
            if "source_name" in cols and "root" in cols:
                db.conn.execute("UPDATE map_sources SET root=source_name")

        if _table_exists(db, "app_meta"):
            keys = [str(row["key"]) for row in db.conn.execute("SELECT key FROM app_meta").fetchall()]
            drop = [key for key in keys if not _keep_meta_key(key)]
            for key in drop:
                db.conn.execute("DELETE FROM app_meta WHERE key=?", (key,))
            stripped_meta = len(drop)
    return stripped_paths, stripped_meta, stripped_payloads


def snapshot_portability_errors(db: Database) -> list[str]:
    """Return release-blocking evidence of player state or builder-local paths."""
    errors: list[str] = []
    for table in USER_STATE_TABLES:
        if _table_exists(db, table):
            count = int(db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if count:
                errors.append(f"{table} still contains {count} user-state row(s)")

    if _table_exists(db, "source_pages"):
        rows = db.conn.execute(
            "SELECT id,source_name,source_key,local_path FROM source_pages"
        ).fetchall()
        for row in rows:
            local_path = str(row["local_path"] or "")
            if local_path:
                errors.append(f"source_pages id {row['id']} retains local_path={local_path!r}")
            source_key = str(row["source_key"] or "")
            if _looks_absolute_filesystem_path(source_key):
                errors.append(
                    f"source_pages id {row['id']} ({row['source_name']}) has absolute source_key={source_key!r}"
                )

    if _table_exists(db, "map_sources"):
        cols = {
            str(row["name"])
            for row in db.conn.execute("PRAGMA table_info(map_sources)").fetchall()
        }
        wanted = [name for name in ("id", "source_name", "source_key", "path", "root") if name in cols]
        if wanted:
            rows = db.conn.execute(f"SELECT {','.join(wanted)} FROM map_sources").fetchall()
            for row in rows:
                row_id = row["id"] if "id" in cols else "?"
                source_key = str(row["source_key"] or "") if "source_key" in cols else ""
                path = str(row["path"] or "") if "path" in cols else ""
                root = str(row["root"] or "") if "root" in cols else ""
                source_name = str(row["source_name"] or "") if "source_name" in cols else ""
                if _looks_absolute_filesystem_path(source_key):
                    errors.append(f"map_sources id {row_id} has absolute source_key={source_key!r}")
                if path and not path.startswith("mapcatalog://"):
                    errors.append(f"map_sources id {row_id} has non-portable path={path!r}")
                if root and source_name and root != source_name:
                    errors.append(f"map_sources id {row_id} retains builder root={root!r}")

    return errors


def finalize_knowledge_snapshot(
    db: Database,
    *,
    snapshot_version: str,
    built_at: str | None = None,
) -> KnowledgeSnapshotReport:
    """Finalize an already-populated DB into a distributable knowledge artifact."""
    version = str(snapshot_version).strip()
    if not version:
        raise ValueError("snapshot_version is required")
    built = built_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Compile deterministic client-table IDs into canonical class/skill identities
    # before FTS finalization. Raw support rows remain exact client evidence; this
    # semantic layer makes them queryable by stable names and future provider IDs.
    mechanics_coverage = MechanicsCatalog(db).reconcile()

    # Cross-source lifecycle facts are attached only after every provider has had a
    # chance to populate canonical identities. Allakhazam spell facts require the exact
    # numeric client spell ID AND exact normalized name; provider order cannot change
    # the finalized attachment result.
    lifecycle_reconciliation = reconcile_allakhazam_spell_lifecycle(db)

    # Structured Allakhazam quest faction names become graph edges only after all
    # providers have populated the builder DB and only when one exact client-backed
    # faction identity exists. Raw quest metadata remains untouched for unresolved or
    # ambiguous names; runtime consumes only the finalized ordinary relationships.
    quest_faction = QuestFactionReconciliationCatalog(db).reconcile()

    # Reconcile provider-owned zone identities into a separate, non-destructive
    # gameplay projection before any downstream catalogs are finalized. The provider
    # entities and their provenance remain untouched; runtime consumes only rows that
    # reached projection-safe `linked` status from builder evidence.
    provider_zone = ProviderZoneReconciliationCatalog(db).reconcile()

    # Ensure the base map schema exists even for client-only/mapless knowledge builds.
    # Historic builder DBs may still contain absolute Windows paths from the original
    # runtime map index. Normalize those rows in the snapshot copy before any derived
    # zone/map/travel reconciliation so release knowledge never retains a builder path.
    map_catalog = MapCatalog(db)
    normalize_legacy_map_sources(db)

    # Reconcile after every provider has run. This makes provider order irrelevant:
    # aliases/identities supplied late in a build can resolve map stems, labels and
    # travel candidates that were imported earlier. Future Allakhazam/wiki providers
    # therefore enrich the same canonical catalogs instead of becoming runtime deps.
    zone_map = ZoneMapCatalog(db).reconcile()
    map_reconciliation = map_catalog.reconcile_all(force=True)
    zone_travel = ZoneTravelCatalog(db).reconcile_from_maps()
    map_reconciliation.update(
        {
            "zone_maps": int(zone_map.maps),
            "zone_maps_linked": int(zone_map.linked),
            "zone_maps_ambiguous": int(zone_map.ambiguous),
            "zone_maps_unresolved": int(zone_map.unresolved),
            "zone_travel_candidates": int(zone_travel.candidates),
            "zone_travel_linked": int(zone_travel.linked),
            "zone_travel_ambiguous": int(zone_travel.ambiguous),
            "zone_travel_unresolved": int(zone_travel.unresolved),
        }
    )

    # Provider topology is compiled only after the provider-zone identity catalog is
    # fixed. The resulting rows use canonical gameplay IDs and share zone_travel_edges
    # with map evidence; runtime routing therefore stays completely source-agnostic.
    provider_travel = ProviderZoneTravelCatalog(db).reconcile()

    # Coverage is compiled only after both map and provider topology are finalized, so
    # release metrics describe the exact graph users will receive.
    zone_coverage = ZoneCoverageCatalog(db).compile_summary()

    stripped_user = strip_user_state(db)
    stripped_paths, stripped_meta, stripped_payloads = strip_builder_local_state(db)

    db.set_meta("database_role", "knowledge_snapshot")
    db.set_meta("knowledge_schema_version", KNOWLEDGE_SCHEMA_VERSION)
    db.set_meta("knowledge_snapshot_version", version)
    db.set_meta("knowledge_snapshot_built_at", built)

    fts_rows = rebuild_compact_search_index(db)
    identity = identity_audit_text(db)

    errors = snapshot_portability_errors(db)
    diagnostics = db.database_diagnostics()
    if diagnostics.get("integrity") != "ok":
        errors.append(f"PRAGMA integrity_check returned {diagnostics.get('integrity')!r}")
    if diagnostics.get("fts_available") and diagnostics.get("fts_dirty"):
        errors.append("FTS index is still marked dirty after rebuild")
    if errors:
        raise ValueError("Knowledge snapshot is not portable:\n- " + "\n- ".join(errors))

    # A packaged knowledge DB must not depend on WAL sidecars. These operations are
    # builder-only; runtime opens the shipped artifact read-only/immutable.
    db.conn.commit()
    try:
        db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        pass
    db.conn.execute("PRAGMA journal_mode=DELETE")
    db.conn.execute("PRAGMA optimize")
    db.conn.execute("VACUUM")
    db.conn.execute("PRAGMA optimize")
    db.conn.commit()

    diagnostics = db.database_diagnostics()
    if diagnostics.get("integrity") != "ok":
        raise ValueError(
            f"Final knowledge snapshot failed integrity_check: {diagnostics.get('integrity')!r}"
        )

    return KnowledgeSnapshotReport(
        path=db.path,
        snapshot_version=version,
        schema_version=KNOWLEDGE_SCHEMA_VERSION,
        built_at=built,
        stripped_user_rows=stripped_user,
        stripped_source_paths=stripped_paths,
        stripped_meta_rows=stripped_meta,
        stripped_builder_payloads=stripped_payloads,
        mechanics_reconciliation=mechanics_coverage.as_dict(),
        lifecycle_reconciliation=lifecycle_reconciliation.as_dict(),
        quest_faction_reconciliation=quest_faction.as_dict(),
        provider_zone_reconciliation=provider_zone.as_dict(),
        provider_zone_travel=provider_travel.as_dict(),
        zone_coverage=zone_coverage.as_dict(),
        map_reconciliation=map_reconciliation,
        fts_rows=fts_rows,
        diagnostics=diagnostics,
        identity_audit=identity,
    )


def create_knowledge_snapshot(
    source_db: str | Path,
    output_db: str | Path,
    *,
    snapshot_version: str,
    overwrite: bool = False,
) -> KnowledgeSnapshotReport:
    """Copy a working DB, finalize the copy, and atomically publish the snapshot."""
    source = Path(source_db).expanduser().resolve()
    output = Path(output_db).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == output:
        raise ValueError("Knowledge snapshots must be written to a separate output file")
    if output.exists() and not overwrite:
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    temp = output.with_name(output.name + ".building")
    temp.unlink(missing_ok=True)
    try:
        source_conn = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        destination_conn = sqlite3.connect(temp)
        try:
            source_conn.backup(destination_conn)
        finally:
            destination_conn.close()
            source_conn.close()

        db = Database(temp)
        try:
            report = finalize_knowledge_snapshot(db, snapshot_version=snapshot_version)
        finally:
            db.close()

        if output.exists():
            output.unlink()
        os.replace(temp, output)
        report.path = output
        return report
    except Exception:
        temp.unlink(missing_ok=True)
        raise
