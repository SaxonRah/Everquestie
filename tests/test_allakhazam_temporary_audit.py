from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.allakhazam_temporary_audit import audit_allakhazam_temporary_pages


def _page(url: str | None, *, close: bool = True) -> str:
    canonical = f'<link rel="canonical" href="{url}">' if url else ""
    ending = "</body></html>" if close else "<div>truncated"
    return f"<html><head>{canonical}</head><body><h1>fixture</h1>{ending}"


class AllakhazamTemporaryAuditTests(unittest.TestCase):
    def test_classifies_recovery_candidates_truncation_and_completed_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            completed_quest = "https://everquest.allakhazam.com/db/quest.html?quest=12"
            (root / "quest.html").write_text(_page(completed_quest), encoding="utf-8")

            item_url = "https://everquest.allakhazam.com/db/item.html?item=34"
            (root / "item0001.html.tmp").write_text(_page(item_url), encoding="utf-8")

            npc_url = "https://everquest.allakhazam.com/db/npc.html?id=56"
            (root / "npc0001.html.tmp").write_text(_page(npc_url, close=False), encoding="utf-8")

            (root / "quest0001.html.tmp").write_text(_page(completed_quest), encoding="utf-8")
            (root / "helper.html.tmp").write_text(
                "<html><body>helper</body></html>",
                encoding="utf-8",
            )

            report = audit_allakhazam_temporary_pages(root, sample_limit=2)

            self.assertEqual(report.temporary_files, 4)
            self.assertEqual(report.read_errors, 0)
            self.assertEqual(report.files_with_canonical_url, 3)
            self.assertEqual(report.unique_canonical_pages, 3)
            self.assertEqual(report.structured_canonical_files, 3)
            self.assertEqual(report.likely_complete_structured_files, 1)
            self.assertEqual(report.structured_files_missing_document_end, 1)
            self.assertEqual(report.duplicate_of_completed_page_files, 1)
            self.assertEqual(dict(report.by_filename_family)["item"], 1)
            self.assertEqual(dict(report.by_filename_family)["npc"], 1)
            self.assertEqual(dict(report.by_filename_family)["quest"], 1)
            self.assertEqual(dict(report.by_filename_family)["other"], 1)
            self.assertEqual(dict(report.by_canonical_kind), {"item": 1, "npc": 1, "quest": 1})
            self.assertEqual(dict(report.by_status)["likely_complete_structured"], 1)
            self.assertEqual(dict(report.by_status)["structured_missing_document_end"], 1)
            self.assertEqual(dict(report.by_status)["structured_duplicate_of_completed_page"], 1)
            self.assertEqual(dict(report.by_status)["no_canonical_with_document_end"], 1)

    def test_duplicate_temporary_canonical_urls_are_counted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            zone_url = "https://everquest.allakhazam.com/db/zone.html?id=99"
            (root / "zone0001.html.tmp").write_text(_page(zone_url), encoding="utf-8")
            (root / "zone0001-2.html.tmp").write_text(_page(zone_url), encoding="utf-8")

            report = audit_allakhazam_temporary_pages(root)

            self.assertEqual(report.files_with_canonical_url, 2)
            self.assertEqual(report.unique_canonical_pages, 1)
            self.assertEqual(report.duplicate_canonical_files, 1)
            self.assertEqual(report.likely_complete_structured_files, 2)


if __name__ == "__main__":
    unittest.main()
