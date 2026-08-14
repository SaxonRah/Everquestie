from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.local_search import (
    count_local_entities_by_kind,
    map_label_terms,
    parse_local_query,
    resolve_local_hits,
    search_local_hits,
)


class LocalSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "search.sqlite3")
        zone_id = self.db.upsert_entity(kind="zone", name="Stone Hive", merge_by_name=True)
        self.npc_id = self.db.upsert_entity(kind="npc", name="Waning Wendlez", zone="Stone Hive", merge_by_name=True)
        self.db.add_alias(self.npc_id, "Wendlez")
        self.db.add_location(self.npc_id, zone_entity_id=zone_id, y=100, x=200)
        self.spell_id = self.db.upsert_entity(kind="spell", name="Waning Light", merge_by_name=True)
        self.db.rebuild_search_index()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_query_parser(self):
        q = parse_local_query('type:npc zone:"Stone Hive" exact:"Waning Wendlez"')
        self.assertEqual(q.kinds, ("npc",))
        self.assertEqual(q.zone, "Stone Hive")
        self.assertEqual(q.text, "Waning Wendlez")
        self.assertTrue(q.exact)

    def test_current_zone_and_exact_name_rank_first(self):
        hits = search_local_hits(self.db, "Waning", current_zone="Stone Hive")
        self.assertTrue(hits)
        self.assertEqual(int(hits[0].row["id"]), self.npc_id)
        self.assertIn("current zone", hits[0].reason)

    def test_type_and_zone_filter(self):
        hits = search_local_hits(self.db, 'type:npc zone:"Stone Hive" Waning')
        self.assertEqual([int(hit.row["id"]) for hit in hits], [self.npc_id])
        counts = count_local_entities_by_kind(self.db, 'zone:"Stone Hive" Waning')
        self.assertEqual({r["kind"]: r["count"] for r in counts}, {"npc": 1})

    def test_map_label_cleanup_and_resolver(self):
        self.assertIn("Waning Wendlez", map_label_terms("Waning Wendlez (Q)"))
        self.assertIn("Blightfire Moors", map_label_terms("To Blightfire Moors"))
        hits = resolve_local_hits(self.db, "Waning Wendlez (Q)", current_zone="Stone Hive")
        self.assertTrue(hits)
        self.assertEqual(int(hits[0].row["id"]), self.npc_id)
        self.assertEqual(hits[0].reason.split(" ·", 1)[0], "exact name")


if __name__ == "__main__":
    unittest.main()
