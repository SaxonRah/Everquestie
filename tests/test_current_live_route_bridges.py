from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.travel_supplement import TravelSupplementImporter
from eqquest.zone_travel import ZoneTravelCatalog


REPO_ROOT = Path(__file__).resolve().parents[1]
TRAVEL_DIR = REPO_ROOT / "builder-data" / "travel-supplements"


class CurrentLiveRouteBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
        self.ids: dict[str, int] = {}
        for name, zone_id in (
            ("The Stonebrunt Mountains", 100),
            ("The Warrens", 101),
            ("Paineel", 75),
            ("Toxxulia Forest", 414),
            ("The Plane of Knowledge", 202),
            ("The Greater Faydark", 54),
            ("Stone Hive", 396),
            ("Blightfire Moors", 395),
            ("West Freeport", 383),
        ):
            self.ids[name] = self.db.upsert_entity(
                kind="zone",
                name=name,
                external_id=str(zone_id),
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )

        # Match the production identity surface where reviewed source labels omit
        # leading articles used by the current EQ client display names.
        self.db.add_alias(
            self.ids["The Stonebrunt Mountains"],
            "Stonebrunt Mountains",
            alias_type="test-current-display-alias",
        )
        self.db.add_alias(
            self.ids["The Greater Faydark"],
            "Greater Faydark",
            alias_type="test-current-display-alias",
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_reviewed_odus_bridges_close_current_live_direction_gaps(self):
        TravelSupplementImporter(self.db).import_manifest(
            TRAVEL_DIR / "odus-current-live-zone-lines.json"
        )
        catalog = ZoneTravelCatalog(self.db)

        stonebrunt = self.ids["The Stonebrunt Mountains"]
        warrens = self.ids["The Warrens"]
        paineel = self.ids["Paineel"]
        tox = self.ids["Toxxulia Forest"]

        self.assertEqual(
            catalog.shortest_path(stonebrunt, paineel),
            [stonebrunt, warrens, paineel],
        )
        self.assertEqual(
            catalog.shortest_path(paineel, stonebrunt),
            [paineel, warrens, stonebrunt],
        )
        self.assertEqual(catalog.shortest_path(tox, paineel), [tox, paineel])
        self.assertEqual(catalog.shortest_path(paineel, tox), [paineel, tox])

    def test_reviewed_tss_bridge_reaches_west_freeport_through_pok(self):
        importer = TravelSupplementImporter(self.db)
        importer.import_manifest(TRAVEL_DIR / "tss-current-live-bridges.json")
        importer.import_manifest(TRAVEL_DIR / "plane-of-knowledge-city-portals.json")
        catalog = ZoneTravelCatalog(self.db)

        stone_hive = self.ids["Stone Hive"]
        blightfire = self.ids["Blightfire Moors"]
        pok = self.ids["The Plane of Knowledge"]
        west_freeport = self.ids["West Freeport"]

        self.assertEqual(
            catalog.shortest_path(stone_hive, west_freeport),
            [stone_hive, blightfire, pok, west_freeport],
        )


if __name__ == "__main__":
    unittest.main()
