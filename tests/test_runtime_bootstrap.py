from __future__ import annotations

from pathlib import Path
import unittest

from eqquest.bootstrap import install_application_layers


class RuntimeBootstrapTests(unittest.TestCase):
    def test_shared_bootstrap_installs_complete_live_intelligence_stack(self):
        from eqquest import app as app_module

        install_application_layers()
        app_cls = app_module.EverQuestieApp

        self.assertTrue(getattr(app_cls, "_everquestie_activity_pathways_ui", False))
        self.assertTrue(getattr(app_cls, "_everquestie_activity_pathway_dismiss_ui", False))
        self.assertTrue(getattr(app_cls, "_everquestie_activity_clusters_ui", False))
        self.assertTrue(getattr(app_cls, "_everquestie_zone_opportunities_ui", False))
        self.assertTrue(getattr(app_cls, "_everquestie_loot_relevance_ui", False))
        self.assertTrue(getattr(app_cls, "_everquestie_target_intelligence_ui", False))

        self.assertTrue(callable(getattr(app_cls, "_refresh_activity_pathways", None)))
        self.assertTrue(callable(getattr(app_cls, "_refresh_activity_cluster", None)))
        self.assertTrue(callable(getattr(app_cls, "_refresh_zone_opportunities", None)))
        self.assertTrue(callable(getattr(app_cls, "_refresh_loot_relevance", None)))
        self.assertTrue(callable(getattr(app_cls, "_refresh_target_intelligence", None)))

    def test_both_supported_launchers_use_the_same_bootstrap(self):
        root = Path(__file__).resolve().parents[1]
        windows_launcher = (root / "EverQuestie.py").read_text(encoding="utf-8")
        package_launcher = (root / "eqquest" / "__main__.py").read_text(encoding="utf-8")

        for source in (windows_launcher, package_launcher):
            self.assertIn("install_application_layers", source)
            self.assertIn("install_application_layers()", source)

        self.assertNotIn("install_activity_pathways_ui()", windows_launcher)
        self.assertNotIn("install_activity_pathways_ui()", package_launcher)


if __name__ == "__main__":
    unittest.main()
