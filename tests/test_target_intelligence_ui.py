from __future__ import annotations

import unittest

from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.target_intelligence_ui import install_target_intelligence_ui


class TargetIntelligenceUITests(unittest.TestCase):
    def test_installer_adds_live_target_surface_and_reuses_activity_refresh(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        before = app_module.EverQuestieApp._refresh_activity_pathways
        install_target_intelligence_ui()
        app_cls = app_module.EverQuestieApp
        after = app_cls._refresh_activity_pathways

        self.assertTrue(getattr(app_cls, "_everquestie_target_intelligence_ui", False))
        self.assertIsNot(after, before)
        self.assertTrue(callable(getattr(app_cls, "_refresh_target_intelligence", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_view", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_navigate", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_details", None)))
        self.assertFalse(hasattr(app_cls, "_target_intelligence_tick"))

        # Idempotence: installing again must not stack another refresh wrapper.
        install_target_intelligence_ui()
        self.assertIs(app_cls._refresh_activity_pathways, after)


if __name__ == "__main__":
    unittest.main()
