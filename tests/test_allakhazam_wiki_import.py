from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eqquest.db import Database
from eqquest.sources.allakhazam_wiki import AllakhazamWikiImporter


class AllakhazamWikiImporterTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.importer = AllakhazamWikiImporter(self.db)

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    @staticmethod
    def _write_wiki(path: Path, key: str) -> None:
        path.write_text(
            f"""
            <html><head>
              <title>{key.replace('_', ' ')}</title>
              <link rel="canonical" href="https://everquest.allakhazam.com/wiki/{key}">
            </head><body>
              <h1>{key.replace('_', ' ')}</h1>
              <p>Fixture wiki body for {key}.</p>
            </body></html>
            """,
            encoding="utf-8",
        )

    def test_unchanged_wiki_file_uses_fingerprint_before_reading(self):
        mirror = self.root / "wiki"
        mirror.mkdir()
        page = mirror / "cached.html"
        self._write_wiki(page, "Cached_Wiki")

        first = self.importer.import_folder(mirror)
        self.assertEqual(first.imported, 1)
        self.assertEqual(first.processed, 1)

        stored = self.db.conn.execute(
            """
            SELECT local_path,local_mtime_ns,local_size
            FROM source_pages
            WHERE url='https://everquest.allakhazam.com/wiki/Cached_Wiki'
            """
        ).fetchone()
        self.assertEqual(stored["local_path"], str(page.resolve()))
        self.assertGreater(int(stored["local_mtime_ns"]), 0)
        self.assertGreater(int(stored["local_size"]), 0)

        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected file read")):
            second = self.importer.import_folder(mirror)

        self.assertEqual(second.imported, 0)
        self.assertEqual(second.unchanged, 1)
        self.assertEqual(second.processed, 1)

    def test_wiki_import_can_cancel_and_resume(self):
        mirror = self.root / "cancel-wiki"
        mirror.mkdir()
        self._write_wiki(mirror / "one.html", "Cancel_Wiki_One")
        self._write_wiki(mirror / "two.html", "Cancel_Wiki_Two")

        progress_calls: list[int] = []

        def progress(result, _path) -> None:
            progress_calls.append(result.processed)

        first = self.importer.import_folder(
            mirror,
            progress=progress,
            cancelled=lambda: bool(progress_calls),
            progress_every=1,
        )
        self.assertTrue(first.cancelled)
        self.assertEqual(first.processed, 1)
        self.assertEqual(first.imported, 1)

        second = self.importer.import_folder(mirror)
        self.assertFalse(second.cancelled)
        self.assertEqual(second.processed, 2)
        self.assertEqual(second.imported, 1)
        self.assertEqual(second.unchanged, 1)

        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM source_pages WHERE source_name='Allakhazam Wiki'"
            ).fetchone()[0],
            2,
        )


if __name__ == "__main__":
    unittest.main()
