from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.route_acceptance import evaluate_route_acceptance
from eqquest.travel_supplement import TravelSupplementImporter
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


REPO_ROOT = Path(__file__).resolve().parents[1]
PORTAL_MANIFEST = (
    REPO_ROOT
    / "builder-data"
    / "travel-supplements"
    / "plane-of-knowledge-city-portals.json"
)


class StoneHiveLiveBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, number: int, *, map_short_name: str = "") -> int:
        data = {"map_short_name": map_short_name} if map_short_name else None
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=str(number),
            external_namespace="eqclient:zone",
            merge_by_name=False,
            data=data,
        )

    def test_brewall_map_evidence_and_reviewed_portal_close_stone_hive_to_west_freeport(self):
        stone = self._zone("Stone Hive", 396, map_short_name="stonehive")
        blight = self._zone("Blightfire Moors", 395, map_short_name="moors")
        pok = self._zone("The Plane of Knowledge", 202, map_short_name="poknowledge")
        self._zone("The Greater Faydark", 54)
        current_west_freeport = self._zone("West Freeport", 383)
        self._zone("Toxxulia Forest", 38)
        self._zone("Toxxulia Forest", 414)

        maps = self.root / "maps"
        maps.mkdir()
        # Base files establish the native map stems; Brewall keeps the travel points
        # used here on layer 1.
        (maps / "stonehive.txt").write_text("\n", encoding="utf-8")
        (maps / "stonehive_1.txt").write_text(
            "P 1183.0000,1648.0000,37.0000,255,0,0,3,to_Blightfire_Moors\n",
            encoding="utf-8",
        )
        (maps / "moors.txt").write_text("\n", encoding="utf-8")
        (maps / "moors_1.txt").write_text(
            "\n".join(
                [
                    "P 3725.0000,518.0000,162.0000,255,0,0,3,to_Stone_Hive",
                    "P -3341.0000,1211.0000,-23.1250,255,0,0,3,to_The_Plane_of_Knowledge_(Click_Book)",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        indexed = MapCatalog(self.db).index_root(
            maps,
            source_name="Brewall's Maps",
            source_version="source-shaped-test",
        )
        self.assertEqual(indexed.base_maps, 2)
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall's Maps")
        map_travel = ZoneTravelCatalog(self.db).reconcile_from_maps(
            source_name="Brewall's Maps"
        )
        self.assertEqual(map_travel.candidates, 3)
        self.assertEqual(map_travel.linked, 3)
        self.assertEqual(map_travel.ambiguous, 0)
        self.assertEqual(map_travel.unresolved, 0)

        # The city-book manifest is a separate reviewed source. This fixture contains
        # only the current-Live West Freeport identity; duplicate historical identity
        # pinning is covered by the dedicated portal-manifest regression.
        TravelSupplementImporter(self.db).import_manifest(PORTAL_MANIFEST)

        catalog = ZoneTravelCatalog(self.db)
        self.assertEqual(catalog.shortest_path(stone, blight), [stone, blight])
        self.assertEqual(catalog.shortest_path(blight, stone), [blight, stone])
        self.assertEqual(catalog.shortest_path(blight, pok), [blight, pok])
        self.assertEqual(catalog.shortest_path(pok, blight), [])
        self.assertEqual(
            catalog.shortest_path(stone, current_west_freeport),
            [stone, blight, pok, current_west_freeport],
        )

        # Preserve the map-owned handoff coordinates for player guidance.
        stone_exit = next(
            edge for edge in catalog.edges_from(stone) if edge.target_zone_entity_id == blight
        )
        pok_book = next(
            edge for edge in catalog.edges_from(blight) if edge.target_zone_entity_id == pok
        )
        self.assertEqual(stone_exit.source_kind, "map_label")
        self.assertEqual(stone_exit.source_name, "Brewall's Maps")
        self.assertEqual((stone_exit.x, stone_exit.y, stone_exit.z), (-1183.0, -1648.0, 37.0))
        self.assertEqual(pok_book.source_kind, "map_label")
        self.assertEqual(pok_book.source_name, "Brewall's Maps")
        self.assertIn("Click Book", pok_book.evidence)
        self.assertEqual((pok_book.x, pok_book.y, pok_book.z), (3341.0, -1211.0, -23.125))

        acceptance = evaluate_route_acceptance(
            self.db,
            (("Stone Hive", "West Freeport"),),
        )
        self.assertEqual(acceptance.total, 1)
        self.assertEqual(acceptance.accepted, 1)
        self.assertEqual(acceptance.failed, 0)
        result = acceptance.results[0]
        self.assertEqual(result.status, "reachable")
        self.assertEqual(result.hop_count, 3)
        self.assertEqual(
            result.path_zone_names,
            ("Stone Hive", "Blightfire Moors", "The Plane of Knowledge", "West Freeport"),
        )


if __name__ == "__main__":
    unittest.main()
