from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
import unittest

from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.target_intelligence_ui import install_target_intelligence_ui
from eqquest.target_quest_relevance import TargetQuestReason, TargetQuestRelevance


class TargetIntelligenceUITests(unittest.TestCase):
    def test_installer_adds_live_target_surface_and_reuses_activity_refresh(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        app_cls = app_module.EverQuestieApp
        already_installed = bool(
            getattr(app_cls, "_everquestie_target_intelligence_ui", False)
        )
        before = app_cls._refresh_activity_pathways
        install_target_intelligence_ui()
        after = app_cls._refresh_activity_pathways

        self.assertTrue(getattr(app_cls, "_everquestie_target_intelligence_ui", False))
        if already_installed:
            self.assertIs(after, before)
        else:
            self.assertIsNot(after, before)
        self.assertTrue(callable(getattr(app_cls, "_refresh_target_intelligence", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_view", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_navigate", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_intelligence_details", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_quest_view_selected", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_quest_track_selected", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_quest_explain_selected", None)))
        self.assertFalse(hasattr(app_cls, "_target_intelligence_tick"))

        # Idempotence: installing again must not stack another refresh wrapper.
        install_target_intelligence_ui()
        self.assertIs(app_cls._refresh_activity_pathways, after)

    def _relevance(self, *, tracked: bool = False) -> TargetQuestRelevance:
        reason = TargetQuestReason(
            path_kind="direct",
            relation="objective_kill",
            label="Kill objective",
            priority=3,
        )
        return TargetQuestRelevance(
            quest_id=4242,
            quest_name="Exact Quest",
            tracked=tracked,
            profile_status="available",
            profile_reason="available",
            reasons=(reason,),
        )

    def test_target_related_quest_view_uses_exact_canonical_quest_id(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_target_intelligence_ui()
        app_cls = app_module.EverQuestieApp
        relevance = self._relevance()
        opened: list[int] = []
        fake = SimpleNamespace(
            target_quest_tree=SimpleNamespace(selection=lambda: ("quest:4242",)),
            _target_quest_by_item={"quest:4242": relevance},
            _open_knowledge_entity_exact=lambda entity_id: opened.append(int(entity_id)),
            status=SimpleNamespace(set=lambda _text: None),
        )

        app_cls._target_quest_view_selected(fake)

        self.assertEqual(opened, [4242])

    def test_target_navigation_uses_shared_map_chooser_for_single_choice(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_target_intelligence_ui()
        app_cls = app_module.EverQuestieApp
        mapped: list[tuple] = []
        status: list[str] = []
        value = SimpleNamespace(
            resolved=True,
            entity_id=77,
            canonical_name="Exact Target",
        )
        choice = SimpleNamespace(
            zone_name="Current Zone",
            x=10.0,
            y=20.0,
            z=5.0,
            map_label="Exact Target",
            loc_text="10, 20, 5",
        )
        choices = SimpleNamespace(
            ready=True,
            choices=(choice,),
            current_zone_name="Current Zone",
            reason="ready",
        )
        fake = SimpleNamespace(
            _target_intelligence_value=value,
            db=object(),
            state_model=SimpleNamespace(current_zone="Current Zone"),
            status=SimpleNamespace(set=lambda text: status.append(str(text))),
            _focus_navigation_map_target=lambda *args: mapped.append(tuple(args)),
        )

        with patch(
            "eqquest.target_intelligence_ui.knowledge_map_choices",
            return_value=choices,
        ) as navigation, patch(
            "eqquest.target_intelligence_ui.ask_knowledge_map_choice",
            return_value=choice,
        ) as chooser:
            app_cls._target_intelligence_navigate(fake)

        navigation.assert_called_once_with(fake.db, 77, "Current Zone")
        chooser.assert_called_once_with(
            fake,
            "Exact Target",
            "Current Zone",
            (choice,),
        )
        self.assertEqual(mapped, [("Current Zone", 10.0, 20.0, 5.0, "Exact Target")])
        self.assertIn("Mapped exact target Exact Target", status[-1])

    def test_target_navigation_uses_shared_route_chooser_before_travel_handoff(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_target_intelligence_ui()
        app_cls = app_module.EverQuestieApp
        routed: list[str] = []
        selected_tabs: list[object] = []
        status: list[str] = []
        value = SimpleNamespace(
            resolved=True,
            entity_id=77,
            canonical_name="Exact Target",
        )
        choices = SimpleNamespace(
            ready=False,
            choices=(),
            current_zone_name="Current Zone",
            reason="remote",
        )
        route = SimpleNamespace(zone_name="Remote Zone")
        travel = SimpleNamespace(route_to_zone=lambda zone: routed.append(str(zone)) or True)
        fake = SimpleNamespace(
            _target_intelligence_value=value,
            db=object(),
            state_model=SimpleNamespace(current_zone="Current Zone"),
            travel_tab=travel,
            notebook=SimpleNamespace(select=lambda tab: selected_tabs.append(tab)),
            status=SimpleNamespace(set=lambda text: status.append(str(text))),
        )

        with patch(
            "eqquest.target_intelligence_ui.knowledge_map_choices",
            return_value=choices,
        ), patch(
            "eqquest.target_intelligence_ui.knowledge_route_choices",
            return_value=(route,),
        ), patch(
            "eqquest.target_intelligence_ui.ask_knowledge_route_choice",
            return_value=route,
        ) as chooser:
            app_cls._target_intelligence_navigate(fake)

        chooser.assert_called_once_with(
            fake,
            "Exact Target",
            "Current Zone",
            (route,),
        )
        self.assertEqual(routed, ["Remote Zone"])
        self.assertEqual(selected_tabs, [travel])
        self.assertIn("Travel route opened to Remote Zone", status[-1])

    def test_already_tracked_target_quest_does_not_reconcile_again(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_target_intelligence_ui()
        app_cls = app_module.EverQuestieApp
        relevance = self._relevance(tracked=True)
        status: list[str] = []
        track_calls: list[int] = []
        fake = SimpleNamespace(
            target_quest_tree=SimpleNamespace(selection=lambda: ("quest:4242",)),
            _target_quest_by_item={"quest:4242": relevance},
            status=SimpleNamespace(set=lambda text: status.append(str(text))),
            _track_and_reconcile=lambda quest_id, **_kwargs: track_calls.append(int(quest_id)),
            _refresh_guidance=lambda: None,
            _refresh_activity_pathways=lambda **_kwargs: None,
        )

        app_cls._target_quest_track_selected(fake)

        self.assertEqual(track_calls, [])
        self.assertEqual(status, ["Exact Quest is already tracked."])


if __name__ == "__main__":
    unittest.main()
