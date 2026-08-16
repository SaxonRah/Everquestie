from __future__ import annotations

from types import SimpleNamespace
import unittest

from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.target_intelligence_ui import install_target_intelligence_ui
from eqquest.target_quest_relevance import TargetQuestReason, TargetQuestRelevance


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
        self.assertTrue(callable(getattr(app_cls, "_target_quest_view_selected", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_quest_track_selected", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_quest_explain_selected", None)))
        self.assertFalse(hasattr(app_cls, "_target_intelligence_tick"))

        # Idempotence: installing again must not stack another refresh wrapper.
        install_target_intelligence_ui()
        self.assertIs(app_cls._refresh_activity_pathways, after)

    def test_target_related_quest_view_uses_exact_canonical_quest_id(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_target_intelligence_ui()
        app_cls = app_module.EverQuestieApp
        reason = TargetQuestReason(
            path_kind="direct",
            relation="objective_kill",
            label="Kill objective",
            priority=3,
        )
        relevance = TargetQuestRelevance(
            quest_id=4242,
            quest_name="Exact Quest",
            tracked=False,
            profile_status="available",
            profile_reason="available",
            reasons=(reason,),
        )
        opened: list[int] = []
        fake = SimpleNamespace(
            target_quest_tree=SimpleNamespace(selection=lambda: ("quest:4242",)),
            _target_quest_by_item={"quest:4242": relevance},
            _open_knowledge_entity_exact=lambda entity_id: opened.append(int(entity_id)),
            status=SimpleNamespace(set=lambda _text: None),
        )

        app_cls._target_quest_view_selected(fake)

        self.assertEqual(opened, [4242])


if __name__ == "__main__":
    unittest.main()
