from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.map_catalog import MAP_CATALOG_VERSION


_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _connect(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _catalog_version(conn: sqlite3.Connection) -> str:
    if not _table_exists(conn, "app_meta"):
        return ""
    row = conn.execute(
        "SELECT value FROM app_meta WHERE key='map_catalog_version'"
    ).fetchone()
    return str(row["value"] or "").strip() if row is not None else ""


def _portable_source_key(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    if candidate.startswith(("/", "\\")) or _DRIVE_PATH_RE.match(candidate):
        return False
    return "://" not in candidate


def audit(
    path: str | Path,
    *,
    required_sources: tuple[str, ...] = (),
    require_versioned_sources: bool = False,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    errors: list[str] = []
    payload: dict[str, Any] = {
        "database": str(resolved),
        "status": "error",
        "catalog_version": "",
        "expected_catalog_version": MAP_CATALOG_VERSION,
        "required_sources": list(required_sources),
        "require_versioned_sources": bool(require_versioned_sources),
        "totals": {
            "sources": 0,
            "files": 0,
            "base_maps": 0,
            "labels": 0,
            "linked_labels": 0,
            "ambiguous_labels": 0,
            "unresolved_labels": 0,
        },
        "sources": [],
        "errors": errors,
    }

    conn = _connect(resolved)
    try:
        missing_tables = [
            table
            for table in ("app_meta", "map_sources", "map_labels")
            if not _table_exists(conn, table)
        ]
        if missing_tables:
            errors.append(
                "map catalog schema is incomplete; missing "
                + ", ".join(missing_tables)
            )
            return payload

        catalog_version = _catalog_version(conn)
        payload["catalog_version"] = catalog_version
        if catalog_version != MAP_CATALOG_VERSION:
            errors.append(
                f"map_catalog_version is {catalog_version!r}; "
                f"expected {MAP_CATALOG_VERSION!r}"
            )

        rows = conn.execute(
            """
            SELECT
                source_name,
                COUNT(*) AS file_count,
                SUM(CASE WHEN layer=0 THEN 1 ELSE 0 END) AS base_map_count,
                SUM(CASE WHEN TRIM(source_version)<>'' THEN 1 ELSE 0 END)
                    AS versioned_file_count,
                COUNT(DISTINCT source_version) AS version_count,
                SUM(CASE WHEN root=source_name THEN 0 ELSE 1 END)
                    AS nonportable_root_count,
                SUM(
                    CASE
                        WHEN TRIM(source_key)='' THEN 1
                        WHEN source_key LIKE '/%' THEN 1
                        WHEN source_key LIKE '\\%' THEN 1
                        WHEN source_key LIKE '%://%' THEN 1
                        ELSE 0
                    END
                ) AS obviously_nonportable_key_count,
                SUM(CASE WHEN path LIKE 'mapcatalog://%' THEN 0 ELSE 1 END)
                    AS nonportable_path_count
            FROM map_sources
            GROUP BY source_name
            ORDER BY source_name COLLATE NOCASE
            """
        ).fetchall()

        source_names: set[str] = set()
        source_payloads: list[dict[str, Any]] = []
        for row in rows:
            source_name = str(row["source_name"] or "").strip()
            source_names.add(source_name)
            file_count = int(row["file_count"] or 0)
            base_map_count = int(row["base_map_count"] or 0)
            versioned_file_count = int(row["versioned_file_count"] or 0)
            versions = [
                str(version_row["source_version"] or "")
                for version_row in conn.execute(
                    """
                    SELECT DISTINCT source_version
                    FROM map_sources
                    WHERE source_name=?
                    ORDER BY source_version
                    """,
                    (source_name,),
                ).fetchall()
            ]
            label_counts = conn.execute(
                """
                SELECT
                    COUNT(*) AS labels,
                    SUM(CASE WHEN ml.link_status='linked' THEN 1 ELSE 0 END) AS linked,
                    SUM(CASE WHEN ml.link_status='ambiguous' THEN 1 ELSE 0 END) AS ambiguous,
                    SUM(CASE WHEN ml.link_status='unresolved' THEN 1 ELSE 0 END) AS unresolved
                FROM map_labels ml
                JOIN map_sources ms ON ms.id=ml.source_id
                WHERE ms.source_name=?
                """,
                (source_name,),
            ).fetchone()
            labels = int(label_counts["labels"] or 0)
            linked = int(label_counts["linked"] or 0)
            ambiguous = int(label_counts["ambiguous"] or 0)
            unresolved = int(label_counts["unresolved"] or 0)

            nonportable_keys = 0
            for key_row in conn.execute(
                "SELECT source_key FROM map_sources WHERE source_name=?",
                (source_name,),
            ):
                if not _portable_source_key(str(key_row["source_key"] or "")):
                    nonportable_keys += 1

            source_payload = {
                "source_name": source_name,
                "versions": versions,
                "files": file_count,
                "base_maps": base_map_count,
                "labels": labels,
                "linked_labels": linked,
                "ambiguous_labels": ambiguous,
                "unresolved_labels": unresolved,
                "portable": (
                    int(row["nonportable_root_count"] or 0) == 0
                    and int(row["nonportable_path_count"] or 0) == 0
                    and int(row["obviously_nonportable_key_count"] or 0) == 0
                    and nonportable_keys == 0
                ),
            }
            source_payloads.append(source_payload)

            if not source_name:
                errors.append("map catalog contains a source with an empty source_name")
            if file_count <= 0:
                errors.append(f"map source {source_name!r} contains no indexed files")
            if base_map_count <= 0:
                errors.append(f"map source {source_name!r} contains no base maps")
            if labels <= 0:
                errors.append(f"map source {source_name!r} contains no indexed labels")
            if require_versioned_sources and versioned_file_count != file_count:
                errors.append(
                    f"map source {source_name!r} has unversioned indexed files"
                )
            if int(row["version_count"] or 0) > 1:
                errors.append(
                    f"map source {source_name!r} contains multiple source versions: "
                    + ", ".join(repr(version) for version in versions)
                )
            if int(row["nonportable_root_count"] or 0):
                errors.append(
                    f"map source {source_name!r} retains builder-local root metadata"
                )
            if int(row["nonportable_path_count"] or 0):
                errors.append(
                    f"map source {source_name!r} contains non-portable catalog paths"
                )
            if int(row["obviously_nonportable_key_count"] or 0) or nonportable_keys:
                errors.append(
                    f"map source {source_name!r} contains non-portable source keys"
                )

        payload["sources"] = source_payloads

        for required in required_sources:
            if required not in source_names:
                errors.append(f"required map catalog source is missing: {required}")

        orphan_labels = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM map_labels ml
                LEFT JOIN map_sources ms ON ms.id=ml.source_id
                WHERE ms.id IS NULL
                """
            ).fetchone()[0]
        )
        if orphan_labels:
            errors.append(f"map catalog contains {orphan_labels} orphan label row(s)")

        duplicate_keys = conn.execute(
            """
            SELECT source_name,source_key,COUNT(*) AS n
            FROM map_sources
            GROUP BY source_name,source_key
            HAVING COUNT(*)<>1
            ORDER BY source_name,source_key
            """
        ).fetchall()
        if duplicate_keys:
            errors.append(
                f"map catalog contains {len(duplicate_keys)} duplicate source identity row(s)"
            )

        totals = conn.execute(
            """
            SELECT
                COUNT(DISTINCT source_name) AS sources,
                COUNT(*) AS files,
                SUM(CASE WHEN layer=0 THEN 1 ELSE 0 END) AS base_maps
            FROM map_sources
            """
        ).fetchone()
        label_totals = conn.execute(
            """
            SELECT
                COUNT(*) AS labels,
                SUM(CASE WHEN link_status='linked' THEN 1 ELSE 0 END) AS linked,
                SUM(CASE WHEN link_status='ambiguous' THEN 1 ELSE 0 END) AS ambiguous,
                SUM(CASE WHEN link_status='unresolved' THEN 1 ELSE 0 END) AS unresolved
            FROM map_labels
            """
        ).fetchone()
        payload["totals"] = {
            "sources": int(totals["sources"] or 0),
            "files": int(totals["files"] or 0),
            "base_maps": int(totals["base_maps"] or 0),
            "labels": int(label_totals["labels"] or 0),
            "linked_labels": int(label_totals["linked"] or 0),
            "ambiguous_labels": int(label_totals["ambiguous"] or 0),
            "unresolved_labels": int(label_totals["unresolved"] or 0),
        }
        if payload["totals"]["files"] <= 0:
            errors.append("map catalog contains no indexed files")
        if payload["totals"]["base_maps"] <= 0:
            errors.append("map catalog contains no base maps")
        if payload["totals"]["labels"] <= 0:
            errors.append("map catalog contains no indexed labels")
    finally:
        conn.close()

    payload["status"] = "ok" if not errors else "error"
    return payload


def _human_lines(payload: dict[str, Any]) -> list[str]:
    totals = payload["totals"]
    lines = [
        f"Map catalog audit: {payload['database']}",
        f"  catalog version: {payload['catalog_version'] or 'MISSING'} "
        f"(expected {payload['expected_catalog_version']})",
        f"  sources: {totals['sources']:,}",
        f"  indexed files: {totals['files']:,}",
        f"  base maps: {totals['base_maps']:,}",
        f"  labels: {totals['labels']:,}",
        (
            "  label links: "
            f"{totals['linked_labels']:,} linked, "
            f"{totals['ambiguous_labels']:,} ambiguous, "
            f"{totals['unresolved_labels']:,} unresolved"
        ),
    ]
    for source in payload["sources"]:
        version_text = ", ".join(source["versions"]) or "(unversioned)"
        lines.append(
            f"  {source['source_name']}: "
            f"{source['base_maps']:,} base maps / {source['files']:,} files / "
            f"{source['labels']:,} labels; version={version_text}; "
            f"portable={'yes' if source['portable'] else 'NO'}"
        )
    if payload["errors"]:
        lines.append("  errors:")
        lines.extend(f"    - {error}" for error in payload["errors"])
    else:
        lines.append("  status: OK")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only audit of the prebuilt portable map catalog stored in an "
            "EverQuestie knowledge database."
        )
    )
    parser.add_argument("database", help="EverQuestie knowledge SQLite database")
    parser.add_argument(
        "--require-source",
        action="append",
        default=[],
        help="Stable source_name that must be present; repeat for multiple sources",
    )
    parser.add_argument(
        "--require-versioned-sources",
        action="store_true",
        help="Fail when any indexed map file has an empty source_version",
    )
    parser.add_argument(
        "--output",
        help="Optional JSON report path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the audit result as JSON instead of human-readable text",
    )
    args = parser.parse_args()

    try:
        payload = audit(
            args.database,
            required_sources=tuple(args.require_source),
            require_versioned_sources=bool(args.require_versioned_sources),
        )
    except (FileNotFoundError, sqlite3.Error) as exc:
        print(f"Map catalog audit failed: {exc}", file=sys.stderr)
        return 2

    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("\n".join(_human_lines(payload)))

    return 0 if payload["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
