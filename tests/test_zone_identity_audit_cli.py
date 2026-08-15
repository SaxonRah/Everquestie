import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from tools.audit_zone_identities import main, open_read_only


class ZoneIdentityAuditCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "zone-identities.sqlite3"
        db = Database(self.path)
        try:
            db.upsert_entity(
                kind="zone",
                name="Stone Hive",
                external_id="396",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            db.upsert_entity(
                kind="zone",
                name="Stone Hive",
                external_id="zone:1",
                external_namespace="allakhazam:zone",
                merge_by_name=False,
            )
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

    def test_json_report_exposes_unique_client_authority_collision(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.path), "--json", "--examples", "10"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["zone_entities"], 2)
        self.assertEqual(payload["duplicate_name_groups"], 1)
        self.assertEqual(payload["client_authority_duplicate_groups"], 1)
        self.assertEqual(payload["client_authority_shadow_entities"], 1)
        self.assertEqual(payload["groups"][0]["classification"], "client_authority_duplicate")

    def test_human_report_is_readable(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.path), "--examples", "10"])
        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("EverQuestie canonical zone identity audit", text)
        self.assertIn("Stone Hive", text)
        self.assertIn("client_authority_duplicate", text)


if __name__ == "__main__":
    unittest.main()
