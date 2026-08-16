from __future__ import annotations

import unittest

from eqquest.profile_availability_ui import install_profile_availability_ui
from eqquest.profile_availability import ProfileAwareQuestEngine, profiled_entity_detail_text


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


if __name__ == "__main__":
    unittest.main()
