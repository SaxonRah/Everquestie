from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from eqquest.activity_clusters_ui import install_activity_clusters_ui
from eqquest.activity_pathway_dismiss_ui import install_activity_pathway_dismiss_ui
from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.db import Database
from eqquest.zone_opportunities import ZoneOpportunity, ZoneOpportunityStep
from eqquest.zone_opportunities_ui import install_zone_opportunities_ui


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class _Tree:
    def __init__(self):
        self.rows: dict[str, tuple] = {}
        self.selected: tuple[str, ...] = ()
        self.focused = ""

    def selection(self):
        return self.selected

    def get_children(self, _parent=""):
        return tuple(self.rows)

    def delete(self, *items):
        for item in items:
            self.rows.pop(str(item), None)

    def insert(self, _parent, _where, *, iid, text, values):
        self.rows[str(iid)] = (str(text), tuple(values))

    def selection_set(self, iid):
        self.selected = (str(iid),)

    def focus(self, iid):
        self.focused = str(iid)


class ZoneOpportunitiesUITests(unittest.TestCase):
    def setUp(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_activity_pathway_dismiss_ui()
        install_activity_clusters_ui()
        install_zone_opportunities_ui()
        self.app_module = app_module
        self.opportunity = ZoneOpportunity(
            quest_id=44,
            quest_name="Here Quest",
            source_url="",
            zone_entity_id=7,
            zone_name="Here Zone",
            steps=(
                ZoneOpportunityStep(
                    step_order=3,
                    description="Defeat Here Mob",
                    source_zone="Here Zone",
                    event_kind="kill",
                ),
            ),
            profile_status="available",
            profile_reason="available here",
            activity_match=False,
        )

    def test_installer_exposes_explicit_live_actions(self):
        app_cls = self.app_module.EverQuestieApp
        self.assertTrue(getattr(app_cls, "_everquestie_zone_opportunities_ui", False))
        self.assertTrue(callable(getattr(app_cls, "_zone_opportunity_view_selected", None)))
        self.assertTrue(callable(getattr(app_cls, "_zone_opportunity_track_selected", None)))
        self.assertTrue(callable(getattr(app_cls, "_zone_opportunity_map_selected", None)))

    def test_view_and_track_remain_explicit_exact_quest_actions(self):
        opened: list[int] = []
        tracked: list[tuple[int, str]] = []
        refreshes: list[bool] = []
        fake = SimpleNamespace(
            zone_opportunity_tree=SimpleNamespace(selection=lambda: ("zone-opportunity:44",)),
            _zone_opportunity_by_item={"zone-opportunity:44": self.opportunity},
            _open_knowledge_entity_exact=lambda entity_id: opened.append(int(entity_id)),
            _track_and_reconcile=lambda quest_id, announce="": tracked.append((int(quest_id), str(announce))),
            _refresh_guidance=lambda: None,
            _refresh_activity_pathways=lambda force=False: refreshes.append(bool(force)),
        )

        self.app_module.EverQuestieApp._zone_opportunity_view_selected(fake)
        self.app_module.EverQuestieApp._zone_opportunity_track_selected(fake)

        self.assertEqual(opened, [44])
        self.assertEqual(tracked[0][0], 44)
        self.assertIn("ZONE OPPORTUNITY", tracked[0][1])
        self.assertEqual(refreshes, [True])

    def test_map_action_uses_exact_selected_step_without_tracking_first(self):
        mapped: list[tuple] = []
        fake = SimpleNamespace(
            db=object(),
            state_model=SimpleNamespace(current_zone="Here Zone"),
            zone_opportunity_tree=SimpleNamespace(selection=lambda: ("zone-opportunity:44",)),
            _zone_opportunity_by_item={"zone-opportunity:44": self.opportunity},
            _focus_navigation_map_target=lambda *args: mapped.append(tuple(args)),
            status=_Status(),
        )
        choice = SimpleNamespace(
            zone_name="Here Zone",
            x=12.0,
            y=34.0,
            z=5.0,
            map_label="Here Mob",
            location_entity_name="Here Mob",
        )
        result = SimpleNamespace(
            map_ready=True,
            route_ready=False,
            map_choices=(choice,),
            route_choices=(),
            current_zone_name="Here Zone",
            reason="",
        )

        with patch(
            "eqquest.zone_opportunities_ui.tracked_quest_objective_navigation",
            return_value=result,
        ) as navigation:
            self.app_module.EverQuestieApp._zone_opportunity_map_selected(fake)

        navigation.assert_called_once_with(
            fake.db,
            44,
            "Here Zone",
            step_order=3,
        )
        self.assertEqual(mapped, [("Here Zone", 12.0, 34.0, 5.0, "Here Mob")])
        self.assertIn("Mapped Zone Opportunity objective", fake.status.value)

    def test_session_dismissed_quest_is_not_rendered_in_zone_opportunities(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.upsert_entity(
                    kind="zone",
                    name="Dismiss Zone",
                    external_id="9301",
                    external_namespace="eqclient:zone",
                )
                quest = db.upsert_entity(
                    kind="quest",
                    name="Dismissed Here Quest",
                    external_id="quest:dismissed-here",
                )
                db.add_quest_step(
                    quest,
                    1,
                    "Do something here",
                    zone="Dismiss Zone",
                    match={"event": "kill", "npc": "Mob"},
                )
                tree = _Tree()
                fake = SimpleNamespace(
                    db=db,
                    state_model=SimpleNamespace(current_zone="Dismiss Zone"),
                    zone_opportunity_tree=tree,
                    zone_opportunity_status=_Status(),
                    _zone_opportunity_by_item={},
                    _zone_opportunity_signature=None,
                    _activity_pathway_by_item={},
                    _activity_pathway_dismissed_quests={quest},
                )

                self.app_module.EverQuestieApp._refresh_zone_opportunities(fake, force=True)

                self.assertEqual(tree.rows, {})
                self.assertEqual(fake._zone_opportunity_by_item, {})
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
