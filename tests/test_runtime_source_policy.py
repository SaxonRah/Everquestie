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


if __name__ == "__main__":
    unittest.main()
