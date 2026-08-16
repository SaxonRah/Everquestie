from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.profile_lifecycle_audit import (
    profile_lifecycle_audit,
    profile_lifecycle_audit_text,
)


def open_read_only(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit explicit entity expansion/era evidence already compiled into an "
            "EverQuestie SQLite knowledge database. The DB is opened read-only and "
            "immutable; no source folders, MCP process, or network access is used."
        )
    )
    parser.add_argument("database", help="Builder or finalized EverQuestie SQLite knowledge DB")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    parser.add_argument(
        "--output",
        help=(
            "Write the selected report directly as UTF-8 text instead of stdout. "
            "Useful for deterministic Windows build artifacts without shell encoding differences."
        ),
    )
    args = parser.parse_args(argv)

    conn = open_read_only(args.database)
    try:
        db = SimpleNamespace(conn=conn)
        if args.json:
            payload = json.dumps(
                profile_lifecycle_audit(db).as_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        else:
            payload = profile_lifecycle_audit_text(db)
    finally:
        conn.close()

    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
