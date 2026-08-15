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

from eqquest.provider_travel_frontier import (
    ProviderTravelFrontierAudit,
    provider_travel_frontier_text,
)


# The CLI default follows the current-live route-acceptance frontier. Historical/retired
# identities can still be diagnosed explicitly with --zone.
DEFAULT_CURRENT_LIVE_PROVIDER_TRAVEL_FRONTIER_ZONES: tuple[str, ...] = (
    "Labyrinth of Spite",
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
            "Explain stored provider Connected Zones evidence at EverQuestie's canonical "
            "travel-compiler boundary. The SQLite database is opened read-only."
        )
    )
    parser.add_argument("database", help="Builder or finalized EverQuestie SQLite knowledge DB")
    parser.add_argument(
        "--zone",
        action="append",
        dest="zones",
        help=(
            "Canonical zone to diagnose; repeat for multiple zones. Defaults to the "
            "remaining current-live route-acceptance provider frontier."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)

    zones = tuple(args.zones or DEFAULT_CURRENT_LIVE_PROVIDER_TRAVEL_FRONTIER_ZONES)
    conn = open_read_only(args.database)
    try:
        db = SimpleNamespace(conn=conn)
        if args.json:
            payload = ProviderTravelFrontierAudit(db).summary(zones).as_dict()
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print(provider_travel_frontier_text(db, zones))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
