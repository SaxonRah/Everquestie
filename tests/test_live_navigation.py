from __future__ import annotations

from types import SimpleNamespace
import unittest

from eqquest.live_navigation import handoff_to_travel


class LiveNavigationHandoffTests(unittest.TestCase):
    def test_missing_travel_surface_returns_none_without_selecting_tab(self):
        selected: list[object] = []
        app = SimpleNamespace(
            notebook=SimpleNamespace(select=lambda tab: selected.append(tab)),
        )

        self.assertIsNone(handoff_to_travel(app, "The Hole"))
        self.assertEqual(selected, [])

    def test_connected_travel_surface_is_selected_and_receives_zone_exactly(self):
        selected: list[object] = []
        destinations: list[str] = []
        travel = SimpleNamespace(
            route_to_zone=lambda zone: destinations.append(zone) or True,
        )
        app = SimpleNamespace(
            travel_tab=travel,
            notebook=SimpleNamespace(select=lambda tab: selected.append(tab)),
        )

        self.assertTrue(handoff_to_travel(app, "The Hole"))
        self.assertEqual(selected, [travel])
        self.assertEqual(destinations, ["The Hole"])

    def test_connected_travel_surface_preserves_false_route_result(self):
        selected: list[object] = []
        travel = SimpleNamespace(route_to_zone=lambda _zone: False)
        app = SimpleNamespace(
            travel_tab=travel,
            notebook=SimpleNamespace(select=lambda tab: selected.append(tab)),
        )

        self.assertFalse(handoff_to_travel(app, "Paineel"))
        self.assertEqual(selected, [travel])


if __name__ == "__main__":
    unittest.main()
