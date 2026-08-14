from __future__ import annotations

import unittest

from eqquest.route_guidance_ui import RouteGuidanceFrame
from eqquest.runtime_policy import install_runtime_policy


class RuntimeRouteGuidancePolicyTests(unittest.TestCase):
    def test_packaged_app_build_closes_over_route_guidance_frame(self):
        install_runtime_policy()
        from eqquest import app as app_module

        build_ui = app_module.EverQuestieApp._build_ui
        closure = {
            name: cell.cell_contents
            for name, cell in zip(build_ui.__code__.co_freevars, build_ui.__closure__ or ())
        }
        self.assertIs(closure.get("TravelFrame"), RouteGuidanceFrame)


if __name__ == "__main__":
    unittest.main()
