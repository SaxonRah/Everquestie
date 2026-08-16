from __future__ import annotations

import unittest

from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.loot_relevance_ui import install_loot_relevance_ui
from eqquest.npc_relevance_ui import install_npc_relevance_ui


class NPCRelevanceUITests(unittest.TestCase):
    def test_installer_decorates_existing_activity_refresh_and_exposes_actions(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_loot_relevance_ui()
        before = app_module.EverQuestieApp._refresh_activity_pathways
        install_npc_relevance_ui()
        after = app_module.EverQuestieApp._refresh_activity_pathways

        self.assertIsNot(after, before)
        self.assertTrue(getattr(app_module.EverQuestieApp, "_everquestie_npc_relevance_ui", False))
        for name in (
            "_npc_relevance_view_npc",
            "_npc_relevance_view_quest",
            "_npc_relevance_track_quest",
            "_npc_relevance_navigate_npc",
            "_npc_relevance_explain",
            "_refresh_npc_relevance",
        ):
            self.assertTrue(callable(getattr(app_module.EverQuestieApp, name, None)), name)

        # Idempotence: a second install must not stack another refresh wrapper.
        install_npc_relevance_ui()
        self.assertIs(app_module.EverQuestieApp._refresh_activity_pathways, after)


if __name__ == "__main__":
    unittest.main()
