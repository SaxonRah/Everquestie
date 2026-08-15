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

from eqquest.zone_identity_audit import ZoneIdentityAudit, zone_identity_audit_text


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
            "Audit exact-name canonical zone identity collisions in an EverQuestie "
            "knowledge DB. The database is opened read-only and no identities are merged."
        )
    )
    parser.add_argument("database", help="Builder or finalized EverQuestie SQLite knowledge DB")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--examples",
        type=int,
        default=40,
        help="Maximum duplicate groups to include (default: 40)",
    )
    args = parser.parse_args(argv)

    conn = open_read_only(args.database)
    try:
        db = SimpleNamespace(conn=conn)
        limit = max(0, args.examples)
        if args.json:
            payload = ZoneIdentityAudit(db).summary(duplicate_example_limit=limit).as_dict()
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(zone_identity_audit_text(db, duplicate_example_limit=limit))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
