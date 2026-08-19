from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from tools.recover_allakhazam_temporary_pages import _require_builder_database, main


REPO_ROOT = Path(__file__).resolve().parents[1]
FULL_BUILD = REPO_ROOT / "tools" / "build_full_knowledge.ps1"


class AllakhazamTemporaryRecoveryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.mirror = self.root / "mirror"
        self.mirror.mkdir()
        self.working = self.root / "working.sqlite3"
        db = Database(self.working)
        db.close()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _page() -> str:
        return (
            "<html><head><title>Recovered Sword :: EverQuest :: ZAM</title>"
            '<link rel="canonical" href="https://everquest.allakhazam.com/db/item.html?item=123">'
            "</head><body><h1>Recovered Sword</h1></body></html>"
        )

    def test_cli_recovers_into_existing_builder_database_and_emits_json(self) -> None:
        (self.mirror / "item123.html.tmp").write_text(self._page(), encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                [
                    str(self.mirror),
                    "--database",
                    str(self.working),
                    "--source-version",
                    "test-recovery",
                    "--json",
                ]
            )

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["candidates"], 1)
        self.assertEqual(payload["imported"], 1)
        self.assertEqual(payload["imported_by_kind"], {"item": 1})

        db = Database(self.working)
        try:
            entity = db.entity_by_external_id("item", "item:123")
            self.assertIsNotNone(entity)
            page = db.conn.execute(
                "SELECT source_version,local_path FROM source_pages WHERE url=?",
                ("https://everquest.allakhazam.com/db/item.html?item=123",),
            ).fetchone()
            self.assertEqual(str(page["source_version"]), "test-recovery")
            self.assertTrue(str(page["local_path"]).endswith("item123.html.tmp"))
        finally:
            db.close()

    def test_cli_refuses_finalized_knowledge_snapshot(self) -> None:
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.working,
            snapshot,
            snapshot_version="recovery-boundary-test",
        )

        with self.assertRaisesRegex(ValueError, "refuses finalized immutable"):
            _require_builder_database(snapshot)

    def test_cli_refuses_non_builder_user_style_database(self) -> None:
        state = self.root / "everquestie-user.sqlite3"
        conn = sqlite3.connect(state)
        try:
            conn.execute("CREATE TABLE user_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            conn.commit()
        finally:
            conn.close()

        with self.assertRaisesRegex(ValueError, "not an EverQuestie builder"):
            _require_builder_database(state)

    def test_canonical_full_builder_still_requires_completed_mirror(self) -> None:
        text = FULL_BUILD.read_text(encoding="utf-8")
        self.assertIn("--require-complete", text)
        self.assertIn("--httrack-project $AllakhazamProject", text)
        self.assertNotIn("recover_allakhazam_temporary_pages.py", text)
        self.assertIn("absence of temporary files alone does not prove", text)
        self.assertIn("interrupted, and unknown runs all fail closed", text)


if __name__ == "__main__":
    unittest.main()
