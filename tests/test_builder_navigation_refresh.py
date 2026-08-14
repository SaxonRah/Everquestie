from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.navigation_catalog import (
    NAVIGATION_CATALOG_VERSION,
    ensure_builder_navigation_catalog,
)
from eqquest.runtime import RuntimeDatabase
from eqquest.travel import build_route_result
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


_MAP_TEXT = "\n".join(
    [
        "L 0,0,0,100,100,0,255,255,255",
        "P 50,50,0,0,255,0,2,To_Blightfire_Moors",
    ]
) + "\n"


class BuilderNavigationRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, external_id: str, namespace: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=external_id,
            external_namespace=namespace,
            merge_by_name=False,
        )

    def _corpus(self):
        provider_stone = self._zone("Stone Hive", "884", "allakhazam:zone")
        client_stone = self._zone("Stone Hive", "396", "eqclient:zone")
        provider_blight = self._zone("Blightfire Moors", "999", "allakhazam:zone")
        client_blight = self._zone("Blightfire Moors", "395", "eqclient:zone")
        return provider_stone, client_stone, provider_blight, client_blight

    def _index_stone_hive(self) -> Path:
        maps = self.root / "Good's Maps"
        maps.mkdir(parents=True, exist_ok=True)
        (maps / "stonehive.txt").write_text(_MAP_TEXT, encoding="utf-8")
        MapCatalog(self.db).index_root(maps, source_name="Good's Maps")
        return maps

    def test_existing_builder_db_repairs_from_stored_map_evidence_without_filesystem_rescan(self):
        _provider_stone, client_stone, _provider_blight, client_blight = self._corpus()
        maps = self._index_stone_hive()

        # The map catalog is already persisted, but the higher-level zone/travel
        # derivatives have not been compiled yet. Delete the filesystem input to prove
        # the compatibility repair cannot rescan or parse the local map pack.
        shutil.rmtree(maps)

        refresh = ensure_builder_navigation_catalog(self.db)
        self.assertTrue(refresh.refreshed)
        self.assertEqual(self.db.get_meta("navigation_catalog_version"), NAVIGATION_CATALOG_VERSION)
        self.assertEqual(self.db.get_meta("navigation_catalog_dirty"), "0")

        binding = ZoneMapCatalog(self.db).binding_for_map("Good's Maps", "stonehive")
        self.assertIsNotNone(binding)
        self.assertEqual(binding.status, "linked")
        self.assertEqual(binding.zone_entity_id, client_stone)

        edges = ZoneTravelCatalog(self.db).edges_from(client_stone)
        linked = [edge for edge in edges if edge.target_zone_entity_id == client_blight]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0].status, "linked")
        self.assertIn("Blightfire Moors", linked[0].evidence)

        route = build_route_result(self.db, "Stone Hive", "Blightfire Moors")
        self.assertTrue(route.ok)
        self.assertEqual(route.path, (client_stone, client_blight))

    def test_clean_builder_catalog_is_a_noop_until_zone_identity_changes(self):
        self._corpus()
        self._index_stone_hive()
        first = ensure_builder_navigation_catalog(self.db)
        self.assertTrue(first.refreshed)

        second = ensure_builder_navigation_catalog(self.db)
        self.assertFalse(second.refreshed)

        # Triggers are installed by the first ensure. A provider/client zone identity
        # change dirties only the derived navigation layer; no map re-index is needed.
        zone = self._zone("A New Test Zone", "777", "eqclient:zone")
        self.assertGreater(zone, 0)
        self.assertEqual(self.db.get_meta("navigation_catalog_dirty"), "1")
        third = ensure_builder_navigation_catalog(self.db)
        self.assertTrue(third.refreshed)
        self.assertEqual(self.db.get_meta("navigation_catalog_dirty"), "0")

    def test_map_label_changes_dirty_navigation_and_rebuild_travel(self):
        _provider_stone, client_stone, _provider_blight, client_blight = self._corpus()
        other = self._zone("The Other Zone", "777", "eqclient:zone")
        self._index_stone_hive()
        ensure_builder_navigation_catalog(self.db)

        label = self.db.conn.execute(
            "SELECT id FROM map_labels WHERE raw_text='To Blightfire Moors' OR raw_text='To_Blightfire_Moors' LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(label)
        self.db.conn.execute(
            "UPDATE map_labels SET raw_text='To The Other Zone', clean_text='The Other Zone' WHERE id=?",
            (int(label["id"]),),
        )
        self.db.conn.commit()
        self.assertEqual(self.db.get_meta("navigation_catalog_dirty"), "1")

        ensure_builder_navigation_catalog(self.db)
        targets = {
            edge.target_zone_entity_id
            for edge in ZoneTravelCatalog(self.db).edges_from(client_stone)
            if edge.status == "linked"
        }
        self.assertIn(other, targets)
        self.assertNotIn(client_blight, targets)

    def test_finalized_runtime_never_refreshes_or_writes_navigation_catalog(self):
        self._corpus()
        self._index_stone_hive()
        ensure_builder_navigation_catalog(self.db)
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.db.path,
            snapshot,
            snapshot_version="builder-navigation-refresh-test",
        )

        before = snapshot.read_bytes()
        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            refresh = ensure_builder_navigation_catalog(runtime, force=True)
            self.assertFalse(refresh.refreshed)
            route = build_route_result(runtime, "Stone Hive", "Blightfire Moors")
            self.assertTrue(route.ok)
        finally:
            runtime.close()
            self.assertEqual(snapshot.read_bytes(), before)
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
