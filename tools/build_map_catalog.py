from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicitly build or refresh a portable EverQuestie map catalog."
    )
    parser.add_argument("--db", required=True, help="EverQuestie knowledge SQLite database")
    parser.add_argument("--maps", required=True, help="Good/Brewall/EverQuest map-pack root")
    parser.add_argument(
        "--source-name",
        required=True,
        help="Stable catalog source name, e.g. Brewall or Good",
    )
    parser.add_argument(
        "--source-version",
        default="",
        help="Optional map-pack version/date retained in catalog provenance",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    maps = Path(args.maps).expanduser().resolve()
    db = Database(db_path)
    try:
        def progress(stage: str, current: int, total: int, detail: str) -> None:
            print(f"[{stage}] {current}/{total} {detail}")

        stats = MapCatalog(db).index_root(
            maps,
            source_name=args.source_name,
            source_version=args.source_version,
            progress=progress,
        )
        print(
            f"catalog ready: {stats.base_maps} base maps, {stats.labels} labels, "
            f"{stats.linked} linked, {stats.ambiguous} ambiguous, {stats.unresolved} unresolved"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
