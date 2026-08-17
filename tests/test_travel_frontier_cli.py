import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.zone_catalog import ZoneMapCatalog
from tools.audit_travel_frontier import main, open_read_only


class TravelFrontierCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "travel-frontier.sqlite3"
        maps = self.root / "maps"
        maps.mkdir()
        # Connection forms graduated into production travel syntax in catalog v3.
        # This fixture intentionally stops before travel reconciliation so the read-only
        # audit must report a current compiler candidate whose stored edge is missing.
        (maps / "stonehive.txt").write_text(
            "P 10,20,3,255,0,0,2,Connection_to_Blightfire_Moors\n",
            encoding="utf-8",
        )

        db = Database(self.path)
        try:
            db.upsert_entity(
                kind="zone",
                name="Stone Hive",
                merge_by_name=True,
                data={"map_short_name": "stonehive"},
            )
            db.upsert_entity(
                kind="zone",
                name="Blightfire Moors",
                merge_by_name=True,
                data={"map_short_name": "blightfire"},
            )
            MapCatalog(db).index_root(maps, source_name="Good's Maps")
            ZoneMapCatalog(db).reconcile(source_name="Good's Maps")
        finally:
            db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_read_only_rejects_writes(self):
        conn = open_read_only(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM entities")
        finally:
            conn.close()

    def test_json_report_exposes_current_candidate_missing_stored_edge(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.path), "--json", "--examples", "5"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["current_explicit_candidates"], 1)
        self.assertEqual(payload["current_explicit_linked"], 1)
        self.assertEqual(payload["current_explicit_unresolved"], 0)
        self.assertEqual(payload["current_explicit_missing_stored_edge"], 1)
        self.assertEqual(payload["frontier_explicit"], 0)
        self.assertEqual(payload["frontier_explicit_linked"], 0)
        self.assertEqual(payload["examples"], [])

    def test_human_report_is_readable(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.path), "--examples", "5"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("EverQuestie travel frontier audit", text)
        self.assertIn("explicit candidates: 1", text)
        self.assertIn("explicit candidates missing stored edge: 1", text)
        self.assertIn("additional explicit travel spellings: 0", text)
        self.assertNotIn("[unsupported_explicit]", text)


if __name__ == "__main__":
    unittest.main()
