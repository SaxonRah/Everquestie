from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys


SYSTEM_KIND_MAP: dict[str, str] = {
    "spells": "spell",
    "zones": "zone",
    "factions": "faction",
    "achievements": "achievement",
    "aaAbilities": "aa",
    "overseerMinions": "overseer_agent",
    "overseerQuests": "overseer_quest",
    "mercenaries": "mercenary",
    "tributes": "tribute",
    "lore": "lore",
    "combatAbilities": "combat_ability",
}


def _connect(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row is not None else default


def _json_meta(conn: sqlite3.Connection, key: str, default):
    raw = _meta(conn, key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _inventory_identity_counts(conn: sqlite3.Connection) -> tuple[dict[str, int], int]:
    rows = conn.execute(
        """
        SELECT namespace, COUNT(*) AS n
        FROM entity_external_ids
        WHERE namespace LIKE 'eqmcp:%'
        GROUP BY namespace
        ORDER BY namespace
        """
    ).fetchall()
    by_kind: dict[str, int] = {}
    total = 0
    for row in rows:
        namespace = str(row["namespace"] or "")
        system = namespace.split(":", 1)[-1]
        kind = SYSTEM_KIND_MAP.get(system, system)
        count = int(row["n"] or 0)
        by_kind[kind] = by_kind.get(kind, 0) + count
        total += count
    return by_kind, total


def audit(path: str | Path, *, require_details: bool = False) -> tuple[list[str], list[str]]:
    conn = _connect(path)
    try:
        inventory_source = conn.execute(
            """
            SELECT id,source_name,source_kind,source_version
            FROM source_pages
            WHERE source_kind='mcp_local_snapshot'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        detail_source = conn.execute(
            """
            SELECT id,source_name,source_kind,source_version
            FROM source_pages
            WHERE source_kind='mcp_local_details'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()

        inventory_by_kind, inventory_identity_total = _inventory_identity_counts(conn)
        inventory_entity_total = int(
            conn.execute(
                "SELECT COUNT(DISTINCT entity_id) FROM entity_external_ids "
                "WHERE namespace LIKE 'eqmcp:%'"
            ).fetchone()[0]
        )
        spell_inventory = int(inventory_by_kind.get("spell", 0))

        detail_record_table = _table_exists(conn, "mcp_detail_records")
        detail_record_total = 0
        detail_record_by_kind: dict[str, int] = {}
        detail_record_entities = 0
        spell_detail_records = 0
        if detail_source is not None and detail_record_table:
            source_id = int(detail_source["id"])
            rows = conn.execute(
                """
                SELECT kind,COUNT(*) AS n,COUNT(DISTINCT entity_id) AS entity_n
                FROM mcp_detail_records
                WHERE source_page_id=?
                GROUP BY kind ORDER BY kind
                """,
                (source_id,),
            ).fetchall()
            detail_record_by_kind = {
                str(row["kind"]): int(row["n"]) for row in rows
            }
            detail_record_total = sum(detail_record_by_kind.values())
            detail_record_entities = int(
                conn.execute(
                    "SELECT COUNT(DISTINCT entity_id) FROM mcp_detail_records "
                    "WHERE source_page_id=?",
                    (source_id,),
                ).fetchone()[0]
            )
            spell_detail_records = int(detail_record_by_kind.get("spell", 0))

        canonical_detail_total = 0
        canonical_detail_by_kind: dict[str, int] = {}
        if detail_source is not None:
            source_id = int(detail_source["id"])
            rows = conn.execute(
                """
                SELECT e.kind,COUNT(*) AS n
                FROM entity_details d
                JOIN entities e ON e.id=d.entity_id
                WHERE d.source_page_id=?
                GROUP BY e.kind ORDER BY e.kind
                """,
                (source_id,),
            ).fetchall()
            canonical_detail_by_kind = {
                str(row["kind"]): int(row["n"]) for row in rows
            }
            canonical_detail_total = sum(canonical_detail_by_kind.values())

        missing_systems = _json_meta(conn, "eq_mcp_detail_missing_systems", [])
        detail_errors = {
            str(k): int(v)
            for k, v in _json_meta(conn, "eq_mcp_detail_errors", {}).items()
        }
        detail_counts_meta = {
            str(k): int(v)
            for k, v in _json_meta(conn, "eq_mcp_detail_counts", {}).items()
        }

        lines = [
            f"MCP knowledge audit: {Path(path).expanduser().resolve()}",
            f"  inventory source: {'present' if inventory_source is not None else 'MISSING'}",
            f"  inventory identities: {inventory_identity_total:,}",
            f"  canonical inventory entities: {inventory_entity_total:,}",
            f"  spell inventory identities: {spell_inventory:,}",
            f"  rich-detail source: {'present' if detail_source is not None else 'MISSING'}",
            f"  rich source-record table: {'present' if detail_record_table else 'MISSING'}",
            f"  rich source records: {detail_record_total:,}",
            f"  canonical rich-detail entities: {detail_record_entities:,}",
            f"  canonical UI detail rows: {canonical_detail_total:,}",
            f"  rich spell records: {spell_detail_records:,}",
        ]
        if inventory_by_kind:
            lines.append(
                "  inventory kinds: "
                + ", ".join(
                    f"{kind}={count:,}"
                    for kind, count in sorted(inventory_by_kind.items())
                )
            )
        if detail_record_by_kind:
            lines.append(
                "  rich-detail kinds: "
                + ", ".join(
                    f"{kind}={count:,}"
                    for kind, count in sorted(detail_record_by_kind.items())
                )
            )
        if canonical_detail_by_kind:
            collapsed = {
                kind: int(detail_record_by_kind.get(kind, 0)) - count
                for kind, count in canonical_detail_by_kind.items()
                if int(detail_record_by_kind.get(kind, 0)) > count
            }
            if collapsed:
                lines.append(
                    "  canonical many-to-one detail variants: "
                    + ", ".join(
                        f"{kind}=+{count:,}"
                        for kind, count in sorted(collapsed.items())
                    )
                )
        if detail_errors:
            nonzero_errors = {
                kind: count for kind, count in detail_errors.items() if count
            }
            if nonzero_errors:
                lines.append(
                    "  getter errors: "
                    + ", ".join(
                        f"{kind}={count:,}"
                        for kind, count in sorted(nonzero_errors.items())
                    )
                )
        if missing_systems:
            lines.append("  missing detail systems: " + ", ".join(map(str, missing_systems)))

        errors: list[str] = []
        if inventory_source is None:
            errors.append("MCP inventory source is missing")
        if inventory_identity_total <= 0:
            errors.append("MCP inventory contains no source identities")

        if require_details:
            if detail_source is None:
                errors.append("MCP rich-detail source is missing")
            if not detail_record_table:
                errors.append("MCP source-granular rich-detail record table is missing")
            if detail_record_total <= 0:
                errors.append("MCP rich-detail layer contains no source records")
            if spell_inventory > 0 and spell_detail_records <= 0:
                errors.append("spell inventory is populated but rich spell details are missing")
            if missing_systems:
                errors.append(
                    "required MCP rich-detail systems are unavailable: "
                    + ", ".join(map(str, missing_systems))
                )
            if detail_counts_meta and detail_record_by_kind:
                if detail_counts_meta != detail_record_by_kind:
                    errors.append(
                        "MCP rich-detail count metadata does not match persisted source records"
                    )

            accounting_failures: list[str] = []
            for kind, inventory_count in sorted(inventory_by_kind.items()):
                rich_count = int(detail_record_by_kind.get(kind, 0))
                getter_errors = int(detail_errors.get(kind, 0))
                if rich_count + getter_errors != int(inventory_count):
                    accounting_failures.append(
                        f"{kind}: inventory={inventory_count}, "
                        f"rich={rich_count}, errors={getter_errors}"
                    )
            if accounting_failures:
                errors.append(
                    "MCP rich-detail accounting does not cover inventory identities: "
                    + "; ".join(accounting_failures)
                )

        return lines, errors
    finally:
        conn.close()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Audit MCP source identities, source-granular rich records, and canonical "
            "detail projection in an EverQuestie DB."
        )
    )
    p.add_argument("database", help="Working or finalized EverQuestie SQLite database")
    p.add_argument(
        "--require-details",
        action="store_true",
        help="Fail unless the structured MCP rich-detail layer is present and complete",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        lines, errors = audit(args.database, require_details=bool(args.require_details))
    except (FileNotFoundError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("\n".join(lines))
    if errors:
        print("MCP knowledge audit FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2
    print("MCP knowledge audit: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
