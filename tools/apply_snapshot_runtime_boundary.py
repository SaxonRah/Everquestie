from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise RuntimeError(f"Expected patch anchor not found in {path}: {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    app = ROOT / "eqquest" / "app.py"
    replace_once(
        app,
        '''        self.wiki_importer = AllakhazamWikiImporter(self.db)\n        # Upgrade previously imported raw Allakhazam pages into the new graph\n        # automatically; no re-save/re-import is required after updating EverQuestie.\n        try:\n            self.importer.rebuild_imported_pages()\n        except Exception:\n            # A malformed archived page must not prevent the companion from starting.\n            pass\n\n''',
        '''        self.wiki_importer = AllakhazamWikiImporter(self.db)\n        # Source compilers/importers are explicit builder/developer actions. Startup\n        # must never rewrite packaged knowledge based on one provider's archived data.\n\n''',
    )

    allakhazam = ROOT / "eqquest" / "allakhazam.py"
    replace_once(
        allakhazam,
        '''    def rebuild_imported_pages(self) -> list[ImportResult]:\n        """Backfill graph data for pages imported by older EverQuestie versions.\n\n        This reads the raw HTML already archived in SQLite; users do not need to\n        re-save or re-import pages after upgrading the app.\n        """''',
        '''    def rebuild_imported_pages(self) -> list[ImportResult]:\n        """Explicitly backfill graph data for legacy imported Allakhazam pages.\n\n        This is a builder/developer migration helper. Normal EverQuestie startup must\n        not call it because packaged knowledge snapshots are release artifacts rather\n        than source-specific mutable caches.\n        """''',
    )

    readme = ROOT / "tools" / "README.md"
    replace_once(
        readme,
        '''## MCP setup\n''',
        '''## Finalize a distributable knowledge snapshot\n\nFinalize from a **copy** of a populated working database:\n\n```powershell\npython .\\tools\\finalize_knowledge_snapshot.py --input .\\build\\working.sqlite3 --output .\\dist\\everquestie-knowledge.sqlite3 --version 2026.08.14\n```\n\nThe finalizer leaves the input database untouched. The output has player/session rows and builder-local paths removed, map links reconciled, FTS rebuilt, separate knowledge schema/content versions recorded, SQLite integrity checked, WAL sidecars eliminated, and the file vacuumed/optimized. A non-portable legacy map path is a release-blocking error rather than something the tool silently packages.\n\nAllakhazam DB/Wiki mirrors are not prerequisites for this process. If those providers are available in a future build, their normalized records and provenance can be present before finalization just like any other source.\n\n## MCP setup\n''',
    )

    test = ROOT / "tests" / "test_runtime_source_policy.py"
    test.write_text(
        '''import inspect\nimport unittest\n\nfrom eqquest.allakhazam import AllakhazamImporter\nfrom eqquest.app import EverQuestieApp\n\n\nclass RuntimeSourcePolicyTests(unittest.TestCase):\n    def test_startup_does_not_rebuild_allakhazam_knowledge(self):\n        init_source = inspect.getsource(EverQuestieApp.__init__)\n        self.assertNotIn("rebuild_imported_pages(", init_source)\n\n    def test_legacy_allakhazam_rebuild_remains_explicitly_available(self):\n        self.assertTrue(callable(AllakhazamImporter.rebuild_imported_pages))\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
        encoding="utf-8",
    )
    print("snapshot/runtime boundary cleanup applied")


if __name__ == "__main__":
    main()
