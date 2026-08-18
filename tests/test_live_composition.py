from __future__ import annotations

import inspect
import unittest

from eqquest import loot_relevance_ui, target_intelligence_ui
from eqquest.live_composition import chain_activity_pathways_refresh


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
