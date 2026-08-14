import tempfile
import unittest
from pathlib import Path

from eqquest.eqmap import load_zone_map
from eqquest.map_search import find_map_label_hits


class MapSearchTests(unittest.TestCase):
    def _map(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "stonehive.txt").write_text(
            "P -100,-200,15,255,0,0,2,Warwing_Wendlez_(Q)\n"
            "P -300,-400,5,0,255,0,2,Other_Merchant\n",
            encoding="utf-8",
        )
        return tmp, load_zone_map(root / "stonehive.txt")

    def test_decorated_label_matches_clean_name(self):
        tmp, zone_map = self._map()
        try:
            hits = find_map_label_hits(zone_map, "Warwing Wendlez", current_zone="Stone Hive")
            self.assertEqual(hits[0].text, "Warwing Wendlez (Q)")
            self.assertEqual(hits[0].reason, "map label exact")
        finally:
            tmp.cleanup()

    def test_structured_query_still_surfaces_unclassified_map_candidate(self):
        tmp, zone_map = self._map()
        try:
            hits = find_map_label_hits(
                zone_map,
                'type:npc zone:"Stone Hive" Warwing',
                current_zone="Stone Hive",
            )
            self.assertEqual(hits[0].text, "Warwing Wendlez (Q)")
            self.assertIn("type unclassified", hits[0].reason)
        finally:
            tmp.cleanup()

    def test_wrong_zone_does_not_match(self):
        tmp, zone_map = self._map()
        try:
            hits = find_map_label_hits(
                zone_map,
                'zone:"Blightfire Moors" Warwing',
                current_zone="Stone Hive",
            )
            self.assertEqual(hits, [])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
