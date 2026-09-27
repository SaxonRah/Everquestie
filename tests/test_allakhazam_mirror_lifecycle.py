from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eqquest.allakhazam_mirror_importer import AllakhazamMirrorImporter
from eqquest.db import Database
from eqquest.entity_lifecycle import entity_expansion_evidence
from eqquest.world_profiles import p99_expansion_allowed


class AllakhazamMirrorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.importer = AllakhazamMirrorImporter(self.db)

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_quest_era_is_preserved_as_top_level_lifecycle_evidence(self):
        path = self.root / "quest.html"
        path.write_text(
            """
            <html><head>
              <title>Lifecycle Quest :: EverQuest</title>
              <link rel="canonical" href="https://everquest.allakhazam.com/db/quest.html?quest=12">
            </head><body>
              <h1>Lifecycle Quest</h1>
              <table>
                <tr><td><strong>Quest Started By:</strong></td><td>Nobody</td></tr>
                <tr><td><strong>Description:</strong></td><td>Fixture description</td></tr>
                <tr><td><strong>Era:</strong></td><td>Original</td></tr>
              </table>
            </body></html>
            """,
            encoding="utf-8",
        )

        result = self.importer.import_saved_html(path)
        row = self.db.entity(result.entity_id)
        data = json.loads(row["data_json"] or "{}")

        self.assertEqual(data["era"], "Original")
        evidence = entity_expansion_evidence(self.db, result.entity_id)
        self.assertEqual(tuple(record.expansion for record in evidence), ("Original",))
        self.assertIs(p99_expansion_allowed("Original"), True)

    def test_item_expansion_is_preserved_as_top_level_lifecycle_evidence(self):
        path = self.root / "item.html"
        path.write_text(
            """
            <html><head>
              <title>Lifecycle Item :: EverQuest</title>
              <link rel="canonical" href="https://everquest.allakhazam.com/db/item.html?item=34">
            </head><body>
              <h1>Lifecycle Item</h1>
              <table id="sortableTable0">
                <tr><td>Item Type:</td><td>Armor</td></tr>
                <tr><td>Expansion:</td><td>Scars of Velious</td></tr>
                <tr><td>Page Updated:</td><td>2026-01-01</td></tr>
              </table>
            </body></html>
            """,
            encoding="utf-8",
        )

        result = self.importer.import_saved_html(path)
        row = self.db.entity(result.entity_id)
        data = json.loads(row["data_json"] or "{}")

        self.assertEqual(data["expansion"], "Scars of Velious")
        self.assertEqual(data["metadata"]["Expansion"], "Scars of Velious")
        evidence = entity_expansion_evidence(self.db, result.entity_id)
        self.assertEqual(tuple(record.expansion for record in evidence), ("Scars of Velious",))
        self.assertIs(p99_expansion_allowed("Scars of Velious"), True)

    def test_mirror_refresh_skips_unchanged_file_before_reading_or_hashing(self):
        mirror = self.root / "mirror"
        mirror.mkdir()
        path = mirror / "cached-quest.html"
        path.write_text(
            """
            <html><head>
              <title>Cached Quest :: EverQuest</title>
              <link rel="canonical" href="https://everquest.allakhazam.com/db/quest.html?quest=998877">
            </head><body>
              <h1>Cached Quest</h1>
              <table>
                <tr><td><strong>Quest Started By:</strong></td><td>Nobody</td></tr>
              </table>
            </body></html>
            """,
            encoding="utf-8",
        )

        first = self.importer.import_mirror(mirror)
        self.assertEqual(first.changed, 1)

        stored = self.db.conn.execute(
            """
            SELECT local_path,local_mtime_ns,local_size
            FROM source_pages
            WHERE url='https://everquest.allakhazam.com/db/quest.html?quest=998877'
            """
        ).fetchone()
        self.assertEqual(stored["local_path"], str(path.resolve()))
        self.assertGreater(int(stored["local_mtime_ns"]), 0)
        self.assertGreater(int(stored["local_size"]), 0)

        # The second refresh must use stat + indexed fingerprint lookup. If it tries
        # to decode/hash the HTML again, this patched read fails the test.
        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected file read")):
            second = self.importer.import_mirror(mirror)

        self.assertEqual(second.changed, 0)
        self.assertEqual(second.unchanged, 1)

    def test_mirror_import_can_cancel_and_resume_without_discarding_completed_pages(self):
        mirror = self.root / "cancel-mirror"
        mirror.mkdir()

        for index in (1, 2):
            (mirror / f"quest-{index}.html").write_text(
                f"""
                <html><head>
                  <title>Cancel Quest {index} :: EverQuest</title>
                  <link rel="canonical" href="https://everquest.allakhazam.com/db/quest.html?quest=8800{index}">
                </head><body>
                  <h1>Cancel Quest {index}</h1>
                  <table>
                    <tr><td><strong>Quest Started By:</strong></td><td>Nobody</td></tr>
                  </table>
                </body></html>
                """,
                encoding="utf-8",
            )

        progress_calls: list[int] = []

        def progress(summary, _path) -> None:
            progress_calls.append(summary.processed)

        first = self.importer.import_mirror(
            mirror,
            progress=progress,
            cancelled=lambda: bool(progress_calls),
            progress_every=1,
        )

        self.assertTrue(first.cancelled)
        self.assertEqual(first.processed, 1)
        self.assertEqual(first.changed, 1)
        self.assertIn(1, progress_calls)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM source_pages WHERE source_name='Allakhazam'"
            ).fetchone()[0],
            1,
        )

        second = self.importer.import_mirror(mirror)
        self.assertFalse(second.cancelled)
        self.assertEqual(second.processed, 2)
        self.assertEqual(second.changed, 1)
        self.assertEqual(second.unchanged, 1)
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM source_pages WHERE source_name='Allakhazam'"
            ).fetchone()[0],
            2,
        )

    def test_dates_are_not_promoted_when_explicit_lifecycle_field_is_absent(self):
        path = self.root / "item-no-expansion.html"
        path.write_text(
            """
            <html><head>
              <title>Undetermined Item :: EverQuest</title>
              <link rel="canonical" href="https://everquest.allakhazam.com/db/item.html?item=35">
            </head><body>
              <h1>Undetermined Item</h1>
              <table id="sortableTable0">
                <tr><td>IC Last Updated:</td><td>2026-08-16</td></tr>
                <tr><td>Page Updated:</td><td>2026-08-16</td></tr>
              </table>
            </body></html>
            """,
            encoding="utf-8",
        )

        result = self.importer.import_saved_html(path)
        row = self.db.entity(result.entity_id)
        data = json.loads(row["data_json"] or "{}")

        self.assertNotIn("expansion", data)
        self.assertNotIn("era", data)
        self.assertEqual(entity_expansion_evidence(self.db, result.entity_id), ())


if __name__ == "__main__":
    unittest.main()
