from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eqquest.allakhazam_mirror_importer import AllakhazamMirrorImporter
from eqquest.allakhazam_temporary_audit import audit_allakhazam_temporary_pages
from eqquest.allakhazam_temporary_recovery import recover_allakhazam_temporary_pages
from eqquest.db import Database


class AllakhazamTemporaryRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.mirror = self.root / "mirror"
        self.mirror.mkdir()
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.tempdir.cleanup()

    @staticmethod
    def _page(canonical: str, title: str, body: str = "") -> str:
        return (
            "<html><head>"
            f"<title>{title} :: EverQuest :: ZAM</title>"
            f'<link rel="canonical" href="{canonical}">'
            "</head><body>"
            f"<h1>{title}</h1>{body}"
            "</body></html>"
        )

    def _write_temp(self, name: str, canonical: str, title: str, body: str = "") -> Path:
        path = self.mirror / name
        path.write_text(self._page(canonical, title, body), encoding="utf-8")
        return path

    def test_normal_mirror_import_still_ignores_complete_temporary_pages(self) -> None:
        self._write_temp(
            "item123.html.tmp",
            "https://everquest.allakhazam.com/db/item.html?item=123",
            "Recovered Sword",
        )

        summary = AllakhazamMirrorImporter(self.db).import_mirror(self.mirror)

        self.assertEqual(summary.changed, 0)
        self.assertEqual(summary.ignored, 1)
        self.assertIsNone(self.db.entity_by_external_id("item", "item:123"))

    def test_explicit_recovery_imports_complete_item_and_quest_pages(self) -> None:
        self._write_temp(
            "item123.html.tmp",
            "https://everquest.allakhazam.com/db/item.html?item=123",
            "Recovered Sword",
        )
        self._write_temp(
            "quest456.html.tmp",
            "https://everquest.allakhazam.com/db/quest.html?quest=456",
            "Recovered Quest",
        )

        audit = audit_allakhazam_temporary_pages(self.mirror)
        result = recover_allakhazam_temporary_pages(
            self.db,
            self.mirror,
            source_version="recovery-capture-2026-08-17",
        )

        self.assertEqual(audit.likely_complete_structured_files, 2)
        self.assertEqual(result.candidates, 2)
        self.assertEqual(result.changed, 2)
        self.assertEqual(
            {(entry.kind, entry.external_id) for entry in result.imported},
            {("item", "item:123"), ("quest", "quest:456")},
        )
        self.assertIsNotNone(self.db.entity_by_external_id("item", "item:123"))
        self.assertIsNotNone(self.db.entity_by_external_id("quest", "quest:456"))

        versions = self.db.conn.execute(
            "SELECT DISTINCT source_version FROM source_pages WHERE source_name='Allakhazam'"
        ).fetchall()
        self.assertEqual(
            {str(row["source_version"]) for row in versions},
            {"recovery-capture-2026-08-17"},
        )

    def test_truncated_structured_page_is_never_recovered(self) -> None:
        path = self.mirror / "item123.html.tmp"
        path.write_text(
            "<html><head><title>Truncated Sword</title>"
            '<link rel="canonical" href="https://everquest.allakhazam.com/db/item.html?item=123">'
            "</head><body><h1>Truncated Sword</h1>",
            encoding="utf-8",
        )

        result = recover_allakhazam_temporary_pages(self.db, self.mirror)

        self.assertEqual(result.candidates, 0)
        self.assertEqual(result.changed, 0)
        self.assertEqual(result.by_status["structured_missing_document_end"], 1)
        self.assertIsNone(self.db.entity_by_external_id("item", "item:123"))

    def test_completed_page_duplicate_always_wins_over_temporary_copy(self) -> None:
        canonical = "https://everquest.allakhazam.com/db/item.html?item=123"
        (self.mirror / "item123.html").write_text(
            self._page(canonical, "Final Sword"),
            encoding="utf-8",
        )
        self._write_temp("item123-copy.html.tmp", canonical, "Temporary Sword")

        result = recover_allakhazam_temporary_pages(self.db, self.mirror)

        self.assertEqual(result.changed, 0)
        self.assertEqual(result.by_status["structured_duplicate_of_completed_page"], 1)
        self.assertIsNone(self.db.entity_by_external_id("item", "item:123"))

    def test_duplicate_temporary_canonical_is_imported_only_once(self) -> None:
        canonical = "https://everquest.allakhazam.com/db/item.html?item=123"
        self._write_temp("item123-a.html.tmp", canonical, "Recovered Sword")
        self._write_temp("item123-b.html.tmp", canonical, "Recovered Sword")

        result = recover_allakhazam_temporary_pages(self.db, self.mirror)

        self.assertEqual(result.candidates, 2)
        self.assertEqual(result.changed, 1)
        self.assertEqual(result.skipped_duplicate_temporary, 1)
        rows = self.db.conn.execute(
            "SELECT COUNT(*) FROM source_pages WHERE url=? AND source_name='Allakhazam'",
            (canonical,),
        ).fetchone()
        self.assertEqual(int(rows[0]), 1)

    def test_candidate_that_changes_during_full_read_is_rejected(self) -> None:
        path = self._write_temp(
            "item123.html.tmp",
            "https://everquest.allakhazam.com/db/item.html?item=123",
            "Recovered Sword",
        )
        raw = path.read_text(encoding="utf-8")

        with patch(
            "eqquest.allakhazam_temporary_recovery._stable_full_read",
            return_value=(raw, True),
        ):
            result = recover_allakhazam_temporary_pages(self.db, self.mirror)

        self.assertEqual(result.candidates, 1)
        self.assertEqual(result.changed, 0)
        self.assertEqual(result.skipped_unstable, 1)
        self.assertIsNone(self.db.entity_by_external_id("item", "item:123"))


if __name__ == "__main__":
    unittest.main()
