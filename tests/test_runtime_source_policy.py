import inspect
import unittest

from eqquest.allakhazam import AllakhazamImporter
from eqquest.app import EverQuestieApp


class RuntimeSourcePolicyTests(unittest.TestCase):
    def test_startup_does_not_rebuild_allakhazam_knowledge(self):
        init_source = inspect.getsource(EverQuestieApp.__init__)
        self.assertNotIn("rebuild_imported_pages(", init_source)

    def test_legacy_allakhazam_rebuild_remains_explicitly_available(self):
        self.assertTrue(callable(AllakhazamImporter.rebuild_imported_pages))

    def test_manual_db_mirror_uses_canonical_mirror_importer_only(self):
        init_source = inspect.getsource(EverQuestieApp.__init__)
        mirror_source = inspect.getsource(EverQuestieApp._import_db_mirror)
        saved_source = inspect.getsource(EverQuestieApp._import_saved_html)

        self.assertIn("self.mirror_importer = AllakhazamMirrorImporter(self.db)", init_source)
        self.assertIn("self.mirror_importer.import_mirror(", mirror_source)
        self.assertNotIn("self.importer.import_mirror(", mirror_source)
        self.assertIn("self.importer.import_saved_html(", saved_source)


if __name__ == "__main__":
    unittest.main()
