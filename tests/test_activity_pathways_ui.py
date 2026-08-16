from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
import unittest

from eqquest.activity_pathways import PathwayEvidence, PathwaySuggestion
from eqquest.activity_pathways_ui import install_activity_pathways_ui


class _FakeTree:
    def __init__(self, selected: str):
        self._selected = selected

    def selection(self):
        return (self._selected,)


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class ActivityPathwaysUITests(unittest.TestCase):
    def setUp(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        self.app_module = app_module
        self.suggestion = PathwaySuggestion(
            quest_id=4242,
            quest_name="Suggested Quest",
            score=75,
            evidence=(
                PathwayEvidence(
                    "loot",
                    "Interesting Token",
                    2,
                    1,
                    "Collect Interesting Tokens",
                    "Test Zone",
                ),
            ),
            profile_status="unknown",
        )

    def _fake(self):
        class FakeApp:
            pass

        fake = FakeApp()
        fake.activity_pathway_tree = _FakeTree("pathway:4242")
        fake._activity_pathway_by_item = {"pathway:4242": self.suggestion}
        fake.status = _Status()
        fake.db = object()
        fake.state_model = SimpleNamespace(current_zone="Current Zone")
        return fake

    def test_installer_marks_app_and_exposes_live_pathway_actions(self):
        app_cls = self.app_module.EverQuestieApp
        self.assertTrue(getattr(app_cls, "_everquestie_activity_pathways_ui", False))
        self.assertTrue(callable(getattr(app_cls, "_activity_pathway_view_selected", None)))
        self.assertTrue(callable(getattr(app_cls, "_activity_pathway_track_selected", None)))
        self.assertTrue(callable(getattr(app_cls, "_activity_pathway_navigate_contact", None)))
        self.assertTrue(callable(getattr(app_cls, "_activity_pathway_explain_selected", None)))

    def test_view_uses_exact_quest_id_handoff(self):
        fake = self._fake()
        opened: list[int] = []
        fake._open_knowledge_entity_exact = lambda entity_id: opened.append(int(entity_id)) or True
        fake._map_entity_selected = lambda _entity_id: self.fail("legacy name/tree handoff should not run")

        self.app_module.EverQuestieApp._activity_pathway_view_selected(fake)
        self.assertEqual(opened, [4242])

    def test_tracking_happens_only_after_explicit_track_action(self):
        fake = self._fake()
        tracked: list[tuple[int, str | None]] = []
        refreshes: list[str] = []
        fake._track_and_reconcile = lambda entity_id, announce=None: tracked.append(
            (int(entity_id), announce)
        )
        fake._refresh_guidance = lambda: refreshes.append("guidance")
        fake._refresh_activity_pathways = lambda **_kwargs: refreshes.append("pathways")

        # Merely selecting a suggestion is read-only.
        selected = self.app_module.EverQuestieApp._selected_activity_pathway(fake)
        self.assertEqual(selected.quest_id, 4242)
        self.assertEqual(tracked, [])

        self.app_module.EverQuestieApp._activity_pathway_track_selected(fake)
        self.assertEqual(tracked[0][0], 4242)
        self.assertIn("PATHWAY", tracked[0][1])
        self.assertEqual(refreshes, ["guidance", "pathways"])

    def test_navigate_contact_hands_one_current_zone_choice_to_map_owner(self):
        fake = self._fake()
        mapped = []
        fake._focus_navigation_map_target = lambda *args: mapped.append(args)
        choice = SimpleNamespace(
            zone_name="Current Zone",
            x=20.0,
            y=10.0,
            z=5.0,
            map_label="Starter Test (quest starter)",
            location_entity_name="Starter Test",
        )
        result = SimpleNamespace(
            map_ready=True,
            route_ready=False,
            map_choices=(choice,),
            route_choices=(),
            quest_name="Suggested Quest",
            contact_kind="quest starter",
            current_zone_name="Current Zone",
            reason="ready",
        )
        with patch("eqquest.activity_pathways_ui.pathway_contact_navigation", return_value=result):
            self.app_module.EverQuestieApp._activity_pathway_navigate_contact(fake)

        self.assertEqual(
            mapped,
            [("Current Zone", 20.0, 10.0, 5.0, "Starter Test (quest starter)")],
        )
        self.assertIn("Starter Test", fake.status.value)

    def test_navigate_contact_hands_one_remote_zone_to_travel_owner(self):
        fake = self._fake()
        routes: list[str] = []
        selections: list[object] = []
        travel = SimpleNamespace(route_to_zone=lambda zone: routes.append(str(zone)) or True)
        fake.travel_tab = travel
        fake.notebook = SimpleNamespace(select=lambda tab: selections.append(tab))
        choice = SimpleNamespace(zone_name="Remote Zone")
        result = SimpleNamespace(
            map_ready=False,
            route_ready=True,
            map_choices=(),
            route_choices=(choice,),
            quest_name="Suggested Quest",
            contact_kind="quest starter",
            current_zone_name="Current Zone",
            reason="remote",
        )
        with patch("eqquest.activity_pathways_ui.pathway_contact_navigation", return_value=result):
            self.app_module.EverQuestieApp._activity_pathway_navigate_contact(fake)

        self.assertEqual(routes, ["Remote Zone"])
        self.assertEqual(selections, [travel])
        self.assertIn("Remote Zone", fake.status.value)

    def test_navigate_contact_reports_missing_safe_contact_without_guessing(self):
        fake = self._fake()
        result = SimpleNamespace(
            map_ready=False,
            route_ready=False,
            map_choices=(),
            route_choices=(),
            quest_name="Suggested Quest",
            contact_kind="",
            current_zone_name="Current Zone",
            reason="No safely mapped quest starter or turn-in NPC is currently known.",
        )
        with patch("eqquest.activity_pathways_ui.pathway_contact_navigation", return_value=result):
            self.app_module.EverQuestieApp._activity_pathway_navigate_contact(fake)
        self.assertIn("No safely mapped", fake.status.value)


if __name__ == "__main__":
    unittest.main()
