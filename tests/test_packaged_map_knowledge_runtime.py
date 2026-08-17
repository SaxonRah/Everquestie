from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.local_search import search_local_hits
from eqquest.locations import location_evidence_for_term, where_text
from eqquest.map_catalog import MapCatalog
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog


class PackagedMapKnowledgeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.working = self.root / "working.sqlite3"
        self.knowledge = self.root / "everquestie-knowledge.sqlite3"
        self.state = self.root / "everquestie-user.sqlite3"
        self.goods = self.root / "goods-source-pack"
        self.brewall = self.root / "brewall-source-pack"
        self.goods.mkdir()
        self.brewall.mkdir()

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _write_map(root: Path, *, x: int, y: int, z: int) -> None:
        (root / "qeynos.txt").write_text(
            "L 0,0,0,10,10,0,0,0,0\n"
            f"P {x},{y},{z},255,0,0,2,Guard_Hezlan\n",
            encoding="utf-8",
        )

    def _build_release_snapshot(self) -> int:
        self._write_map(self.goods, x=10, y=20, z=3)
        self._write_map(self.brewall, x=30, y=40, z=5)

        builder = Database(self.working)
        try:
            builder.upsert_entity(
                kind="zone",
                name="South Qeynos",
                external_id="1",
                external_namespace="eqclient:zone",
                merge_by_name=True,
                data={"map_short_name": "qeynos"},
            )
            npc_id = builder.upsert_entity(
                kind="npc",
                name="Guard Hezlan",
                zone="South Qeynos",
                merge_by_name=True,
            )

            catalog = MapCatalog(builder)
            catalog.index_root(
                self.goods,
                source_name="Goods",
                source_version="2026-08-17",
            )
            ZoneMapCatalog(builder).reconcile(source_name="Goods")
            catalog.index_root(
                self.brewall,
                source_name="Brewall",
                source_version="2026-08-17",
            )
            ZoneMapCatalog(builder).reconcile(source_name="Brewall")
            links = catalog.reconcile_all(force=True)
            self.assertEqual(links["linked"], 2)
        finally:
            builder.close()

        create_knowledge_snapshot(
            self.working,
            self.knowledge,
            snapshot_version="packaged-map-runtime-test",
        )
        return npc_id

    def test_shipped_map_knowledge_survives_without_local_source_packs(self):
        npc_id = self._build_release_snapshot()
        before_hash = self._digest(self.knowledge)
        before_bytes = self.knowledge.stat().st_size

        # Builder map packs are deliberately unavailable before packaged runtime opens.
        # Runtime knowledge must come from the finalized SQLite snapshot, not a hidden
        # source crawl or a rendering-directory dependency.
        shutil.rmtree(self.goods)
        shutil.rmtree(self.brewall)
        self.assertFalse(self.goods.exists())
        self.assertFalse(self.brewall.exists())

        runtime = RuntimeDatabase(
            self.knowledge,
            self.state,
            migrate_legacy=False,
        )
        try:
            hits = search_local_hits(
                runtime,
                "Guard Hezlan",
                default_kind="npc",
                limit=10,
            )
            self.assertEqual(len(hits), 1)
            self.assertEqual(int(hits[0].row["id"]), npc_id)
            self.assertEqual(hits[0].row["name"], "Guard Hezlan")

            entity, status, locations = location_evidence_for_term(
                runtime,
                "Guard Hezlan",
                kind="npc",
            )
            self.assertIsNotNone(entity)
            self.assertIn(status, {"exact", "unique"})
            self.assertEqual(int(entity["id"]), npc_id)

            mapped = [row for row in locations if row.evidence_type == "map_label"]
            self.assertEqual(len(mapped), 2)
            self.assertEqual(
                {row.source_name for row in mapped},
                {"Goods", "Brewall"},
            )
            self.assertEqual(
                {row.source_version for row in mapped},
                {"2026-08-17"},
            )
            self.assertTrue(all(row.zone_name == "South Qeynos" for row in mapped))
            self.assertTrue(all(row.navigable for row in mapped))
            self.assertEqual(
                {(row.x, row.y, row.z) for row in mapped},
                {(-10.0, -20.0, 3.0), (-30.0, -40.0, 5.0)},
            )

            rendered = where_text(runtime, npc_id)
            self.assertIn("WHERE | [npc] Guard Hezlan", rendered)
            self.assertIn("Goods 2026-08-17", rendered)
            self.assertIn("Brewall 2026-08-17", rendered)
            self.assertIn("Y=-20 X=-10 Z=3", rendered)
            self.assertIn("Y=-40 X=-30 Z=5", rendered)

            # A nonexistent local rendering root is user state, not a knowledge
            # prerequisite. Ordinary player writes must remain confined to the user DB.
            missing_render_root = self.root / "player-maps-not-installed"
            runtime.set_meta("map_root", str(missing_render_root))
            runtime.add_event(
                Event(
                    kind="loot",
                    raw="You have looted a Runtime Token.",
                    item="Runtime Token",
                )
            )
            self.assertEqual(runtime.get_meta("map_root"), str(missing_render_root))
            self.assertEqual(len(runtime.observed_event_history()), 1)
            self.assertFalse(missing_render_root.exists())
        finally:
            runtime.close()

        self.assertTrue(self.state.is_file())
        self.assertEqual(self._digest(self.knowledge), before_hash)
        self.assertEqual(self.knowledge.stat().st_size, before_bytes)
        self.assertFalse(Path(str(self.knowledge) + "-wal").exists())
        self.assertFalse(Path(str(self.knowledge) + "-shm").exists())
        self.assertFalse(self.goods.exists())
        self.assertFalse(self.brewall.exists())

        reopened = RuntimeDatabase(
            self.knowledge,
            self.state,
            migrate_legacy=False,
        )
        try:
            self.assertEqual(
                reopened.get_meta("map_root"),
                str(self.root / "player-maps-not-installed"),
            )
            self.assertEqual(len(reopened.observed_event_history()), 1)
            self.assertIn("Goods 2026-08-17", where_text(reopened, npc_id))
            self.assertIn("Brewall 2026-08-17", where_text(reopened, npc_id))
        finally:
            reopened.close()

        self.assertEqual(self._digest(self.knowledge), before_hash)


if __name__ == "__main__":
    unittest.main()
