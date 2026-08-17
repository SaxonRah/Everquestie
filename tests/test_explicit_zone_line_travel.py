from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.navigation_catalog import NAVIGATION_CATALOG_VERSION, ensure_builder_navigation_catalog
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZONE_TRAVEL_CATALOG_VERSION, ZoneTravelCatalog


class ExplicitZoneLineTravelTests(unittest.TestCase):
    def test_explicit_map_author_spellings_are_recognized_without_bare_name_guessing(self):
        cases = {
            "ZL_to_Blightfire_Moors": ("zone_line", "Blightfire Moors"),
            "z/l: Blightfire Moors": ("zone_line", "Blightfire Moors"),
            "Blightfire_Moors_ZL": ("zone_line", "Blightfire Moors"),
            "Zone_Line_-_Blightfire_Moors": ("zone_line", "Blightfire Moors"),
            "Connection_to_Blightfire_Moors": ("zone_line", "Blightfire Moors"),
            "connection: Blightfire Moors": ("zone_line", "Blightfire Moors"),
            "Boundary_-_Blightfire_Moors": ("zone_line", "Blightfire Moors"),
            "boundary=Blightfire_Moors": ("zone_line", "Blightfire Moors"),
            "Portal:_Blightfire_Moors": ("portal", "Blightfire Moors"),
            "Teleporter_-_Blightfire_Moors": ("portal", "Blightfire Moors"),
            "Exit:_Blightfire_Moors": ("exit", "Blightfire Moors"),
            "Entrance_to_Blightfire_Moors": ("exit", "Blightfire Moors"),
            "To:_Blightfire_Moors": ("travel", "Blightfire Moors"),
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(ZoneTravelCatalog._travel_candidate(label), expected)

        # Exact zone names still require explicit travel/zone-line evidence. A bare
        # canonical name on a map can be a landmark and must not become an exit.
        self.assertIsNone(ZoneTravelCatalog._travel_candidate("Blightfire_Moors"))
        self.assertIsNone(ZoneTravelCatalog._travel_candidate("Bank"))
        self.assertEqual(ZONE_TRAVEL_CATALOG_VERSION, "3")
        self.assertEqual(NAVIGATION_CATALOG_VERSION, "5")

    def test_existing_clean_builder_catalog_recompiles_stored_labels_for_new_syntax(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            maps = root / "maps"
            maps.mkdir()
            (maps / "stonehive.txt").write_text(
                "\n".join(
                    [
                        "P 10,20,3,255,0,0,2,ZL_to_Blightfire_Moors",
                        "P 30,40,5,255,0,0,2,Portal:_Goru'kar_Mesa",
                        "P 50,60,7,255,0,0,2,Connection_to_Crescent_Reach",
                        "P 70,80,9,255,0,0,2,Boundary:_Nektulos_Forest",
                        "P 90,100,11,255,0,0,2,Bank",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            db = Database(root / "knowledge.sqlite3")
            try:
                stone = db.upsert_entity(
                    kind="zone",
                    name="Stone Hive",
                    merge_by_name=True,
                    data={"map_short_name": "stonehive"},
                )
                blight = db.upsert_entity(
                    kind="zone",
                    name="Blightfire Moors",
                    merge_by_name=True,
                    data={"map_short_name": "blightfire"},
                )
                mesa = db.upsert_entity(
                    kind="zone",
                    name="Goru'kar Mesa",
                    merge_by_name=True,
                    data={"map_short_name": "gorukar"},
                )
                crescent = db.upsert_entity(
                    kind="zone",
                    name="Crescent Reach",
                    merge_by_name=True,
                    data={"map_short_name": "crescent"},
                )
                nektulos = db.upsert_entity(
                    kind="zone",
                    name="Nektulos Forest",
                    merge_by_name=True,
                    data={"map_short_name": "nektulos"},
                )
                MapCatalog(db).index_root(maps, source_name="Good's Maps")
                ZoneMapCatalog(db).reconcile(source_name="Good's Maps")

                # Simulate a builder DB that had already been considered clean by
                # navigation catalog v3 before Connection/Boundary were promoted.
                ZoneTravelCatalog(db)  # ensure the historic derivative table exists
                db.set_meta("navigation_catalog_version", "3")
                db.set_meta("navigation_catalog_dirty", "0")
                db.conn.execute("DELETE FROM zone_travel_edges WHERE source_kind='map_label'")
                db.conn.commit()

                refresh = ensure_builder_navigation_catalog(db)
                self.assertTrue(refresh.refreshed)
                self.assertIsNotNone(refresh.travel)
                self.assertEqual(refresh.travel.candidates, 4)
                self.assertEqual(refresh.travel.linked, 4)
                self.assertEqual(db.get_meta("navigation_catalog_version"), "5")
                self.assertEqual(db.get_meta("navigation_catalog_dirty"), "0")

                edges = ZoneTravelCatalog(db).edges_from(stone)
                self.assertEqual(len(edges), 4)
                by_target = {edge.target_zone_entity_id: edge for edge in edges}
                self.assertEqual(by_target[blight].connection_kind, "zone_line")
                self.assertEqual(by_target[mesa].connection_kind, "portal")
                self.assertEqual(by_target[crescent].connection_kind, "zone_line")
                self.assertEqual(by_target[nektulos].connection_kind, "zone_line")
                self.assertTrue(all(not edge.bidirectional for edge in edges))
                self.assertTrue(all(edge.source_kind == "map_label" for edge in edges))
                self.assertTrue(all(edge.source_name == "Good's Maps" for edge in edges))
                self.assertTrue(all(edge.source_key for edge in edges))

                # The same graph is immediately routeable; no filesystem scan occurs
                # in this read path after the builder refresh.
                self.assertEqual(ZoneTravelCatalog(db).shortest_path(stone, blight), [stone, blight])
                self.assertEqual(ZoneTravelCatalog(db).shortest_path(stone, mesa), [stone, mesa])
                self.assertEqual(ZoneTravelCatalog(db).shortest_path(stone, crescent), [stone, crescent])
                self.assertEqual(ZoneTravelCatalog(db).shortest_path(stone, nektulos), [stone, nektulos])
                self.assertEqual(ZoneTravelCatalog(db).shortest_path(crescent, stone), [])
                self.assertEqual(ZoneTravelCatalog(db).shortest_path(nektulos, stone), [])

                # Once v5 is clean, repeated Travel reads do not rebuild again.
                second = ensure_builder_navigation_catalog(db)
                self.assertFalse(second.refreshed)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
