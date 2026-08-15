from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys


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

        inventory_total = int(
            conn.execute(
                "SELECT COUNT(DISTINCT entity_id) FROM entity_external_ids "
                "WHERE namespace LIKE 'eqmcp:%'"
            ).fetchone()[0]
        )
        spell_inventory = int(
            conn.execute(
                "SELECT COUNT(DISTINCT entity_id) FROM entity_external_ids "
                "WHERE namespace='eqmcp:spells'"
            ).fetchone()[0]
        )

        detail_total = 0
        detail_by_kind: dict[str, int] = {}
        spell_details = 0
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
            detail_by_kind = {str(row["kind"]): int(row["n"]) for row in rows}
            detail_total = sum(detail_by_kind.values())
            spell_details = int(detail_by_kind.get("spell", 0))

        missing_systems = _json_meta(conn, "eq_mcp_detail_missing_systems", [])
        detail_errors = _json_meta(conn, "eq_mcp_detail_errors", {})
        detail_counts_meta = _json_meta(conn, "eq_mcp_detail_counts", {})

        lines = [
            f"MCP knowledge audit: {Path(path).expanduser().resolve()}",
            f"  inventory source: {'present' if inventory_source is not None else 'MISSING'}",
            f"  inventory entities: {inventory_total:,}",
            f"  spell inventory: {spell_inventory:,}",
            f"  rich-detail source: {'present' if detail_source is not None else 'MISSING'}",
            f"  rich-detail records: {detail_total:,}",
            f"  rich spell records: {spell_details:,}",
        ]
        if detail_by_kind:
            lines.append(
                "  rich-detail kinds: "
                + ", ".join(f"{kind}={count:,}" for kind, count in sorted(detail_by_kind.items()))
            )
        if detail_errors:
            lines.append(
                "  getter errors: "
                + ", ".join(
                    f"{kind}={int(count):,}"
                    for kind, count in sorted(detail_errors.items())
                    if int(count)
                )
            )
        if missing_systems:
            lines.append("  missing detail systems: " + ", ".join(map(str, missing_systems)))

        errors: list[str] = []
        if inventory_source is None:
            errors.append("MCP inventory source is missing")
        if inventory_total <= 0:
            errors.append("MCP inventory contains no canonical entity links")

        if require_details:
            if detail_source is None:
                errors.append("MCP rich-detail source is missing")
            if detail_total <= 0:
                errors.append("MCP rich-detail layer contains no records")
            if spell_inventory > 0 and spell_details <= 0:
                errors.append("spell inventory is populated but rich spell details are missing")
            if missing_systems:
                errors.append(
                    "required MCP rich-detail systems are unavailable: "
                    + ", ".join(map(str, missing_systems))
                )
            if detail_counts_meta and detail_by_kind:
                normalized_meta = {str(k): int(v) for k, v in detail_counts_meta.items()}
                if normalized_meta != detail_by_kind:
                    errors.append("MCP rich-detail count metadata does not match persisted rows")

        return lines, errors
    finally:
        conn.close()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Audit MCP inventory and structured rich-detail persistence in an EverQuestie DB."
    )
    p.add_argument("database", help="Working or finalized EverQuestie SQLite database")
    p.add_argument(
        "--require-details",
        action="store_true",
        help="Fail unless the structured MCP rich-detail layer is present and non-empty",
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
