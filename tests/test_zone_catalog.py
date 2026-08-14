from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.zone_catalog import ZoneMapCatalog


class ZoneMapCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "maps"
        self.root.mkdir()
        self.db = Database(Path(self.tempdir.name) / "knowledge.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _map(self, stem: str, label: str = "Test_Label") -> None:
        (self.root / f"{stem}.txt").write_text(
            f"P 1,2,3,255,0,0,2,{label}\n",
            encoding="utf-8",
        )

    def test_unique_significant_word_links_map_to_canonical_zone(self):
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="South Qeynos",
            external_id="1",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self._map("qeynos", "Guard_Hezlan")
        MapCatalog(self.db).index_root(self.root, source_name="Brewall")

        stats = ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        self.assertEqual(stats.maps, 1)
        self.assertEqual(stats.linked, 1)
        binding = ZoneMapCatalog(self.db).binding_for_map("Brewall", "qeynos")
        self.assertIsNotNone(binding)
        self.assertEqual(binding.zone_entity_id, zone_id)
        self.assertEqual(binding.zone_name, "South Qeynos")
        self.assertEqual(binding.status, "linked")
        self.assertIn("significant", binding.reason)

        source = self.db.conn.execute(
            "SELECT zone_name FROM map_sources WHERE source_name='Brewall' AND map_stem='qeynos'"
        ).fetchone()
        label = self.db.conn.execute("SELECT zone_name FROM map_labels LIMIT 1").fetchone()
        self.assertEqual(source["zone_name"], "South Qeynos")
        self.assertEqual(label["zone_name"], "South Qeynos")

    def test_shared_word_is_recorded_ambiguous_not_guessed(self):
        self.db.upsert_entity(kind="zone", name="South Qeynos", merge_by_name=True)
        self.db.upsert_entity(kind="zone", name="North Qeynos", merge_by_name=True)
        self._map("qeynos")
        MapCatalog(self.db).index_root(self.root, source_name="Good")

        stats = ZoneMapCatalog(self.db).reconcile(source_name="Good")
        self.assertEqual(stats.ambiguous, 1)
        binding = ZoneMapCatalog(self.db).binding_for_map("Good", "qeynos")
        self.assertIsNotNone(binding)
        self.assertIsNone(binding.zone_entity_id)
        self.assertEqual(binding.status, "ambiguous")
        self.assertIn("shared", binding.reason)

    def test_explicit_short_name_hint_beats_shared_display_word(self):
        south = self.db.upsert_entity(
            kind="zone",
            name="South Qeynos",
            merge_by_name=True,
            data={"map_short_name": "qeynos"},
        )
        self.db.upsert_entity(kind="zone", name="North Qeynos", merge_by_name=True)
        self._map("qeynos")
        MapCatalog(self.db).index_root(self.root, source_name="Good")

        ZoneMapCatalog(self.db).reconcile(source_name="Good")
        binding = ZoneMapCatalog(self.db).binding_for_map("Good", "qeynos")
        self.assertEqual(binding.zone_entity_id, south)
        self.assertEqual(binding.status, "linked")
        self.assertIn("short-name", binding.reason)

    def test_later_provider_alias_can_resolve_previously_unknown_map(self):
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self._map("poknowledge")
        MapCatalog(self.db).index_root(self.root, source_name="Brewall")
        catalog = ZoneMapCatalog(self.db)
        first = catalog.reconcile(source_name="Brewall")
        self.assertEqual(first.unresolved, 1)

        # This alias could come from any later provider (including a future mirror).
        self.db.add_alias(zone_id, "poknowledge", alias_type="provider_short_name")
        second = catalog.reconcile(source_name="Brewall")
        self.assertEqual(second.linked, 1)
        binding = catalog.binding_for_map("Brewall", "poknowledge")
        self.assertEqual(binding.zone_entity_id, zone_id)
        self.assertEqual(binding.zone_name, "The Plane of Knowledge")

    def test_same_zone_can_have_pack_specific_map_bindings(self):
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            merge_by_name=True,
            data={"map_short_name": "stonehive"},
        )
        self._map("stonehive")
        map_catalog = MapCatalog(self.db)
        map_catalog.index_root(self.root, source_name="Good", source_version="1")
        map_catalog.index_root(self.root, source_name="Brewall", source_version="2")
        zone_catalog = ZoneMapCatalog(self.db)
        stats = zone_catalog.reconcile()
        self.assertEqual(stats.maps, 2)
        self.assertEqual(stats.linked, 2)
        bindings = zone_catalog.maps_for_zone(zone_id)
        self.assertEqual({b.source_name for b in bindings}, {"Good", "Brewall"})
        self.assertEqual({b.map_stem for b in bindings}, {"stonehive"})


if __name__ == "__main__":
    unittest.main()
