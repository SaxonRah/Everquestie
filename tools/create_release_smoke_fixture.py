from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.db import Database
from eqquest.zone_identity import ZoneIdentityIndex


# Keep this fixture intentionally explicit. These are the canonical identities required
# by the repository-owned reviewed alias/travel manifests used by the official release
# staging step. If that reviewed corpus expands, Windows packaging CI should fail until
# this list is consciously updated to match the new release contract.
CLIENT_ZONES: tuple[tuple[str, str], ...] = (
    ("The Hole", "39"),
    ("The Greater Faydark", "54"),
    ("Paineel", "75"),
    ("The Plane of Knowledge", "202"),
    ("West Freeport", "383"),
    ("Toxxulia Forest", "414"),
    ("Labyrinth of Spite", "549"),
)

PLAIN_ZONES: tuple[str, ...] = (
    "Arcstone, Shattered Isles",
    "Ruined Relic",
    "The Vortex",
)

REQUIRED_QUERIES: tuple[str, ...] = (
    "The Hole",
    "Greater Faydark",
    "Paineel",
    "The Plane of Knowledge",
    "West Freeport",
    "Toxxulia Forest",
    "Labyrinth of Spite",
    "Arcstone, Shattered Isles",
    "Ruined Relic",
    "The Vortex",
)


def _remove_sqlite_family(path: Path) -> None:
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
    ):
        candidate.unlink(missing_ok=True)


def create_release_smoke_fixture(output: str | Path, *, overwrite: bool = False) -> Path:
    """Create the smallest builder DB that can exercise official reviewed release staging.

    This is CI/package plumbing only; it is not gameplay content and does not attempt to
    satisfy route acceptance. The official packaging smoke intentionally skips the route
    gate while still compiling the real checked-in reviewed alias/travel manifests.
    """
    destination = Path(output).expanduser().resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    temp = destination.with_name(destination.name + ".building")
    _remove_sqlite_family(temp)
    try:
        db = Database(temp)
        try:
            for name, eq_zone_id in CLIENT_ZONES:
                db.upsert_entity(
                    kind="zone",
                    name=name,
                    external_id=eq_zone_id,
                    external_namespace="eqclient:zone",
                    merge_by_name=False,
                    data={"authoritative_identity_source": "EverQuest Client"},
                )
            for name in PLAIN_ZONES:
                db.upsert_entity(kind="zone", name=name, merge_by_name=True)

            identities = ZoneIdentityIndex(db, include_map_bindings=True)
            unresolved = []
            for query in REQUIRED_QUERIES:
                resolution = identities.resolve(query)
                if resolution.status != "linked" or resolution.entity_id is None:
                    unresolved.append(f"{query!r} -> {resolution.status}")
            if unresolved:
                raise RuntimeError(
                    "release smoke fixture does not resolve required zone identities: "
                    + "; ".join(unresolved)
                )
            db.set_meta("release_smoke_fixture", "windows-packaging")
            db.conn.commit()
        finally:
            db.close()

        if destination.exists():
            destination.unlink()
        os.replace(temp, destination)
        return destination
    except Exception:
        _remove_sqlite_family(temp)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a minimal release-shaped EverQuestie builder DB for Windows packaging CI."
        )
    )
    parser.add_argument("--output", required=True, help="Destination working.sqlite3")
    parser.add_argument("--force", action="store_true", help="Replace an existing fixture")
    args = parser.parse_args(argv)

    path = create_release_smoke_fixture(args.output, overwrite=args.force)
    print(f"release packaging smoke fixture: {path}")
    print(f"client-backed zones: {len(CLIENT_ZONES)}")
    print(f"additional reviewed zones: {len(PLAIN_ZONES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
