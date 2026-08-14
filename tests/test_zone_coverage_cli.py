import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.zone_travel import ZoneTravelCatalog
from tools.audit_zone_coverage import main, open_read_only


class ZoneCoverageCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "zone-coverage.sqlite3"
        db = Database(self.path)
        try:
            source = db.upsert_source_page(
                url="eqclient://zones",
                title="ZoneNames",
                entity_type="zone",
                sha256="zones",
                plain_text="",
                raw_html="",
                source_name="EverQuest Client",
                source_kind="local_game_files",
                source_key="Resources/ZoneNames.txt",
            )
            stone = db.upsert_entity(
                kind="zone",
                name="Stone Hive",
                source_page_id=source,
                source_url="eqclient://zones",
                external_id="396",
                external_namespace="eqclient:zone",
                merge_by_name=True,
            )
            blightfire = db.upsert_entity(
                kind="zone",
                name="Blightfire Moors",
                source_page_id=source,
                source_url="eqclient://zones",
                external_id="395",
                external_namespace="eqclient:zone",
                merge_by_name=True,
            )
            ZoneTravelCatalog(db).add_provider_connection(
                stone,
                blightfire,
                source_name="Fixture",
                source_kind="provider",
                source_key="stone-blightfire",
                evidence="To Blightfire Moors",
            )
        finally:
            db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_read_only_rejects_database_writes(self):
        conn = open_read_only(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM entities")
        finally:
            conn.close()

    def test_json_report_exposes_route_graph_connectivity(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.path), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["coverage_version"], "3")
        self.assertEqual(payload["zones"], 2)
        self.assertEqual(payload["route_zones"], 2)
        self.assertEqual(payload["route_weak_components"], 1)
        self.assertEqual(payload["route_strong_components"], 2)
        self.assertEqual(payload["largest_strong_route_component"], 1)
        self.assertEqual(payload["route_sink_zones"], ["Blightfire Moors"])

    def test_human_report_names_connectivity_and_sink(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.path)])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("Zone coverage v3", text)
        self.assertIn("Route graph: zones=2/2, weak components=1", text)
        self.assertIn("Directed route sinks", text)
        self.assertIn("Blightfire Moors", text)


if __name__ == "__main__":
    unittest.main()
