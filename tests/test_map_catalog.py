import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog


class MapCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "maps"
        self.root.mkdir()
        self.db = Database(Path(self.tmp.name) / "catalog.sqlite3")
        self.zone_id = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            merge_by_name=True,
            data={"map_short_name": "stonehive"},
        )
        self.npc_id = self.db.upsert_entity(
            kind="npc", name="Warwing Wendlez", zone="Stone Hive", merge_by_name=True
        )
        (self.root / "stonehive.txt").write_text(
            "L 0,0,0,10,10,0,0,0,0\n",
            encoding="utf-8",
        )
        (self.root / "stonehive_1.txt").write_text(
            "P 279,529,-27,255,0,0,2,Warwing_Wendlez_(Q)\n"
            "P 100,200,0,0,255,0,2,Other_Merchant\n",
            encoding="utf-8",
        )
        self.catalog = MapCatalog(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_indexes_all_labels_and_links_exact_entity(self):
        stats = self.catalog.index_root(self.root)
        self.assertEqual(stats.base_maps, 1)
        self.assertEqual(stats.labels, 2)
        hits = self.catalog.search('zone:"Stone Hive" Warwing', current_zone="Stone Hive")
        self.assertTrue(hits)
        self.assertEqual(hits[0].text, "Warwing Wendlez (Q)")
        self.assertEqual(hits[0].linked_entity_id, self.npc_id)
        self.assertEqual(hits[0].link_status, "linked")
        self.assertTrue(Path(hits[0].path).name.startswith("stonehive"))

    def test_typo_suggests_map_label_but_spell_filter_does_not(self):
        self.catalog.index_root(self.root)
        hits = self.catalog.search(
            'type:npc zone:"Stone Hive" Waning', current_zone="Stone Hive"
        )
        self.assertTrue(hits)
        self.assertEqual(hits[0].text, "Warwing Wendlez (Q)")
        self.assertIn("fuzzy suggestion", hits[0].reason)
        self.assertEqual(
            self.catalog.search('type:spell zone:"Stone Hive" Waning', current_zone="Stone Hive"),
            [],
        )

    def test_type_only_query_does_not_invent_map_entity_types(self):
        self.catalog.index_root(self.root)
        self.assertEqual(
            self.catalog.search('zone:"Stone Hive" type:npc', current_zone="Stone Hive"),
            [],
        )
        self.assertEqual(len(self.catalog.search('zone:"Stone Hive"', current_zone="Stone Hive")), 2)


if __name__ == "__main__":
    unittest.main()
