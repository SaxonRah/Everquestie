from __future__ import annotations

import unittest

from eqquest.target_intelligence_ui import install_target_intelligence_ui


class TargetIntelligenceUITests(unittest.TestCase):
    def test_installer_adds_live_target_surface_methods(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        app_cls = app_module.EverQuestieApp

        self.assertTrue(getattr(app_cls, "_everquestie_target_intelligence_ui", False))
        self.assertTrue(callable(getattr(app_cls, "_refresh_target_intelligence", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_view", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_navigate", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_details", None)))


if __name__ == "__main__":
    unittest.main()
