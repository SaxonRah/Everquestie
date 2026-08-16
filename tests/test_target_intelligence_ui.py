from __future__ import annotations

import unittest

from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.target_intelligence_ui import install_target_intelligence_ui
from eqquest.target_quest_connections import TargetQuestConnection


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
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_view_quest", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_track_quest", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_why_quest", None)))
        self.assertFalse(hasattr(app_cls, "_target_intelligence_tick"))

        # Idempotence: installing again must not stack another refresh wrapper.
        install_target_intelligence_ui()
        self.assertIs(app_cls._refresh_activity_pathways, after)

    def test_quest_tracking_happens_only_after_explicit_target_action(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_target_intelligence_ui()
        app_cls = app_module.EverQuestieApp
        connection = TargetQuestConnection(
            quest_id=123,
            quest_name="Bark for the Brewer",
            relation="objective_turn_in_to",
            relation_label="turn-in NPC",
            evidence="Give the bark to Brewer Brolin.",
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=123",
            tracked=False,
            profile_status="available",
            profile_reason="available in selected profile",
        )

        class FakeTree:
            def selection(self):
                return ("target-quest:123:objective_turn_in_to",)

        class FakeStatus:
            def __init__(self):
                self.value = ""

            def set(self, value):
                self.value = str(value)

        class FakeApp:
            def __init__(self):
                self.target_quest_tree = FakeTree()
                self._target_quest_connections_by_item = {
                    "target-quest:123:objective_turn_in_to": connection
                }
                self.status = FakeStatus()
                self.track_calls: list[tuple[int, str]] = []
                self.guidance_refreshes = 0
                self.activity_refreshes = 0

            def _track_and_reconcile(self, quest_id: int, *, announce: str):
                self.track_calls.append((int(quest_id), announce))

            def _refresh_guidance(self):
                self.guidance_refreshes += 1

            def _refresh_activity_pathways(self, *, force: bool = False):
                if force:
                    self.activity_refreshes += 1

        fake = FakeApp()

        # Merely having a selected exact quest connection is display state only.
        self.assertEqual(fake.track_calls, [])
        app_cls._target_intelligence_track_quest(fake)

        self.assertEqual(
            fake.track_calls,
            [(123, "TARGET INTELLIGENCE | tracking selected quest")],
        )
        self.assertEqual(fake.guidance_refreshes, 1)
        self.assertEqual(fake.activity_refreshes, 1)


if __name__ == "__main__":
    unittest.main()
