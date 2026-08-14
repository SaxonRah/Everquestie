from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.local_map_readiness import resolve_local_map_readiness
from eqquest.runtime import RuntimeDatabase
from eqquest.runtime_zone_identity import resolve_runtime_zone
from eqquest.zone_identity import ZoneIdentityIndex


_MAP_TEXT = "L 0,0,0,100,100,0,255,255,255\nP 50,50,0,255,0,0,2,Stone_Hive\n"


class RuntimeZoneMapDisambiguationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(
        self,
        name: str,
        external_id: str,
        namespace: str,
        *,
        data: dict | None = None,
    ) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=external_id,
            external_namespace=namespace,
            merge_by_name=False,
            data=data,
        )

    @staticmethod
    def _write_map(folder: Path, stem: str) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{stem}.txt"
        path.write_text(_MAP_TEXT, encoding="utf-8")
        return path

    def test_runtime_prefers_unique_client_backed_duplicate_canonical_name(self):
        provider = self._zone("Stone Hive", "884", "allakhazam:zone")
        client = self._zone("Stone Hive", "400", "eqclient:zone")

        strict = ZoneIdentityIndex(self.db).resolve("Stone Hive")
        self.assertEqual(strict.status, "ambiguous")
        self.assertEqual({row.entity_id for row in strict.candidates}, {provider, client})

        runtime = resolve_runtime_zone(self.db, "Stone Hive")
        self.assertEqual(runtime.status, "linked")
        self.assertEqual(runtime.entity_id, client)
        self.assertIn("EverQuest client identity", runtime.reason)

    def test_runtime_does_not_use_client_preference_to_break_alias_ambiguity(self):
        south = self._zone("South Freeport", "10", "eqclient:zone")
        east = self._zone("East Freeport", "20", "allakhazam:zone")
        self.db.add_alias(south, "Freeport", alias_type="provider_alias")
        self.db.add_alias(east, "Freeport", alias_type="provider_alias")

        runtime = resolve_runtime_zone(self.db, "Freeport")
        self.assertEqual(runtime.status, "ambiguous")
        self.assertIsNone(runtime.identity)

    def test_current_zone_map_loads_with_provider_duplicate_and_no_compiled_binding(self):
        self._zone("Stone Hive", "884", "allakhazam:zone")
        client = self._zone("Stone Hive", "400", "eqclient:zone")
        maps = self.root / "maps" / "Good's Maps"
        expected = self._write_map(maps, "stonehive")

        readiness = resolve_local_map_readiness(self.db, "Stone Hive", maps)
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.canonical_zone_entity_id, client)
        self.assertEqual(readiness.path, expected)
        self.assertEqual(readiness.reason, "canonical runtime zone identity local map match")

    def test_true_duplicate_client_names_may_share_one_map_geometry_without_merging_identity(self):
        first = self._zone("Stone Hive", "400", "eqclient:zone")
        second = self._zone("Stone Hive", "401", "eqclient:zone")
        maps = self.root / "maps" / "Good's Maps"
        expected = self._write_map(maps, "stonehive")

        runtime = resolve_runtime_zone(self.db, "Stone Hive")
        self.assertEqual(runtime.status, "ambiguous")
        self.assertEqual({row.entity_id for row in runtime.candidates}, {first, second})

        readiness = resolve_local_map_readiness(self.db, "Stone Hive", maps)
        self.assertTrue(readiness.ready)
        self.assertIsNone(readiness.canonical_zone_entity_id)
        self.assertEqual(readiness.path, expected)
        self.assertIn("share one local map geometry", readiness.reason)

    def test_true_duplicate_client_names_with_two_installed_packs_become_map_ambiguity(self):
        self._zone("Stone Hive", "400", "eqclient:zone")
        self._zone("Stone Hive", "401", "eqclient:zone")
        collection = self.root / "EverQuest" / "maps"
        good = self._write_map(collection / "Good's Maps", "stonehive")
        brewall = self._write_map(collection / "Brewall's Maps", "stonehive")

        readiness = resolve_local_map_readiness(self.db, "Stone Hive", collection)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.status, "map_ambiguous")
        self.assertEqual(set(readiness.candidates), {good, brewall})
        self.assertIn("multiple local map-pack copies", readiness.reason)

    def test_alias_ambiguity_still_blocks_local_filename_guess(self):
        south = self._zone("South Qeynos", "1", "eqclient:zone")
        north = self._zone("North Qeynos", "2", "eqclient:zone")
        self.db.add_alias(south, "qeynos", alias_type="provider_alias")
        self.db.add_alias(north, "qeynos", alias_type="provider_alias")
        maps = self.root / "maps"
        self._write_map(maps, "qeynos")

        readiness = resolve_local_map_readiness(self.db, "qeynos", maps)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.status, "zone_ambiguous")
        self.assertEqual(readiness.candidates, ())

    def test_finalized_runtime_uses_same_live_zone_policy_read_only(self):
        self._zone("Stone Hive", "884", "allakhazam:zone")
        client = self._zone("Stone Hive", "400", "eqclient:zone")
        maps = self.root / "maps" / "Good's Maps"
        expected = self._write_map(maps, "stonehive")
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.db.path,
            snapshot,
            snapshot_version="runtime-zone-map-disambiguation-test",
        )

        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            readiness = resolve_local_map_readiness(runtime, "Stone Hive", maps)
            self.assertTrue(readiness.ready)
            self.assertEqual(readiness.canonical_zone_entity_id, client)
            self.assertEqual(readiness.path, expected)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entities SET name='mutated' WHERE id=?", (client,))
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
