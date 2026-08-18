from __future__ import annotations

from types import SimpleNamespace
import unittest

from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.loot_relevance_ui import install_loot_relevance_ui
import eqquest.loot_relevance_ui as loot_ui


class LootSourceNavigationUITests(unittest.TestCase):
    def test_installer_exposes_find_source_action(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_loot_relevance_ui()
        app_cls = app_module.EverQuestieApp

        self.assertTrue(callable(getattr(app_cls, "_loot_relevance_find_source", None)))

        before = app_cls._build_live
        install_loot_relevance_ui()
        self.assertIs(app_cls._build_live, before)

    def test_find_source_maps_exact_projected_source_choice(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_loot_relevance_ui()
        app_cls = app_module.EverQuestieApp

        item = SimpleNamespace(item_id=7001, item_name="Exact Resin")
        use = SimpleNamespace(quest_id=8001)
        choice = SimpleNamespace(
            zone_name="The Stone Hive",
            x=41.0,
            y=31.0,
            z=5.0,
            map_label="a stone hive worker (drops from)",
            location_entity_name="a stone hive worker",
        )
        projected = SimpleNamespace(
            item_name="Exact Resin",
            map_ready=True,
            route_ready=False,
            map_choices=(choice,),
            route_choices=(),
            reason="ready",
        )
        calls: list[tuple[int, str | None]] = []
        chooser_calls: list[tuple[str, str, tuple[object, ...]]] = []
        focused: list[tuple] = []
        statuses: list[str] = []
        fake = SimpleNamespace(
            loot_relevance_tree=SimpleNamespace(
                selection=lambda: ("loot-relevance:7001:8001:objective_loot",)
            ),
            _loot_relevance_by_item={
                "loot-relevance:7001:8001:objective_loot": (item, use)
            },
            db=object(),
            state_model=SimpleNamespace(current_zone="The Stone Hive"),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
            _focus_navigation_map_target=lambda *args: focused.append(args),
        )

        old_projection = loot_ui.loot_source_navigation
        old_chooser = loot_ui.ask_knowledge_map_choice
        try:
            loot_ui.loot_source_navigation = lambda _db, item_id, zone: (
                calls.append((int(item_id), zone)) or projected
            )
            loot_ui.ask_knowledge_map_choice = lambda _parent, name, zone, choices: (
                chooser_calls.append((str(name), str(zone), tuple(choices))) or choices[0]
            )
            app_cls._loot_relevance_find_source(fake)
        finally:
            loot_ui.loot_source_navigation = old_projection
            loot_ui.ask_knowledge_map_choice = old_chooser

        self.assertEqual(calls, [(7001, "The Stone Hive")])
        self.assertEqual(chooser_calls, [("Exact Resin", "The Stone Hive", (choice,))])
        self.assertEqual(
            focused,
            [("The Stone Hive", 41.0, 31.0, 5.0, "a stone hive worker (drops from)")],
        )
        self.assertTrue(any("a stone hive worker" in text for text in statuses))

    def test_find_source_without_selection_fails_closed(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()
        install_loot_relevance_ui()
        app_cls = app_module.EverQuestieApp
        statuses: list[str] = []
        fake = SimpleNamespace(
            loot_relevance_tree=SimpleNamespace(selection=lambda: ()),
            _loot_relevance_by_item={},
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
        )

        app_cls._loot_relevance_find_source(fake)

        self.assertEqual(statuses, ["Select a Recent Loot Relevance row first."])


if __name__ == "__main__":
    unittest.main()
