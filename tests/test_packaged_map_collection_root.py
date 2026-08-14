from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.eqmap import (
    discover_base_maps,
    discover_local_base_maps,
    load_zone_map,
    resolve_map_for_zone,
)
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.local_map_readiness import resolve_local_map_readiness
from eqquest.map_catalog import MapCatalog
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog


_MAP_TEXT = "L 0,0,0,100,100,0,255,255,255\nP 50,50,0,255,0,0,2,Test_Label\n"


class PackagedMapCollectionRootTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _write_map(folder: Path, stem: str, *, layer1: bool = False) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{stem}.txt"
        path.write_text(_MAP_TEXT, encoding="utf-8")
        if layer1:
            (folder / f"{stem}_1.txt").write_text(
                "P 25,25,1,0,255,0,2,Layer_One\n",
                encoding="utf-8",
            )
        return path

    def _runtime_with_stonehive_catalog(self) -> RuntimeDatabase:
        working = self.root / "working.sqlite3"
        builder = Database(working)
        try:
            builder.upsert_entity(
                kind="zone",
                name="Stone Hive",
                external_id="400",
                external_namespace="eqclient:zone",
                merge_by_name=True,
            )
            source_pack = self.root / "builder-good"
            self._write_map(source_pack, "stonehive")
            MapCatalog(builder).index_root(
                source_pack,
                source_name="Good's Maps",
                source_version="fixture",
            )
            stats = ZoneMapCatalog(builder).reconcile(source_name="Good's Maps")
            self.assertEqual(stats.linked, 1)
        finally:
            builder.close()

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            working,
            snapshot,
            snapshot_version="packaged-map-collection-root-test",
        )
        return RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )

    def test_player_collection_root_finds_map_in_nested_good_pack(self):
        collection = self.root / "EverQuest" / "maps"
        good = collection / "Good's Maps"
        expected = self._write_map(good, "stonehive", layer1=True)
        self._write_map(collection / "Brewall's Maps", "blightfire")

        # Builder discovery remains intentionally source-scoped.
        self.assertEqual(discover_base_maps(collection), [])
        local = discover_local_base_maps(collection)
        self.assertIn(expected, local)
        self.assertNotIn(good / "stonehive_1.txt", local)

        # The ordinary local fallback now accepts the parent EverQuest/maps root.
        self.assertEqual(resolve_map_for_zone("Stone Hive", collection), expected)
        zone_map = load_zone_map(expected)
        self.assertEqual(set(zone_map.layers), {0, 1})

    def test_finalized_runtime_resolves_nested_local_pack_without_rebuilding_catalog(self):
        collection = self.root / "EverQuest" / "maps"
        expected = self._write_map(collection / "Good's Maps", "stonehive")
        self._write_map(collection / "Brewall's Maps", "blightfire")
        runtime = self._runtime_with_stonehive_catalog()
        try:
            runtime.set_meta("map_root", str(collection))
            readiness = resolve_local_map_readiness(runtime, "Stone Hive", collection)
            self.assertTrue(readiness.ready)
            self.assertEqual(readiness.path, expected)
            self.assertEqual(readiness.reason, "shipped canonical zone/map binding")
            self.assertEqual(runtime.get_meta("map_root"), str(collection))
        finally:
            runtime.close()

    def test_duplicate_same_stem_across_local_packs_is_explicitly_ambiguous(self):
        collection = self.root / "EverQuest" / "maps"
        good = self._write_map(collection / "Good's Maps", "stonehive")
        brewall = self._write_map(collection / "Brewall's Maps", "stonehive")

        # Legacy resolution refuses to choose one pack by filesystem ordering.
        self.assertIsNone(resolve_map_for_zone("Stone Hive", collection))

        runtime = self._runtime_with_stonehive_catalog()
        try:
            readiness = resolve_local_map_readiness(runtime, "Stone Hive", collection)
            self.assertFalse(readiness.ready)
            self.assertEqual(readiness.status, "map_ambiguous")
            self.assertEqual(set(readiness.candidates), {good, brewall})
            self.assertIn("pack collection", readiness.reason)
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
