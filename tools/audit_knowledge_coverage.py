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

from eqquest.knowledge_coverage import (
    knowledge_normalization_coverage,
    normalization_coverage_text,
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
            "Report how persisted source pages have been normalized into EverQuestie's "
            "canonical knowledge graph. The database is opened read-only and mirror "
            "folders are never scanned."
        )
    )
    parser.add_argument("database", help="Builder or finalized EverQuestie SQLite knowledge DB")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the human-readable report",
    )
    args = parser.parse_args(argv)

    conn = open_read_only(args.database)
    try:
        db = SimpleNamespace(conn=conn)
        if args.json:
            report = knowledge_normalization_coverage(db)
            payload = {
                "source_pages": report.source_pages,
                "normalized_pages": report.normalized_pages,
                "relationships": report.relationships,
                "providers": [provider.as_dict() for provider in report.providers],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(normalization_coverage_text(db))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
