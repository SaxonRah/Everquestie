import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from eqquest.allakhazam_mirror_audit import (
    allakhazam_mirror_audit_text,
    audit_allakhazam_mirror,
)
from tools.audit_allakhazam_mirror import main


class AllakhazamMirrorAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

        self._write(
            "quest-a.html",
            self._canonical("https://everquest.allakhazam.com/db/quest.html?quest=123"),
        )
        self._write(
            "nested/quest-duplicate.htm",
            self._canonical("https://everquest.allakhazam.com/db/quest.html?quest=123"),
        )
        self._write(
            "npc.html",
            self._canonical("https://everquest.allakhazam.com/db/npc.html?id=44"),
        )
        self._write(
            "item.html",
            self._canonical("https://everquest.allakhazam.com/db/item.html?item=55"),
        )
        self._write(
            "zone.html",
            self._canonical("https://everquest.allakhazam.com/db/zone.html?zstrat=66"),
        )
        self._write(
            "search.html",
            self._canonical("https://everquest.allakhazam.com/search.html?q=fungus"),
        )
        self._write("no-canonical.html", "<html><title>Saved helper</title></html>")
        self._write(
            "still-writing.html.tmp",
            self._canonical("https://everquest.allakhazam.com/db/npc.html?id=999"),
        )
        self._write_bytes("images/icon.png", b"not really a png; fixture asset")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _canonical(url: str) -> str:
        return f'<html><head><link rel="canonical" href="{url}"></head><body>fixture</body></html>'

    def _write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _write_bytes(self, relative: str, data: bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def test_audit_separates_raw_files_from_unique_structured_pages(self):
        audit = audit_allakhazam_mirror(self.root)

        self.assertEqual(audit.all_files, 9)
        self.assertEqual(audit.html_candidates, 8)
        self.assertEqual(audit.temporary_files, 1)
        self.assertEqual(audit.readable_files, 7)
        self.assertEqual(audit.read_errors, 0)
        self.assertEqual(audit.canonical_files, 6)
        self.assertEqual(audit.unique_canonical_pages, 5)
        self.assertEqual(audit.duplicate_canonical_files, 1)
        self.assertEqual(audit.importable_pages, 4)
        self.assertEqual(audit.missing_canonical, 1)
        self.assertEqual(audit.unclassified_canonical, 1)
        self.assertEqual(
            dict(audit.pages_by_kind),
            {"item": 1, "npc": 1, "quest": 1, "zone": 1},
        )
        self.assertEqual(
            audit.duplicate_urls,
            (("https://everquest.allakhazam.com/db/quest.html?quest=123", 2),),
        )

    def test_human_report_explains_httrack_file_count_boundary(self):
        text = allakhazam_mirror_audit_text(self.root)
        self.assertIn("All mirror files: 9", text)
        self.assertIn("HTML-like files discovered: 8", text)
        self.assertIn("Unique quest/NPC/item/zone pages ready for structured import: 4", text)
        self.assertIn("quest: 1", text)
        self.assertIn("2 files -> https://everquest.allakhazam.com/db/quest.html?quest=123", text)
        self.assertIn("HTTrack/raw mirror file count includes assets and helper pages", text)

    def test_json_cli_is_machine_readable_and_does_not_create_database_files(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["all_files"], 9)
        self.assertEqual(payload["importable_pages"], 4)
        self.assertEqual(payload["pages_by_kind"]["quest"], 1)
        self.assertFalse(any(path.suffix in {".db", ".sqlite", ".sqlite3"} for path in self.root.rglob("*")))

    def test_missing_folder_fails_cleanly(self):
        with self.assertRaises(FileNotFoundError):
            audit_allakhazam_mirror(self.root / "missing")


if __name__ == "__main__":
    unittest.main()
