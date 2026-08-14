from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.map_resolution import resolve_catalog_map_for_zone
from eqquest.zone_catalog import ZoneMapCatalog


class CanonicalMapResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "knowledge.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    @staticmethod
    def _write_map(root: Path, stem: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{stem}.txt"
        path.write_text("P 1,2,3,255,0,0,2,Test_Label\n", encoding="utf-8")
        return path

    def _build_two_variant_catalog(self) -> int:
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            merge_by_name=True,
        )
        self.db.add_alias(zone_id, "poknowledge", alias_type="provider_short_name")
        self.db.add_alias(zone_id, "planeofknowledge", alias_type="provider_short_name")

        good = self.root / "builder-good"
        brewall = self.root / "builder-brewall"
        self._write_map(good, "poknowledge")
        self._write_map(brewall, "planeofknowledge")
        MapCatalog(self.db).index_root(good, source_name="Good")
        ZoneMapCatalog(self.db).reconcile(source_name="Good")
        MapCatalog(self.db).index_root(brewall, source_name="Brewall")
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        return zone_id

    def test_selected_pack_intersects_shipped_bindings_without_reindexing(self):
        self._build_two_variant_catalog()
        local = self.root / "player-pack"
        expected = self._write_map(local, "poknowledge")

        result = resolve_catalog_map_for_zone(
            self.db,
            "The Plane of Knowledge",
            local,
        )
        self.assertEqual(result.path, expected)
        self.assertEqual(result.reason, "shipped canonical zone/map binding")
        self.assertEqual(result.candidates, (expected,))

    def test_multiple_canonical_variants_are_not_guessed(self):
        self._build_two_variant_catalog()
        local = self.root / "combined-player-pack"
        a = self._write_map(local, "poknowledge")
        b = self._write_map(local, "planeofknowledge")

        result = resolve_catalog_map_for_zone(
            self.db,
            "The Plane of Knowledge",
            local,
        )
        self.assertIsNone(result.path)
        self.assertEqual(set(result.candidates), {a, b})
        self.assertIn("multiple shipped canonical", result.reason)

    def test_explicit_canonical_hint_can_choose_between_present_variants(self):
        self._build_two_variant_catalog()
        local = self.root / "combined-player-pack"
        self._write_map(local, "poknowledge")
        expected = self._write_map(local, "planeofknowledge")

        result = resolve_catalog_map_for_zone(
            self.db,
            "The Plane of Knowledge",
            local,
            hinted_stem="planeofknowledge",
        )
        self.assertEqual(result.path, expected)
        self.assertEqual(result.reason, "explicit canonical map short-name hint")

    def test_player_binding_wins_over_catalog_variants(self):
        self._build_two_variant_catalog()
        local = self.root / "combined-player-pack"
        expected = self._write_map(local, "poknowledge")
        self._write_map(local, "planeofknowledge")

        result = resolve_catalog_map_for_zone(
            self.db,
            "The Plane of Knowledge",
            local,
            bound_stem="poknowledge",
        )
        self.assertEqual(result.path, expected)
        self.assertEqual(result.reason, "user map binding")

    def test_legacy_unique_filename_fallback_remains_for_catalog_gaps(self):
        self.db.upsert_entity(kind="zone", name="Stone Hive", merge_by_name=True)
        local = self.root / "legacy-pack"
        expected = self._write_map(local, "stonehive")

        result = resolve_catalog_map_for_zone(self.db, "Stone Hive", local)
        self.assertEqual(result.path, expected)
        self.assertEqual(result.reason, "legacy unique filename fallback")


if __name__ == "__main__":
    unittest.main()
