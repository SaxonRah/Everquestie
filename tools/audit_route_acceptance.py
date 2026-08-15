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

from eqquest.route_acceptance import (
    DEFAULT_ROUTE_ACCEPTANCE_CASES,
    evaluate_route_acceptance,
    route_acceptance_text,
)


def open_read_only(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate exact canonical zone-to-zone route acceptance against an EverQuestie "
            "SQLite knowledge database. The database is opened read-only; no map folders, "
            "mirrors, providers, or network sources are scanned."
        )
    )
    parser.add_argument("database", help="Builder or finalized EverQuestie SQLite knowledge DB")
    parser.add_argument(
        "--route",
        nargs=2,
        action="append",
        metavar=("SOURCE", "DESTINATION"),
        help=(
            "Route pair to audit. Repeat for multiple cases. If omitted, the built-in "
            "cross-world acceptance suite is used."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    parser.add_argument(
        "--full-paths",
        action="store_true",
        help="Print every zone in successful long routes instead of a compact path preview",
    )
    parser.add_argument(
        "--fail-unreachable",
        action="store_true",
        help="Return exit code 2 when any requested route is unresolved, blocked, or disconnected",
    )
    args = parser.parse_args(argv)

    cases = tuple(tuple(pair) for pair in args.route) if args.route else DEFAULT_ROUTE_ACCEPTANCE_CASES
    conn = open_read_only(args.database)
    try:
        # ZoneTravelCatalog sees knowledge_writable=False and therefore never attempts
        # schema creation against the immutable/read-only snapshot.
        db = SimpleNamespace(conn=conn, knowledge_writable=False)
        summary = evaluate_route_acceptance(db, cases)
        if args.json:
            print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(route_acceptance_text(summary, full_paths=args.full_paths))
    finally:
        conn.close()

    if args.fail_unreachable and summary.failed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
