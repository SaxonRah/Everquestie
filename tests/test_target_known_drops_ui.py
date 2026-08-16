from __future__ import annotations

from types import SimpleNamespace
import unittest

from eqquest.target_known_drops import TargetKnownDrop
from eqquest.target_known_drops_ui import target_known_drop_labels
from eqquest.target_intelligence_ui import install_target_intelligence_ui
from eqquest.target_known_drops_live_ui import install_target_known_drops_ui
import eqquest.target_known_drops_live_ui as live_ui


class TargetKnownDropsUITests(unittest.TestCase):
    def _drop(self) -> TargetKnownDrop:
        return TargetKnownDrop(
            item_id=777,
            item_name="Exact Drop",
            profile_status="available",
            profile_reason="available",
            evidence_count=2,
            source_labels=("Allakhazam",),
            evidence=("Reviewed evidence.",),
            quest_uses=(),
        )

    def test_drop_choice_label_states_quest_and_source_context(self):
        label = target_known_drop_labels((self._drop(),))[0]
        self.assertIn("Exact Drop", label)
        self.assertIn("no reviewed quest use", label)
        self.assertIn("Allakhazam", label)
        self.assertIn("2 evidence row", label)

    def test_installer_adds_on_demand_drop_action(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_known_drops_ui()
        app_cls = app_module.EverQuestieApp

        self.assertTrue(getattr(app_cls, "_everquestie_target_known_drops_ui", False))
        self.assertTrue(callable(getattr(app_cls, "_target_known_drops_browse", None)))

        before = app_cls._build_live
        install_target_known_drops_ui()
        self.assertIs(app_cls._build_live, before)

    def test_selected_drop_opens_exact_canonical_item_id(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_known_drops_ui()
        app_cls = app_module.EverQuestieApp
        drop = self._drop()
        opened: list[int] = []
        statuses: list[str] = []
        target = SimpleNamespace(resolved=True, entity_id=123, canonical_name="Exact NPC")
        fake = SimpleNamespace(
            _target_intelligence_value=target,
            db=SimpleNamespace(),
            target_known_drops_status=SimpleNamespace(set=lambda text: None),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
            _open_knowledge_entity_exact=lambda entity_id: opened.append(int(entity_id)),
        )

        old_profile = live_ui.active_world_profile_id
        old_drops = live_ui.target_known_drops
        old_ask = live_ui.ask_target_known_drop
        try:
            live_ui.active_world_profile_id = lambda _db: "live"
            live_ui.target_known_drops = lambda _db, _entity_id, **_kwargs: (drop,)
            live_ui.ask_target_known_drop = lambda _parent, _target_name, _drops: drop
            app_cls._target_known_drops_browse(fake)
        finally:
            live_ui.active_world_profile_id = old_profile
            live_ui.target_known_drops = old_drops
            live_ui.ask_target_known_drop = old_ask

        self.assertEqual(opened, [777])
        self.assertTrue(any("Exact Drop" in text for text in statuses))

    def test_no_exact_target_fails_closed_before_drop_lookup(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_known_drops_ui()
        app_cls = app_module.EverQuestieApp
        statuses: list[str] = []
        fake = SimpleNamespace(
            _target_intelligence_value=SimpleNamespace(resolved=False, entity_id=None),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
        )

        app_cls._target_known_drops_browse(fake)

        self.assertEqual(statuses, ["No exact current NPC target is available for drop lookup."])


if __name__ == "__main__":
    unittest.main()
