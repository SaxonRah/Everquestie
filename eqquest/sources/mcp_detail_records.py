from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Callable

from ..mcp_client import MCPError, mcp_status
from . import mcp_snapshot as core


MCP_DETAIL_RECORD_SCHEMA_VERSION = "1"


def _ensure_detail_record_schema(db) -> None:
    db.conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mcp_detail_records (
            source_page_id INTEGER NOT NULL
                REFERENCES source_pages(id) ON DELETE CASCADE,
            system TEXT NOT NULL,
            kind TEXT NOT NULL,
            external_id TEXT NOT NULL,
            entity_id INTEGER NOT NULL
                REFERENCES entities(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT '',
            getter TEXT NOT NULL DEFAULT '',
            detail_format TEXT NOT NULL DEFAULT 'mcp-json',
            detail_text TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(source_page_id, system, external_id)
        );
        CREATE INDEX IF NOT EXISTS ix_mcp_detail_records_entity
        ON mcp_detail_records(entity_id, source_page_id);
        CREATE INDEX IF NOT EXISTS ix_mcp_detail_records_kind
        ON mcp_detail_records(source_page_id, kind);
        """
    )
    db.set_meta("mcp_detail_record_schema_version", MCP_DETAIL_RECORD_SCHEMA_VERSION)


def _stored_record_counts(db, source_page_id: int) -> dict[str, int]:
    rows = db.conn.execute(
        """
        SELECT kind, COUNT(*) AS n
        FROM mcp_detail_records
        WHERE source_page_id=?
        GROUP BY kind
        ORDER BY kind
        """,
        (int(source_page_id),),
    ).fetchall()
    return {str(row["kind"]): int(row["n"]) for row in rows}


def _stored_canonical_counts(db, source_page_id: int) -> dict[str, int]:
    rows = db.conn.execute(
        """
        SELECT e.kind, COUNT(*) AS n
        FROM entity_details d
        JOIN entities e ON e.id=d.entity_id
        WHERE d.source_page_id=?
        GROUP BY e.kind
        ORDER BY e.kind
        """,
        (int(source_page_id),),
    ).fetchall()
    return {str(row["kind"]): int(row["n"]) for row in rows}


def _load_json_meta(db, key: str, default):
    raw = db.get_meta(key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _persist_detail_record(
    db,
    *,
    source_page_id: int,
    system: str,
    kind: str,
    external_id: str,
    entity_id: int,
    name: str,
    getter: str,
    detail_text: str,
    detail_json,
) -> None:
    payload = json.dumps(detail_json, ensure_ascii=False)
    now = datetime.now().isoformat(timespec="seconds")
    db.conn.execute(
        """
        INSERT INTO mcp_detail_records(
            source_page_id,system,kind,external_id,entity_id,name,getter,
            detail_format,detail_text,detail_json,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_page_id,system,external_id) DO UPDATE SET
            kind=excluded.kind,
            entity_id=excluded.entity_id,
            name=excluded.name,
            getter=excluded.getter,
            detail_format=excluded.detail_format,
            detail_text=excluded.detail_text,
            detail_json=excluded.detail_json,
            updated_at=excluded.updated_at
        """,
        (
            int(source_page_id),
            system,
            kind,
            external_id,
            int(entity_id),
            name,
            getter,
            "mcp-json",
            detail_text,
            payload,
            now,
        ),
    )
    db.link_entity_source(int(entity_id), int(source_page_id), role="detail")


def _validate_inventory_accounting(
    capture: core.MCPSnapshotCapture,
    result: core.MCPCompileResult,
) -> None:
    failures: list[str] = []
    for system, payload in (capture.snapshot.get("systems") or {}).items():
        kind = core.SYSTEM_KIND_MAP.get(str(system))
        if not kind or not isinstance(payload, dict):
            continue
        names = payload.get("names") or {}
        if not isinstance(names, dict):
            continue
        expected = sum(1 for value in names.values() if str(value or "").strip())
        imported = int(result.detail_imported_by_kind.get(kind, 0))
        errors = int(result.detail_errors_by_kind.get(kind, 0))
        if imported + errors != expected:
            failures.append(
                f"{kind}: inventory={expected}, rich={imported}, errors={errors}"
            )
    if failures:
        raise MCPError(
            "MCP rich-detail accounting does not cover the populated inventory: "
            + "; ".join(failures)
        )


def import_details(
    self: core.MCPLocalSnapshotCompiler,
    capture: core.MCPSnapshotCapture,
    result: core.MCPCompileResult,
    *,
    progress: Callable[[str], None] | None = None,
) -> None:
    """Compile and retain every source-granular MCP rich record.

    ``entity_details`` remains the one-row canonical UI projection. The
    ``mcp_detail_records`` table preserves every upstream namespace/external-ID
    record, including many-to-one canonical mappings such as duplicate zone IDs.
    """
    _ensure_detail_record_schema(self.db)

    bridge = Path(core.__file__).resolve().parents[2] / "tools" / "mcp_local_detail_bridge.mjs"
    if not bridge.is_file():
        result.detail_bridge_missing_systems = list(core.SYSTEM_KIND_MAP)
        raise MCPError(
            f"Rich-detail compiler is required but missing: {bridge}. "
            "Use --skip-mcp-details only for an intentional inventory-only build."
        )

    bridge_hash = hashlib.sha256(bridge.read_bytes()).hexdigest()
    detail_digest = hashlib.sha256(
        (
            hashlib.sha256(capture.raw_json.encode("utf-8")).hexdigest()
            + "|"
            + capture.mcp_commit
            + "|"
            + bridge_hash
            + "|"
            + MCP_DETAIL_RECORD_SCHEMA_VERSION
        ).encode("utf-8")
    ).hexdigest()

    previous = self.db.conn.execute(
        "SELECT id, sha256 FROM source_pages WHERE url=?",
        (core.MCP_DETAIL_SOURCE_URL,),
    ).fetchone()
    if previous is not None and str(previous["sha256"]) == detail_digest:
        source_id = int(previous["id"])
        counts = _stored_record_counts(self.db, source_id)
        if counts:
            result.detail_source_page_id = source_id
            result.details_unchanged = True
            result.detail_imported_by_kind = counts
            result.detail_errors_by_kind = {
                str(k): int(v)
                for k, v in _load_json_meta(self.db, "eq_mcp_detail_errors", {}).items()
            }
            result.detail_bridge_missing_systems = [
                str(value)
                for value in _load_json_meta(
                    self.db, "eq_mcp_detail_missing_systems", []
                )
            ]
            self._validate_detail_result(capture, result)
            _validate_inventory_accounting(capture, result)
            return

    version_parts = [
        part for part in (capture.mcp_version, capture.mcp_commit[:12]) if part
    ]
    source_version = " @ ".join(version_parts)
    manifest = {
        "snapshot_timestamp": result.snapshot_timestamp,
        "mcp_version": capture.mcp_version,
        "mcp_commit": capture.mcp_commit,
        "bridge_sha256": bridge_hash,
        "detail_record_schema_version": MCP_DETAIL_RECORD_SCHEMA_VERSION,
        "systems": sorted(core.SYSTEM_KIND_MAP),
    }

    status = mcp_status(capture.mcp_path)
    if not status.ready:
        raise MCPError(status.summary())
    env = os.environ.copy()
    env["EQ_GAME_PATH"] = str(capture.eq_path)
    proc = subprocess.Popen(
        [status.node or "node", str(bridge), str(capture.mcp_path), "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(json.dumps(capture.snapshot, ensure_ascii=False))
    proc.stdin.close()

    with self.db.batch():
        detail_source_id = self.db.upsert_source_page(
            url=core.MCP_DETAIL_SOURCE_URL,
            title="EverQuest structured local records via everquest1-mcp",
            entity_type="multi",
            sha256=detail_digest,
            plain_text=json.dumps(manifest, ensure_ascii=False, indent=2),
            raw_html="",
            source_name="EverQuest Client via everquest1-mcp",
            source_kind="mcp_local_details",
            source_key=core.MCP_DETAIL_SOURCE_KEY,
            source_version=source_version,
            local_path=str(capture.eq_path),
            fetched_at=result.snapshot_timestamp or None,
        )
        result.detail_source_page_id = detail_source_id

        # The source-page URL is stable across builds. Rebuild this source atomically
        # so removed upstream records cannot survive as stale detail rows.
        self.db.conn.execute(
            "DELETE FROM mcp_detail_records WHERE source_page_id=?",
            (detail_source_id,),
        )
        self.db.conn.execute(
            "DELETE FROM entity_details WHERE source_page_id=?",
            (detail_source_id,),
        )

        canonical_written: set[int] = set()

        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = str(message.get("type") or "")
            system = str(message.get("system") or "")
            kind = str(
                message.get("kind")
                or core.SYSTEM_KIND_MAP.get(system)
                or "unknown"
            )

            if msg_type == "system_start":
                if progress:
                    progress(
                        f"MCP rich details: {kind} "
                        f"({int(message.get('total') or 0):,} records)…"
                    )
                continue
            if msg_type == "system_done":
                if progress:
                    progress(
                        f"MCP rich details: {kind} complete "
                        f"({int(message.get('imported') or 0):,} imported, "
                        f"{int(message.get('errors') or 0):,} getter errors)"
                    )
                continue
            if msg_type == "system_missing":
                if system and system not in result.detail_bridge_missing_systems:
                    result.detail_bridge_missing_systems.append(system)
                continue
            if msg_type == "record_error":
                result.detail_errors_by_kind[kind] = (
                    result.detail_errors_by_kind.get(kind, 0) + 1
                )
                continue
            if msg_type != "record":
                continue

            expected_kind = core.SYSTEM_KIND_MAP.get(system)
            external_id = str(message.get("external_id") or "")
            record = message.get("record")
            if not expected_kind or kind != expected_kind or not external_id:
                result.detail_errors_by_kind[kind] = (
                    result.detail_errors_by_kind.get(kind, 0) + 1
                )
                continue

            entity_id = self._detail_entity_id(system, external_id)
            if entity_id is None:
                result.detail_errors_by_kind[kind] = (
                    result.detail_errors_by_kind.get(kind, 0) + 1
                )
                continue

            detail_json, detail_text = core._detail_storage_payload(record)
            _persist_detail_record(
                self.db,
                source_page_id=detail_source_id,
                system=system,
                kind=kind,
                external_id=external_id,
                entity_id=entity_id,
                name=str(message.get("name") or ""),
                getter=str(message.get("getter") or ""),
                detail_text=detail_text,
                detail_json=detail_json,
            )

            # Existing renderers intentionally consume one canonical detail row. Keep
            # the first deterministic source record for that canonical entity while
            # the source-record table retains all many-to-one variants.
            if entity_id not in canonical_written:
                self.db.upsert_entity_detail(
                    entity_id,
                    source_page_id=detail_source_id,
                    detail_format="mcp-json",
                    detail_text=detail_text,
                    detail_json=detail_json,
                )
                canonical_written.add(entity_id)

            result.detail_imported_by_kind[kind] = (
                result.detail_imported_by_kind.get(kind, 0) + 1
            )

        return_code = proc.wait()
        if return_code != 0:
            stderr = proc.stderr.read().strip() if proc.stderr is not None else ""
            raise MCPError(
                "Rich-detail compiler failed"
                + (f":\n{stderr}" if stderr else f" with exit code {return_code}.")
            )

        self._validate_detail_result(capture, result)
        _validate_inventory_accounting(capture, result)

        canonical_counts = _stored_canonical_counts(self.db, detail_source_id)
        self.db.set_meta("eq_mcp_detail_last_compile", result.snapshot_timestamp)
        self.db.set_meta(
            "eq_mcp_detail_counts",
            json.dumps(result.detail_imported_by_kind, sort_keys=True),
        )
        self.db.set_meta(
            "eq_mcp_detail_canonical_counts",
            json.dumps(canonical_counts, sort_keys=True),
        )
        self.db.set_meta(
            "eq_mcp_detail_errors",
            json.dumps(result.detail_errors_by_kind, sort_keys=True),
        )
        self.db.set_meta(
            "eq_mcp_detail_missing_systems",
            json.dumps(sorted(result.detail_bridge_missing_systems)),
        )

    if progress:
        canonical_total = sum(
            _stored_canonical_counts(self.db, result.detail_source_page_id).values()
        )
        progress(
            f"MCP rich details compiled: {result.total_details:,} source records "
            f"across {canonical_total:,} canonical entities."
        )
