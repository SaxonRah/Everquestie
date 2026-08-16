from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.allakhazam_temporary_audit import audit_allakhazam_temporary_pages


def _page(
    url: str | None,
    *,
    close: bool = True,
    body: str = '<h1>fixture</h1>',
    title: str = 'Fixture',
) -> str:
    canonical = f'<link rel="canonical" href="{url}">' if url else ""
    ending = "</body></html>" if close else "<div>truncated"
    return f"<html><head><title>{title}</title>{canonical}</head><body>{body}{ending}"


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
            self.assertEqual(report.final_temporary_files, 4)
            self.assertFalse(report.mirror_changed_during_scan)
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

    def test_generic_bestiary_canonical_uses_production_document_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generic_url = "https://everquest.allakhazam.com/search.html?id=12345"
            (root / "npc1234.html.tmp").write_text(
                _page(
                    generic_url,
                    body='<div class="npcinfo">NPC Added: 2001 NPC Last Updated: 2002</div>',
                    title="a test npc :: Bestiary :: EverQuest",
                ),
                encoding="utf-8",
            )

            report = audit_allakhazam_temporary_pages(root)

            self.assertEqual(report.files_with_canonical_url, 1)
            self.assertEqual(report.structured_canonical_files, 1)
            self.assertEqual(report.likely_complete_structured_files, 1)
            self.assertEqual(dict(report.by_canonical_kind), {"npc": 1})
            self.assertEqual(dict(report.by_status), {"likely_complete_structured": 1})
            self.assertGreaterEqual(report.full_content_fallback_reads, 1)

    def test_reports_when_mirror_grows_during_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            item_url = "https://everquest.allakhazam.com/db/item.html?item=1"
            (root / "item0001.html.tmp").write_text(_page(item_url), encoding="utf-8")
            created = False

            def progress(current: int, total: int) -> None:
                nonlocal created
                if not created and current == 1:
                    created = True
                    (root / "item0002.html.tmp").write_text(
                        _page("https://everquest.allakhazam.com/db/item.html?item=2"),
                        encoding="utf-8",
                    )

            report = audit_allakhazam_temporary_pages(root, progress=progress)

            self.assertEqual(report.temporary_files, 1)
            self.assertEqual(report.final_temporary_files, 2)
            self.assertEqual(report.files_added_during_scan, 1)
            self.assertEqual(report.files_removed_during_scan, 0)
            self.assertTrue(report.mirror_changed_during_scan)


if __name__ == "__main__":
    unittest.main()
