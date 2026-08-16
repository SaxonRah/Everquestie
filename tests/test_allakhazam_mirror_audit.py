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
            "spell-with-expansion.html",
            self._spell_page(111, "Malaisement", "Original"),
        )
        self._write(
            "spell-without-expansion.html",
            self._spell_page(222, "Later Spell", None),
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

    @staticmethod
    def _spell_page(spell_id: int, name: str, expansion: str | None) -> str:
        expansion_row = (
            f'<div><b>Expansion:</b><img alt="{expansion}" src="/images/expansion.gif"></div>'
            if expansion
            else '<div><b>Duration:</b><span>7.4 mins</span></div>'
        )
        return f"""
        <html>
          <head>
            <title>{name} :: Spells :: EverQuest :: ZAM</title>
            <link rel="canonical" href="https://everquest.allakhazam.com/db/spell.html?spell={spell_id}">
          </head>
          <body>
            <h1>{name}</h1>
            <section class="spell-facts">
              <h3>Quick Facts</h3>
              <div><b>Scroll:</b> Spell: {name}</div>
              {expansion_row}
            </section>
            <h3>Comments</h3>
            <p>Expansion: The Serpent's Spine in player prose must not count.</p>
          </body>
        </html>
        """

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

        self.assertEqual(audit.all_files, 11)
        self.assertEqual(audit.html_candidates, 10)
        self.assertEqual(audit.temporary_files, 1)
        self.assertEqual(audit.readable_files, 9)
        self.assertEqual(audit.read_errors, 0)
        self.assertEqual(audit.canonical_files, 8)
        self.assertEqual(audit.unique_canonical_pages, 7)
        self.assertEqual(audit.duplicate_canonical_files, 1)
        self.assertEqual(audit.importable_pages, 6)
        self.assertEqual(audit.missing_canonical, 1)
        self.assertEqual(audit.unclassified_canonical, 1)
        self.assertEqual(
            dict(audit.pages_by_kind),
            {"spell": 2, "item": 1, "npc": 1, "quest": 1, "zone": 1},
        )
        self.assertEqual(audit.spell_pages, 2)
        self.assertEqual(audit.spell_pages_with_expansion, 1)
        self.assertEqual(audit.spell_pages_missing_expansion, 1)
        self.assertEqual(
            audit.duplicate_urls,
            (("https://everquest.allakhazam.com/db/quest.html?quest=123", 2),),
        )

    def test_spell_coverage_uses_structured_quick_facts_not_comment_prose(self):
        audit = audit_allakhazam_mirror(self.root)
        self.assertEqual(audit.spell_pages, 2)
        self.assertEqual(audit.spell_pages_with_expansion, 1)
        self.assertEqual(audit.spell_pages_missing_expansion, 1)

    def test_human_report_explains_httrack_file_count_boundary_and_spell_coverage(self):
        text = allakhazam_mirror_audit_text(self.root)
        self.assertIn("All mirror files: 11", text)
        self.assertIn("HTML-like files discovered: 10", text)
        self.assertIn("Unique structured pages ready for import: 6", text)
        self.assertIn("spell: 2", text)
        self.assertIn("With reviewed Quick Facts Expansion: 1", text)
        self.assertIn("Missing reviewed Quick Facts Expansion: 1", text)
        self.assertIn("2 files -> https://everquest.allakhazam.com/db/quest.html?quest=123", text)
        self.assertIn("HTTrack/raw mirror file count includes assets and helper pages", text)

    def test_json_cli_is_machine_readable_and_does_not_create_database_files(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["all_files"], 11)
        self.assertEqual(payload["importable_pages"], 6)
        self.assertEqual(payload["pages_by_kind"]["quest"], 1)
        self.assertEqual(payload["pages_by_kind"]["spell"], 2)
        self.assertEqual(payload["spell_pages_with_expansion"], 1)
        self.assertEqual(payload["spell_pages_missing_expansion"], 1)
        self.assertFalse(any(path.suffix in {".db", ".sqlite", ".sqlite3"} for path in self.root.rglob("*")))

    def test_output_writes_atomic_json_artifact_and_reuses_one_scan(self):
        # Put the report under the mirror on purpose. The production full build writes
        # it elsewhere, but this proves human + JSON output came from the same initial
        # scan: a second scan after writing the JSON would report 12 total files.
        output = self.root / "reports" / "nested" / "allakhazam-mirror-audit.json"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.root), "--output", str(output)])

        self.assertEqual(code, 0)
        self.assertTrue(output.is_file())
        self.assertFalse(output.with_name(output.name + ".tmp").exists())
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["all_files"], 11)
        self.assertEqual(payload["pages_by_kind"]["spell"], 2)
        self.assertEqual(payload["spell_pages_with_expansion"], 1)
        self.assertIn("All mirror files: 11", stdout.getvalue())
        self.assertEqual(sum(1 for path in self.root.rglob("*") if path.is_file()), 12)
        self.assertFalse(any(path.suffix in {".db", ".sqlite", ".sqlite3"} for path in self.root.rglob("*")))

    def test_missing_folder_fails_cleanly(self):
        with self.assertRaises(FileNotFoundError):
            audit_allakhazam_mirror(self.root / "missing")


if __name__ == "__main__":
    unittest.main()
