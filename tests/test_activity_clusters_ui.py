from __future__ import annotations

import unittest

from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.activity_clusters_ui import install_activity_clusters_ui


class ActivityClustersUITests(unittest.TestCase):
    def test_installer_decorates_existing_activity_pathways_surface(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_activity_clusters_ui()
        app_cls = app_module.EverQuestieApp

        self.assertTrue(getattr(app_cls, "_everquestie_activity_pathways_ui", False))
        self.assertTrue(getattr(app_cls, "_everquestie_activity_clusters_ui", False))
        self.assertTrue(callable(getattr(app_cls, "_refresh_activity_cluster", None)))
        self.assertTrue(callable(getattr(app_cls, "_refresh_activity_pathways", None)))


if __name__ == "__main__":
    unittest.main()
