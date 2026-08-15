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

from eqquest.travel_frontier import TravelFrontierAudit, travel_frontier_audit_text


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
            "Audit stored EverQuestie map labels for current travel-compiler coverage "
            "and conservative route-evidence frontier candidates. The SQLite database "
            "is opened read-only; no map folders, mirrors or runtime files are scanned."
        )
    )
    parser.add_argument("database", help="Builder or finalized EverQuestie SQLite knowledge DB")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=30,
        help="Maximum frontier examples to include (default: 30)",
    )
    args = parser.parse_args(argv)

    conn = open_read_only(args.database)
    try:
        db = SimpleNamespace(conn=conn)
        if args.json:
            payload = TravelFrontierAudit(db).summary(example_limit=max(0, args.examples)).as_dict()
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(travel_frontier_audit_text(db, example_limit=max(0, args.examples)))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
