from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eqquest.activity_pathways import ActivityPathwayEngine
from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot


HOT_ZONE = "South Qeynos"
HOT_NPC = "Performance Rat"
HOT_ITEM = "Performance Token"
HOT_QUEST = "Performance Quest"


def _remove_sqlite_family(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        candidate.unlink(missing_ok=True)


def create_performance_fixture(
    working_db: str | Path,
    snapshot_db: str | Path,
    *,
    filler_entities: int = 50_000,
    aliases_per_entity: int = 2,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Create a release-shaped large synthetic corpus for performance smoke tests.

    The fixture deliberately contains a large entity/alias inventory plus one exact
    kill/loot/quest chain used by the runtime benchmark tool. It is developer test
    data only and must never be distributed as gameplay knowledge.
    """
    working = Path(working_db).expanduser().resolve()
    snapshot = Path(snapshot_db).expanduser().resolve()
    for path in (working, snapshot):
        if path.exists() and not overwrite:
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite:
            _remove_sqlite_family(path)

    db = Database(working)
    try:
        with db.batch():
            source_page_id = db.upsert_source_page(
                url="performance://synthetic/source",
                title="Synthetic performance source",
                entity_type="multi",
                sha256="synthetic-performance-source",
                plain_text=("Synthetic source excerpt. " + ("payload " * 10_000)),
                raw_html="<html><body>builder-only synthetic payload</body></html>",
                source_name="EverQuestie Performance Fixture",
                source_kind="synthetic_fixture",
                source_key="performance",
                source_version="1",
            )
            zone_id = db.upsert_entity(
                kind="zone",
                name=HOT_ZONE,
                external_id="1",
                external_namespace="eqclient:zone",
                merge_by_name=True,
                source_page_id=source_page_id,
            )
            npc_id = db.upsert_entity(
                kind="npc",
                name=HOT_NPC,
                external_id="npc:performance",
                source_page_id=source_page_id,
                zone=HOT_ZONE,
            )
            item_id = db.upsert_entity(
                kind="item",
                name=HOT_ITEM,
                external_id="item:performance",
                source_page_id=source_page_id,
            )
            quest_id = db.upsert_entity(
                kind="quest",
                name=HOT_QUEST,
                external_id="quest:performance",
                source_page_id=source_page_id,
                zone=HOT_ZONE,
            )
            db.add_alias(npc_id, "Perf Rat", source_page_id=source_page_id)
            db.add_alias(item_id, "Perf Token", source_page_id=source_page_id)
            db.add_quest_step(
                quest_id,
                1,
                f"Defeat {HOT_NPC}",
                zone=HOT_ZONE,
                match={"event": "kill", "npc_entity_id": npc_id, "count": 1},
                source_page_id=source_page_id,
            )
            db.add_quest_step(
                quest_id,
                2,
                f"Loot {HOT_ITEM}",
                match={"event": "loot", "item_entity_id": item_id, "count": 1},
                source_page_id=source_page_id,
            )
            db.upsert_relationship(
                quest_id,
                npc_id,
                "objective_kill",
                source_page_id=source_page_id,
                evidence="Synthetic performance kill objective.",
            )
            db.upsert_relationship(
                quest_id,
                item_id,
                "objective_turn_in_item",
                source_page_id=source_page_id,
                evidence="Synthetic performance turn-in item.",
            )
            db.upsert_relationship(
                item_id,
                npc_id,
                "drops_from",
                source_page_id=source_page_id,
                evidence="Synthetic performance drop chain.",
            )
            db.add_location(
                npc_id,
                zone_entity_id=zone_id,
                y=100.0,
                x=200.0,
                z=5.0,
                label="synthetic spawn",
                source_page_id=source_page_id,
                evidence="Synthetic performance location.",
            )

            kinds = ("item", "npc", "spell")
            for i in range(max(0, int(filler_entities))):
                kind = kinds[i % len(kinds)]
                name = f"Performance Filler {kind.title()} {i:07d}"
                entity_id = db.upsert_entity(
                    kind=kind,
                    name=name,
                    external_id=f"{kind}:perf:{i}",
                )
                for alias_index in range(max(0, int(aliases_per_entity))):
                    db.add_alias(
                        entity_id,
                        f"Perf Alias {i:07d} {alias_index}",
                        alias_type="synthetic",
                    )

        # Compile the same compact Live lookup tables shipped in production snapshots.
        ActivityPathwayEngine(db).compile_catalog()
        db.rebuild_search_index()
    finally:
        db.close()

    create_knowledge_snapshot(
        working,
        snapshot,
        snapshot_version="synthetic-performance",
        overwrite=True,
    )
    return working, snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a large release-shaped EverQuestie performance fixture."
    )
    parser.add_argument("--working-db", required=True)
    parser.add_argument("--snapshot-db", required=True)
    parser.add_argument("--entities", type=int, default=50_000)
    parser.add_argument("--aliases-per-entity", type=int, default=2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    working, snapshot = create_performance_fixture(
        args.working_db,
        args.snapshot_db,
        filler_entities=args.entities,
        aliases_per_entity=args.aliases_per_entity,
        overwrite=args.force,
    )
    print(f"working DB: {working}")
    print(f"snapshot DB: {snapshot}")
    print(f"filler entities: {args.entities:,}")
    print(f"aliases/entity: {args.aliases_per_entity}")
    print(f"benchmark NPC: {HOT_NPC}")
    print(f"benchmark item: {HOT_ITEM}")
    print(f"benchmark query: {HOT_ITEM}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
