from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.local_map_readiness import resolve_local_map_readiness
from eqquest.local_map_variant import bind_local_map_variant, current_local_map_variants
from eqquest.map_catalog import MapCatalog
from eqquest.mapview import _binding_key
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog


class LocalMapVariantTests(unittest.TestCase):
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
        path.write_text("P 1,2,3,255,0,0,2,Test\n", encoding="utf-8")
        return path

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _catalog(self) -> tuple[int, Path, Path, Path]:
        zone = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.db.add_alias(zone, "poknowledge", alias_type="provider_short_name")
        self.db.add_alias(zone, "planeofknowledge", alias_type="provider_short_name")

        good = self.root / "builder-good"
        brewall = self.root / "builder-brewall"
        self._write_map(good, "poknowledge")
        self._write_map(brewall, "planeofknowledge")
        MapCatalog(self.db).index_root(good, source_name="Good", source_version="1")
        ZoneMapCatalog(self.db).reconcile(source_name="Good")
        MapCatalog(self.db).index_root(brewall, source_name="Brewall", source_version="1")
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")

        local = self.root / "player-pack"
        first = self._write_map(local, "poknowledge")
        second = self._write_map(local, "planeofknowledge")
        return zone, local, first, second

    def test_current_variants_returns_full_canonical_set_without_user_binding(self):
        zone, local, first, second = self._catalog()
        self.db.set_meta(_binding_key("The Plane of Knowledge"), "poknowledge")

        readiness, candidates = current_local_map_variants(
            self.db,
            "The Plane of Knowledge",
            local,
        )
        self.assertEqual(readiness.status, "map_ambiguous")
        self.assertEqual(set(candidates), {first, second})

    def test_binding_one_current_candidate_persists_and_re_resolves(self):
        zone, local, first, second = self._catalog()
        key = _binding_key("The Plane of Knowledge")

        result = bind_local_map_variant(
            self.db,
            "The Plane of Knowledge",
            local,
            second,
            binding_key=key,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "bound")
        self.assertEqual(result.selected_path, second)
        self.assertEqual(result.reason, "user map binding")
        self.assertEqual(self.db.get_meta(key, ""), "planeofknowledge")

        readiness = resolve_local_map_readiness(
            self.db,
            "The Plane of Knowledge",
            local,
            bound_stem=self.db.get_meta(key, ""),
        )
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.path, second)
        self.assertEqual(readiness.reason, "user map binding")

    def test_binding_can_switch_between_legitimate_current_variants(self):
        zone, local, first, second = self._catalog()
        key = _binding_key("The Plane of Knowledge")

        self.assertTrue(
            bind_local_map_variant(
                self.db,
                "202",
                local,
                first,
                binding_key=key,
            ).ok
        )
        self.assertEqual(self.db.get_meta(key, ""), "poknowledge")

        self.assertTrue(
            bind_local_map_variant(
                self.db,
                "The Plane of Knowledge",
                local,
                second,
                binding_key=key,
            ).ok
        )
        self.assertEqual(self.db.get_meta(key, ""), "planeofknowledge")

    def test_arbitrary_path_under_same_root_is_rejected_without_write(self):
        zone, local, first, second = self._catalog()
        arbitrary = self._write_map(local, "totally_unrelated")
        key = _binding_key("The Plane of Knowledge")

        result = bind_local_map_variant(
            self.db,
            "The Plane of Knowledge",
            local,
            arbitrary,
            binding_key=key,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "not_candidate")
        self.assertEqual(self.db.get_meta(key, ""), "")

    def test_stale_candidate_removed_before_apply_is_rejected(self):
        zone, local, first, second = self._catalog()
        readiness, candidates = current_local_map_variants(
            self.db,
            "The Plane of Knowledge",
            local,
        )
        self.assertIn(second, candidates)
        second.unlink()

        key = _binding_key("The Plane of Knowledge")
        result = bind_local_map_variant(
            self.db,
            "The Plane of Knowledge",
            local,
            second,
            binding_key=key,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "not_candidate")
        self.assertEqual(self.db.get_meta(key, ""), "")

    def test_ambiguous_zone_identity_never_accepts_filename_candidate(self):
        north = self.db.upsert_entity(kind="zone", name="North Freeport", merge_by_name=True)
        south = self.db.upsert_entity(kind="zone", name="South Freeport", merge_by_name=True)
        self.db.add_alias(north, "Freeport", alias_type="provider_alias")
        self.db.add_alias(south, "Freeport", alias_type="provider_alias")
        local = self.root / "maps"
        candidate = self._write_map(local, "freeport")
        key = _binding_key("Freeport")

        result = bind_local_map_variant(
            self.db,
            "Freeport",
            local,
            candidate,
            binding_key=key,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "zone_ambiguous")
        self.assertEqual(self.db.get_meta(key, ""), "")

    def test_binding_key_must_be_player_map_binding_metadata(self):
        zone, local, first, second = self._catalog()
        result = bind_local_map_variant(
            self.db,
            "The Plane of Knowledge",
            local,
            first,
            binding_key="zone_catalog_coverage",
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "invalid_binding_key")
        self.assertNotEqual(self.db.get_meta("zone_catalog_coverage", ""), "poknowledge")

    def test_runtime_binding_changes_only_user_state_not_knowledge_snapshot(self):
        zone, local, first, second = self._catalog()
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="local-map-variant-test",
        )
        before = self._digest(snapshot)
        self.db.close()

        runtime = RuntimeDatabase(snapshot, state, migrate_legacy=False)
        try:
            key = _binding_key("The Plane of Knowledge")
            result = bind_local_map_variant(
                runtime,
                "The Plane of Knowledge",
                local,
                second,
                binding_key=key,
            )
            self.assertTrue(result.ok)
            self.assertEqual(runtime.get_meta(key, ""), "planeofknowledge")
            row = runtime.conn.execute(
                "SELECT value FROM user_meta WHERE key=?",
                (key,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["value"], "planeofknowledge")
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE zone_map_bindings SET status='mutated'")
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")

        self.assertEqual(self._digest(snapshot), before)
        self.assertFalse(Path(str(snapshot) + "-wal").exists())
        self.assertFalse(Path(str(snapshot) + "-shm").exists())


if __name__ == "__main__":
    unittest.main()
