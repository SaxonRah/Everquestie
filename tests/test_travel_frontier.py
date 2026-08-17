from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.travel_frontier import TravelFrontierAudit, travel_frontier_audit_text
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


class TravelFrontierAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.maps = self.root / "maps"
        self.maps.mkdir()
        self.db = Database(self.root / "knowledge.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _zone(self, name: str, stem: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            merge_by_name=True,
            data={"map_short_name": stem},
        )

    def _write_map(self, stem: str, labels: list[str]) -> None:
        lines = [
            f"P {index * 10},{index * 20},3,255,0,0,2,{label}"
            for index, label in enumerate(labels, start=1)
        ]
        (self.maps / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _index(self) -> None:
        MapCatalog(self.db).index_root(self.maps, source_name="Good's Maps")
        ZoneMapCatalog(self.db).reconcile(source_name="Good's Maps")

    def test_audit_separates_current_compiler_and_bare_zone_labels(self):
        stone = self._zone("Stone Hive", "stonehive")
        blight = self._zone("Blightfire Moors", "blightfire")
        mesa = self._zone("Goru'kar Mesa", "gorukar")
        crescent = self._zone("Crescent Reach", "crescent")
        self._write_map(
            "stonehive",
            [
                # All six forms below are production compiler v3 syntax.
                "To_Blightfire_Moors",
                "ZL_to_Goru'kar_Mesa",
                "Portal:_Crescent_Reach",
                "ZL_to_Not_A_Zone",
                "Connection_to_Crescent_Reach",
                "Boundary_to_Blightfire_Moors",
                # Exact zone name alone stays audit-only because it may be a landmark.
                "Blightfire_Moors",
                "Bank",
            ],
        )
        self._index()
        stats = ZoneTravelCatalog(self.db).reconcile_from_maps(source_name="Good's Maps")
        self.assertEqual(stats.candidates, 6)
        self.assertEqual(stats.linked, 5)
        self.assertEqual(stats.unresolved, 1)
        self.assertEqual(ZoneTravelCatalog(self.db).shortest_path(stone, blight), [stone, blight])
        self.assertEqual(ZoneTravelCatalog(self.db).shortest_path(stone, mesa), [stone, mesa])
        self.assertEqual(ZoneTravelCatalog(self.db).shortest_path(stone, crescent), [stone, crescent])

        rows = self.db.conn.execute(
            """
            SELECT evidence,connection_kind,bidirectional
            FROM zone_travel_edges
            WHERE source_kind='map_label' AND evidence IN (?,?)
            ORDER BY evidence
            """,
            ("Connection to Crescent Reach", "Boundary to Blightfire Moors"),
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["connection_kind"] == "zone_line" for row in rows))
        self.assertTrue(all(not row["bidirectional"] for row in rows))

        summary = TravelFrontierAudit(self.db).summary()
        self.assertEqual(summary.map_labels_total, 8)
        self.assertEqual(summary.labels_on_linked_zone_maps, 8)
        self.assertEqual(summary.stored_map_travel_rows, 6)
        self.assertEqual(summary.current_explicit_candidates, 6)
        self.assertEqual(summary.current_explicit_linked, 5)
        self.assertEqual(summary.current_explicit_unresolved, 1)
        self.assertEqual(summary.current_explicit_missing_stored_edge, 0)
        self.assertEqual(summary.current_explicit_status_drift, 0)
        self.assertEqual(summary.frontier_explicit, 0)
        self.assertEqual(summary.frontier_explicit_linked, 0)
        self.assertEqual(summary.frontier_explicit_unresolved, 0)
        self.assertEqual(summary.frontier_bare_zone_labels, 1)
        self.assertEqual(summary.source_frontier_counts, (("Good's Maps", 1),))
        self.assertEqual(summary.unresolved_destinations, (("Not A Zone", 1),))

        categories = [example.category for example in summary.examples]
        self.assertEqual(categories.count("unsupported_explicit"), 0)
        self.assertEqual(categories.count("bare_zone_label"), 1)
        linked_targets = {example.target_zone for example in summary.examples if example.target_zone}
        self.assertEqual(linked_targets, {"Blightfire Moors"})

    def test_current_explicit_candidate_missing_stored_edge_is_detected_read_only(self):
        self._zone("Stone Hive", "stonehive")
        self._zone("Blightfire Moors", "blightfire")
        self._write_map("stonehive", ["Connection_to_Blightfire_Moors"])
        self._index()

        summary = TravelFrontierAudit(self.db).summary()
        self.assertEqual(summary.current_explicit_candidates, 1)
        self.assertEqual(summary.current_explicit_linked, 1)
        self.assertEqual(summary.stored_map_travel_rows, 0)
        self.assertEqual(summary.current_explicit_missing_stored_edge, 1)
        self.assertEqual(summary.frontier_explicit, 0)

    def test_plain_non_zone_map_labels_are_not_promoted_to_frontier(self):
        self._zone("Stone Hive", "stonehive")
        self._zone("Blightfire Moors", "blightfire")
        self._write_map("stonehive", ["Bank", "A_Stone_Worker", "Tradeskills"])
        self._index()

        summary = TravelFrontierAudit(self.db).summary()
        self.assertEqual(summary.current_explicit_candidates, 0)
        self.assertEqual(summary.frontier_explicit, 0)
        self.assertEqual(summary.frontier_bare_zone_labels, 0)
        self.assertEqual(summary.examples, ())

    def test_human_report_explains_audit_only_bare_zone_names(self):
        self._zone("Stone Hive", "stonehive")
        self._zone("Blightfire Moors", "blightfire")
        self._write_map("stonehive", ["Blightfire_Moors"])
        self._index()

        text = travel_frontier_audit_text(self.db)
        self.assertIn("EverQuestie travel frontier audit", text)
        self.assertIn("additional explicit travel spellings: 0", text)
        self.assertIn("bare labels that exactly name another canonical zone: 1", text)
        self.assertIn("bare_zone_label", text)
        self.assertIn("Blightfire Moors", text)


if __name__ == "__main__":
    unittest.main()
