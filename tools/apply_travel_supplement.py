from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.db import Database
from eqquest.travel_supplement import TravelSupplementImporter


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Compile an explicit source-backed travel supplement into an existing "
            "EverQuestie builder/working knowledge database."
        )
    )
    p.add_argument(
        "database",
        help="Existing writable builder/working EverQuestie SQLite database",
    )
    p.add_argument(
        "manifest",
        help="Versioned travel supplement JSON manifest",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable build statistics",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    database = Path(args.database).expanduser().resolve()
    manifest = Path(args.manifest).expanduser().resolve()
    if not database.is_file():
        raise SystemExit(f"Builder database not found: {database}")
    if not manifest.is_file():
        raise SystemExit(f"Travel supplement manifest not found: {manifest}")

    db = Database(database)
    try:
        stats = TravelSupplementImporter(db).import_manifest(manifest)
    finally:
        db.close()

    payload = {
        "source_name": stats.source_name,
        "source_version": stats.source_version,
        "edges": stats.edges,
        "bidirectional_edges": stats.bidirectional_edges,
        "requirements": stats.requirements,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "travel supplement: "
            f"{stats.source_name} {stats.source_version}; "
            f"edges={stats.edges}, "
            f"bidirectional={stats.bidirectional_edges}, "
            f"requirements={stats.requirements}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
