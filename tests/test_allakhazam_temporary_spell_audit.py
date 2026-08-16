from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.allakhazam_temporary_audit import audit_allakhazam_temporary_pages


class AllakhazamTemporarySpellAuditTests(unittest.TestCase):
    @staticmethod
    def _page(url: str) -> str:
        return (
            '<html><head><link rel="canonical" href="'
            + url
            + '"></head><body>fixture</body></html>'
        )

    def test_numeric_spell_temp_page_uses_production_spell_identity_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "spell1234.html.tmp").write_text(
                self._page("https://everquest.allakhazam.com/db/spell.html?spell=789"),
                encoding="utf-8",
            )

            report = audit_allakhazam_temporary_pages(root)

            self.assertEqual(report.temporary_files, 1)
            self.assertEqual(report.structured_canonical_files, 1)
            self.assertEqual(report.likely_complete_structured_files, 1)
            self.assertEqual(dict(report.by_filename_family), {"spell": 1})
            self.assertEqual(dict(report.by_canonical_kind), {"spell": 1})
            self.assertEqual(dict(report.by_status), {"likely_complete_structured": 1})

    def test_nonnumeric_spell_lookalike_is_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "spell-lookalike.html.tmp").write_text(
                self._page("https://everquest.allakhazam.com/db/spell.html?spell=abc"),
                encoding="utf-8",
            )

            report = audit_allakhazam_temporary_pages(root)

            self.assertEqual(report.files_with_canonical_url, 1)
            self.assertEqual(report.structured_canonical_files, 0)
            self.assertEqual(dict(report.by_filename_family), {"spell": 1})
            self.assertEqual(dict(report.by_canonical_kind), {})
            self.assertEqual(dict(report.by_status), {"canonical_other_with_document_end": 1})


if __name__ == "__main__":
    unittest.main()
