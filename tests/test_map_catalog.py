import tempfile
import threading
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

    def test_search_is_read_only_when_links_are_dirty(self):
        self.catalog.index_root(self.root)
        self.db.set_meta("map_links_dirty", "1")
        hits = self.catalog.search("Warwing")
        self.assertTrue(hits)
        self.assertEqual(self.db.get_meta("map_links_dirty"), "1")


class MapCatalogConcurrencyTests(unittest.TestCase):
    def test_index_does_not_hold_write_lock_between_files(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "catalog.sqlite3"
            root = Path(td) / "maps"
            root.mkdir()
            for stem in ("alpha", "beta"):
                (root / f"{stem}.txt").write_text(
                    f"P 1,2,3,255,0,0,2,{stem}_Label\n",
                    encoding="utf-8",
                )

            main_db = Database(db_path)
            reached_between_files = threading.Event()
            release_worker = threading.Event()
            errors: list[Exception] = []

            def worker() -> None:
                worker_db = Database(db_path)
                try:
                    def progress(stage, current, total, detail):
                        if stage == "index" and current == 1:
                            reached_between_files.set()
                            release_worker.wait(2)

                    MapCatalog(worker_db).index_root(root, progress=progress)
                except Exception as exc:
                    errors.append(exc)
                finally:
                    worker_db.close()

            thread = threading.Thread(target=worker)
            thread.start()
            self.assertTrue(reached_between_files.wait(3))

            # The indexer is deliberately paused between map files. A foreground UI
            # metadata write must still succeed because the previous file transaction
            # has already committed.
            main_db.set_meta("foreground_write", "ok")
            self.assertEqual(main_db.get_meta("foreground_write"), "ok")

            release_worker.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            main_db.close()


if __name__ == "__main__":
    unittest.main()
