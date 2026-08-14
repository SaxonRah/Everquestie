from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.local_map_readiness import local_map_readiness_text, resolve_local_map_readiness
from eqquest.map_catalog import MapCatalog
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog


class LocalMapReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    @staticmethod
    def _write_map(root: Path, stem: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{stem}.txt"
        path.write_text("P 1,2,3,255,0,0,2,Test_Label\n", encoding="utf-8")
        return path

    def _two_variant_catalog(self, *, hint: str = "") -> int:
        data = {"map_short_name": hint} if hint else None
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data=data,
        )
        self.db.add_alias(zone_id, "poknowledge", alias_type="provider_short_name")
        self.db.add_alias(zone_id, "planeofknowledge", alias_type="provider_short_name")

        good = self.root / "builder-good"
        brewall = self.root / "builder-brewall"
        self._write_map(good, "poknowledge")
        self._write_map(brewall, "planeofknowledge")
        MapCatalog(self.db).index_root(good, source_name="Good", source_version="1")
        ZoneMapCatalog(self.db).reconcile(source_name="Good")
        MapCatalog(self.db).index_root(brewall, source_name="Brewall", source_version="1")
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        return zone_id

    def test_ready_intersects_shipped_binding_with_selected_local_pack(self):
        zone_id = self._two_variant_catalog()
        local = self.root / "player-pack"
        expected = self._write_map(local, "poknowledge")
        before_sources = int(self.db.conn.execute("SELECT COUNT(*) FROM map_sources").fetchone()[0])

        readiness = resolve_local_map_readiness(self.db, "202", local)
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.status, "ready")
        self.assertEqual(readiness.canonical_zone_entity_id, zone_id)
        self.assertEqual(readiness.canonical_zone_name, "The Plane of Knowledge")
        self.assertEqual(readiness.path, expected)
        self.assertEqual(readiness.reason, "shipped canonical zone/map binding")
        self.assertIn("Local map ready", local_map_readiness_text(readiness))

        after_sources = int(self.db.conn.execute("SELECT COUNT(*) FROM map_sources").fetchone()[0])
        self.assertEqual(after_sources, before_sources)

    def test_multiple_local_canonical_variants_are_reported_ambiguous(self):
        self._two_variant_catalog()
        local = self.root / "combined-pack"
        a = self._write_map(local, "poknowledge")
        b = self._write_map(local, "planeofknowledge")

        readiness = resolve_local_map_readiness(self.db, "The Plane of Knowledge", local)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.status, "map_ambiguous")
        self.assertEqual(set(readiness.candidates), {a, b})
        self.assertIn("multiple canonical map variants", local_map_readiness_text(readiness))

    def test_packaged_short_name_hint_resolves_present_variants_without_user_write(self):
        self._two_variant_catalog(hint="planeofknowledge")
        local = self.root / "combined-pack"
        self._write_map(local, "poknowledge")
        expected = self._write_map(local, "planeofknowledge")

        readiness = resolve_local_map_readiness(self.db, "202", local)
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.path, expected)
        self.assertEqual(readiness.hinted_stem, "planeofknowledge")
        self.assertEqual(readiness.reason, "explicit canonical map short-name hint")

    def test_explicit_user_binding_wins_over_packaged_hint(self):
        self._two_variant_catalog(hint="planeofknowledge")
        local = self.root / "combined-pack"
        expected = self._write_map(local, "poknowledge")
        self._write_map(local, "planeofknowledge")

        readiness = resolve_local_map_readiness(
            self.db,
            "The Plane of Knowledge",
            local,
            bound_stem="poknowledge",
        )
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.path, expected)
        self.assertEqual(readiness.bound_stem, "poknowledge")
        self.assertEqual(readiness.reason, "user map binding")

    def test_missing_root_and_missing_map_are_distinct(self):
        self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            external_id="400",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        unavailable = resolve_local_map_readiness(
            self.db,
            "Stone Hive",
            self.root / "does-not-exist",
        )
        self.assertEqual(unavailable.status, "root_unavailable")
        self.assertIn("choose a valid map pack folder", local_map_readiness_text(unavailable))

        empty_root = self.root / "empty-pack"
        empty_root.mkdir()
        missing = resolve_local_map_readiness(self.db, "Stone Hive", empty_root)
        self.assertEqual(missing.status, "map_missing")
        self.assertIn("Local map missing", local_map_readiness_text(missing))

    def test_canonical_zone_ambiguity_is_not_broken_by_local_filename(self):
        north = self.db.upsert_entity(kind="zone", name="North Freeport", merge_by_name=True)
        south = self.db.upsert_entity(kind="zone", name="South Freeport", merge_by_name=True)
        self.db.add_alias(north, "Freeport", alias_type="provider_alias")
        self.db.add_alias(south, "Freeport", alias_type="provider_alias")
        local = self.root / "player-pack"
        self._write_map(local, "freeport")

        readiness = resolve_local_map_readiness(self.db, "Freeport", local)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.status, "zone_ambiguous")
        self.assertIsNone(readiness.path)
        self.assertIn("will not guess", local_map_readiness_text(readiness))

    def test_finalized_runtime_checks_local_files_without_mutating_snapshot(self):
        self._two_variant_catalog(hint="planeofknowledge")
        local = self.root / "player-pack"
        expected = self._write_map(local, "planeofknowledge")
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="local-map-readiness-test",
        )
        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            readiness = resolve_local_map_readiness(runtime, "202", local)
            self.assertTrue(readiness.ready)
            self.assertEqual(readiness.path, expected)
            self.assertEqual(readiness.reason, "shipped canonical zone/map binding")
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE zone_map_bindings SET status='mutated'")
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
