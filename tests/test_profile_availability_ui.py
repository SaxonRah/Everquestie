from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.profile_availability_ui import install_profile_availability_ui
from eqquest.profile_availability import ProfileAwareQuestEngine, profiled_entity_detail_text
from eqquest.world_profiles import set_active_world_profile


class ProfileAvailabilityUITests(unittest.TestCase):
    def test_installer_rebinds_app_profile_surfaces(self):
        from eqquest import app as app_module
        from eqquest import route_guidance_ui as travel_ui
        from eqquest.world_profile_ui import install_world_profile_ui

        # The production launcher installs world-profile Travel ownership first.
        install_world_profile_ui()
        install_profile_availability_ui()

        self.assertIs(app_module.QuestEngine, ProfileAwareQuestEngine)
        self.assertIs(app_module.entity_detail_text, profiled_entity_detail_text)
        self.assertTrue(
            getattr(
                travel_ui.RouteGuidanceFrame._world_profile_changed,
                "_everquestie_profile_availability_ui",
                False,
            )
        )
        self.assertTrue(
            getattr(
                app_module.EverQuestieApp._suggest_zone_from_quest,
                "_everquestie_profile_quest_zone_policy",
                False,
            )
        )

    def test_blocked_quest_does_not_infer_current_zone(self):
        from eqquest import app as app_module
        from eqquest.world_profile_ui import install_world_profile_ui

        install_world_profile_ui()
        install_profile_availability_ui()

        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.upsert_entity(
                    kind="zone",
                    name="Stone Hive",
                    external_id="396",
                    external_namespace="eqclient:zone",
                    data={"expansion": "The Serpent's Spine"},
                )
                quest = db.upsert_entity(
                    kind="quest",
                    name="Blocked Zone Suggestion",
                    external_id="quest:blocked-zone-suggestion",
                )
                db.add_quest_step(
                    quest,
                    1,
                    "Visit Stone Hive",
                    zone="Stone Hive",
                    match={"event": "zone"},
                )
                set_active_world_profile(db, "p99")

                class FakeApp:
                    def __init__(self):
                        self.db = db
                        self.events: list[str] = []

                    def _quest_zone_name(self, _quest_id: int) -> str:
                        return "Stone Hive"

                    def _append_event(self, text: str) -> None:
                        self.events.append(text)

                fake = FakeApp()
                app_module.EverQuestieApp._suggest_zone_from_quest(fake, quest)
                self.assertEqual(len(fake.events), 1)
                self.assertIn("not inferred from quest", fake.events[0])
                self.assertIn("Classic / P99-style", fake.events[0])
                self.assertIn("Stone Hive", fake.events[0])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
