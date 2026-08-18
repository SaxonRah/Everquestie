from __future__ import annotations

import inspect
import unittest

from eqquest import (
    activity_clusters_ui,
    activity_pathway_zone_context_ui,
    loot_relevance_ui,
    quest_progress_zone_context_ui,
    session_activity_ledger_ui,
    target_intelligence_ui,
    target_known_drops_live_ui,
    target_personal_sightings_live_ui,
    zone_opportunities_ui,
)
from eqquest.live_composition import (
    chain_activity_pathways_refresh,
    chain_live_build,
    chain_live_start,
)


class LiveCompositionTests(unittest.TestCase):
    def test_chained_refresh_preserves_install_order_and_force(self):
        calls: list[tuple[str, bool]] = []

        class App:
            def _refresh_activity_pathways(self, *, force: bool = False) -> None:
                calls.append(("base", force))

        def first(self, *, force: bool = False) -> None:
            calls.append(("first", force))

        def second(self, *, force: bool = False) -> None:
            calls.append(("second", force))

        chain_activity_pathways_refresh(App, first)
        chain_activity_pathways_refresh(App, second)

        App()._refresh_activity_pathways(force=True)

        self.assertEqual(
            calls,
            [("base", True), ("first", True), ("second", True)],
        )

    def test_chained_refresh_can_call_extension_without_force_parameter(self):
        calls: list[str] = []

        class App:
            def _refresh_activity_pathways(self, *, force: bool = False) -> None:
                calls.append(f"base:{force}")

        def extension(self) -> None:
            calls.append("extension")

        chain_activity_pathways_refresh(App, extension, pass_force=False)

        App()._refresh_activity_pathways(force=True)

        self.assertEqual(calls, ["base:True", "extension"])

    def test_chained_live_start_preserves_previous_first_install_order(self):
        calls: list[str] = []

        class App:
            def _start(self) -> None:
                calls.append("base")

        def first(self) -> None:
            calls.append("first")

        def second(self) -> None:
            calls.append("second")

        chain_live_start(App, first)
        chain_live_start(App, second)

        App()._start()

        self.assertEqual(calls, ["base", "first", "second"])

    def test_chained_live_build_preserves_previous_first_install_order(self):
        calls: list[str] = []

        class App:
            def _build_live(self) -> None:
                calls.append("base")

        def first(self) -> None:
            calls.append("first")

        def second(self) -> None:
            calls.append("second")

        chain_live_build(App, first)
        chain_live_build(App, second)

        App()._build_live()

        self.assertEqual(calls, ["base", "first", "second"])

    def test_post_start_installers_delegate_to_shared_start_chain(self):
        for installer in (
            activity_pathway_zone_context_ui.install_activity_pathway_zone_context_ui,
            quest_progress_zone_context_ui.install_quest_progress_zone_context_ui,
            session_activity_ledger_ui.install_session_activity_ledger_ui,
        ):
            source = inspect.getsource(installer)
            self.assertIn("chain_live_start(", source)
            self.assertNotIn("current_start =", source)
            self.assertNotIn("def _start(", source)

    def test_target_auxiliary_installers_delegate_to_shared_live_build_chain(self):
        for installer in (
            target_known_drops_live_ui.install_target_known_drops_ui,
            target_personal_sightings_live_ui.install_target_personal_sightings_ui,
        ):
            source = inspect.getsource(installer)
            self.assertIn("chain_live_build(", source)
            self.assertNotIn("current_build_live =", source)
            self.assertNotIn("def _build_live(", source)

    def test_activity_discovery_installers_delegate_to_shared_live_build_chain(self):
        for installer in (
            activity_clusters_ui.install_activity_clusters_ui,
            zone_opportunities_ui.install_zone_opportunities_ui,
        ):
            source = inspect.getsource(installer)
            self.assertIn("chain_live_build(", source)
            self.assertNotIn("current_build_live =", source)
            self.assertNotIn("def _build_live(", source)

    def test_live_projection_build_installers_delegate_to_shared_live_build_chain(self):
        for installer in (
            loot_relevance_ui.install_loot_relevance_ui,
            target_intelligence_ui.install_target_intelligence_ui,
        ):
            source = inspect.getsource(installer)
            self.assertIn("chain_live_build(", source)
            self.assertNotIn("current_build_live =", source)
            self.assertNotIn("def _build_live(", source)

    def test_remaining_live_projection_installers_delegate_to_shared_refresh_chain(self):
        for installer in (
            loot_relevance_ui.install_loot_relevance_ui,
            target_intelligence_ui.install_target_intelligence_ui,
        ):
            source = inspect.getsource(installer)
            self.assertIn("chain_activity_pathways_refresh(", source)
            self.assertNotIn("def _refresh_activity_pathways(", source)
            self.assertNotIn("current_refresh_pathways =", source)


if __name__ == "__main__":
    unittest.main()
