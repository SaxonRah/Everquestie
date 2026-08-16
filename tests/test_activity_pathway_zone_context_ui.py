from __future__ import annotations

import inspect
import unittest

from eqquest.activity_pathway_zone_context_ui import install_activity_pathway_zone_context_ui


class ActivityPathwayZoneContextUITests(unittest.TestCase):
    def test_start_wrapper_seeds_engine_from_recovered_current_zone(self):
        source = inspect.getsource(install_activity_pathway_zone_context_ui)
        self.assertIn('getattr(self.state_model, "current_zone", None)', source)
        self.assertIn(
            "engine.reset_session(boundary, starting_zone=starting_zone)",
            source,
        )
        self.assertIn("_activity_session_start_zone = starting_zone", source)

    def test_seed_runs_only_after_monitoring_actually_started(self):
        source = inspect.getsource(install_activity_pathway_zone_context_ui)
        self.assertIn('getattr(self, "tailer", None) is None', source)
        self.assertIn("current_start(self)", source)


if __name__ == "__main__":
    unittest.main()
