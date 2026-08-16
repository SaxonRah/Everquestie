from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

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
