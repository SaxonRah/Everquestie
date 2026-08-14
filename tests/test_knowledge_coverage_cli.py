import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from tools.audit_knowledge_coverage import main, open_read_only


class KnowledgeCoverageCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "coverage.sqlite3"
        db = Database(self.path)
        try:
            source_id = db.upsert_source_page(
                url="eqclient://coverage",
                title="Coverage source",
                entity_type="skill_cap",
                sha256="coverage",
                plain_text="",
                raw_html="",
                source_name="EverQuest Client",
                source_kind="local_game_files",
                source_key="coverage",
            )
            db.replace_skill_caps(source_id, [(1, 0, 1, 5)])
        finally:
            db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_read_only_rejects_database_writes(self):
        conn = open_read_only(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM skill_caps")
        finally:
            conn.close()

    def test_json_report_is_machine_readable(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.path), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["source_pages"], 1)
        self.assertEqual(payload["normalized_pages"], 1)
        self.assertEqual(payload["relationships"], 0)
        self.assertEqual(payload["providers"][0]["support_rows"], 1)


if __name__ == "__main__":
    unittest.main()
