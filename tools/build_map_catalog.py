from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicitly build or refresh a portable EverQuestie map catalog."
    )
    parser.add_argument("--db", required=True, help="EverQuestie knowledge SQLite database")
    parser.add_argument("--maps", required=True, help="Good/Brewall/EverQuest map-pack root")
    parser.add_argument(
        "--source-name",
        required=True,
        help="Stable catalog source name, e.g. Goods or Brewall",
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

        catalog = MapCatalog(db)
        stats = catalog.index_root(
            maps,
            source_name=args.source_name,
            source_version=args.source_version,
            progress=progress,
        )
        zone_stats = ZoneMapCatalog(db).reconcile(source_name=args.source_name)
        # Canonical zone backfill can disambiguate otherwise-identical NPC/map
        # labels, so run the label linker once more after zone identity is known.
        label_links = catalog.reconcile_all(force=bool(zone_stats.changed), progress=progress)
        travel_stats = ZoneTravelCatalog(db).reconcile_from_maps(source_name=args.source_name)
        print(
            f"catalog ready: {stats.base_maps} base maps, {stats.labels} labels, "
            f"{label_links['linked']} linked, {label_links['ambiguous']} ambiguous, "
            f"{label_links['unresolved']} unresolved"
        )
        print(
            "zone/map identity: "
            f"{zone_stats.linked}/{zone_stats.maps} linked, "
            f"{zone_stats.ambiguous} ambiguous, {zone_stats.unresolved} unresolved"
        )
        print(
            "zone travel: "
            f"{travel_stats.linked}/{travel_stats.candidates} linked, "
            f"{travel_stats.ambiguous} ambiguous, {travel_stats.unresolved} unresolved"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
