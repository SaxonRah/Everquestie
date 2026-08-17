from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.allakhazam_temporary_recovery import (
    recover_allakhazam_temporary_pages,
    temporary_recovery_text,
)
from eqquest.db import Database


def _require_builder_database(path: str | Path) -> Path:
    database = Path(path).expanduser().resolve()
    if not database.is_file():
        raise ValueError(
            "Recovery requires an existing builder/working database; "
            f"file does not exist: {database}"
        )

    conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not {"entities", "source_pages"}.issubset(tables):
            raise ValueError(
                "Recovery target is not an EverQuestie builder/working database "
                "with entities + source_pages tables"
            )
        role = ""
        if "app_meta" in tables:
            row = conn.execute(
                "SELECT value FROM app_meta WHERE key='database_role'"
            ).fetchone()
            role = str(row[0]) if row is not None else ""
        if role == "knowledge_snapshot":
            raise ValueError(
                "Recovery refuses finalized immutable knowledge snapshots; "
                "run it only against a builder/working database"
            )
    finally:
        conn.close()
    return database


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Explicitly recover stable likely-complete structured Allakhazam HTTrack "
            ".tmp pages into an existing EverQuestie builder database. This is a "
            "builder/developer action; normal mirror import and packaged runtime still "
            "ignore all temporary pages."
        )
    )
    p.add_argument("mirror", help="Local everquest.allakhazam.com HTTrack mirror root")
    p.add_argument(
        "--database",
        required=True,
        help="Existing writable EverQuestie builder/working SQLite database",
    )
    p.add_argument(
        "--source-version",
        default="",
        help="Optional capture/version label applied to recovered Allakhazam source pages",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable recovery summary JSON",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        database = _require_builder_database(args.database)
        mirror = Path(args.mirror).expanduser().resolve()
        if not mirror.is_dir():
            raise ValueError(f"Allakhazam mirror directory does not exist: {mirror}")
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    db = Database(database)
    try:
        result = recover_allakhazam_temporary_pages(
            db,
            mirror,
            source_version=args.source_version,
        )
    finally:
        db.close()

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(temporary_recovery_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
