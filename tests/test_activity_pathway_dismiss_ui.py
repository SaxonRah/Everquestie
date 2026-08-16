from __future__ import annotations

from types import SimpleNamespace
import unittest

from eqquest.activity_pathway_dismiss_ui import install_activity_pathway_dismiss_ui
from eqquest.activity_pathways import PathwayEvidence, PathwaySuggestion
from eqquest.activity_pathways_ui import install_activity_pathways_ui


class _Tree:
    def __init__(self):
        self.deleted: list[str] = []

    def delete(self, iid):
        self.deleted.append(str(iid))


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class ActivityPathwayDismissUITests(unittest.TestCase):
    def setUp(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_activity_pathway_dismiss_ui()
        self.app_module = app_module
        self.one = PathwaySuggestion(
            quest_id=100,
            quest_name="First Quest",
            score=70,
            evidence=(PathwayEvidence("kill", "Test Mob", 3, 1, "Kill it", "Zone"),),
            profile_status="available",
        )
        self.two = PathwaySuggestion(
            quest_id=200,
            quest_name="Second Quest",
            score=60,
            evidence=(PathwayEvidence("loot", "Test Item", 1, 1, "Loot it", "Zone"),),
            profile_status="available",
        )

    def test_apply_removes_only_dismissed_visible_pathway(self):
        fake = SimpleNamespace(
            activity_pathway_tree=_Tree(),
            _activity_pathway_dismissed_quests={100},
            _activity_pathway_by_item={
                "pathway:100": self.one,
                "pathway:200": self.two,
            },
        )

        removed = self.app_module.EverQuestieApp._apply_activity_pathway_dismissals(fake)

        self.assertEqual(removed, 1)
        self.assertEqual(fake.activity_pathway_tree.deleted, ["pathway:100"])
        self.assertEqual(list(fake._activity_pathway_by_item), ["pathway:200"])

    def test_dismiss_selected_changes_session_display_state_only(self):
        refreshes: list[bool] = []
        status = _Status()
        fake = SimpleNamespace(
            _activity_pathway_dismissed_quests=set(),
            _selected_activity_pathway=lambda: self.one,
            _refresh_activity_pathways=lambda force=False: refreshes.append(bool(force)),
            status=status,
        )

        self.app_module.EverQuestieApp._activity_pathway_dismiss_selected(fake)

        self.assertEqual(fake._activity_pathway_dismissed_quests, {100})
        self.assertEqual(refreshes, [True])
        self.assertIn("First Quest", status.value)
        self.assertIn("this monitoring session", status.value)

    def test_missing_selection_does_not_create_dismissal(self):
        status = _Status()
        fake = SimpleNamespace(
            _activity_pathway_dismissed_quests=set(),
            _selected_activity_pathway=lambda: None,
            status=status,
        )

        self.app_module.EverQuestieApp._activity_pathway_dismiss_selected(fake)

        self.assertEqual(fake._activity_pathway_dismissed_quests, set())
        self.assertIn("Select a Potential Pathway", status.value)

    def test_installer_is_explicitly_session_only_and_exposes_control(self):
        app_cls = self.app_module.EverQuestieApp
        self.assertTrue(getattr(app_cls, "_everquestie_activity_pathway_dismiss_ui", False))
        self.assertTrue(callable(getattr(app_cls, "_activity_pathway_dismiss_selected", None)))
        self.assertTrue(callable(getattr(app_cls, "_apply_activity_pathway_dismissals", None)))


if __name__ == "__main__":
    unittest.main()
