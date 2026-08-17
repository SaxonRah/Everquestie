from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from eqquest import bootstrap


class RuntimeBootstrapTests(unittest.TestCase):
    def test_shared_bootstrap_declares_complete_live_intelligence_stack_in_order(self):
        source = inspect.getsource(bootstrap.install_application_layers)
        installers = [
            "install_runtime_policy",
            "install_map_loading_policy",
            "install_knowledge_coverage_ui",
            "install_packaged_ui_policy",
            "install_objective_reviewed_item_sources_ui",
            "install_knowledge_relationship_navigation_ui",
            "install_travel_output_ui",
            "install_world_profile_ui",
            "install_profile_availability_ui",
            "install_activity_pathways_ui",
            "install_activity_pathway_zone_context_ui",
            "install_quest_progress_zone_context_ui",
            "install_session_geography_ui",
            "install_activity_pathway_dismiss_ui",
            "install_activity_clusters_ui",
            "install_zone_opportunities_ui",
            "install_loot_relevance_ui",
            "install_target_intelligence_ui",
            "install_target_known_drops_ui",
            "install_target_personal_sightings_ui",
            "install_live_track_guard_ui",
            "install_runtime_mode_ui",
        ]

        positions = []
        for installer in installers:
            needle = f"{installer}()"
            self.assertIn(needle, source)
            positions.append(source.index(needle))
        self.assertEqual(positions, sorted(positions))

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
