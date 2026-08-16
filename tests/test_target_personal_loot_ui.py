from __future__ import annotations

from types import SimpleNamespace
import unittest

from eqquest.target_intelligence_ui import install_target_intelligence_ui
from eqquest.target_known_drops_live_ui import install_target_known_drops_ui
from eqquest.target_personal_loot import TargetPersonalLoot
from eqquest.target_personal_loot_ui import target_personal_loot_labels
import eqquest.target_known_drops_live_ui as live_ui


class TargetPersonalLootUITests(unittest.TestCase):
    def _resolved_row(self, *, reviewed: bool = False) -> TargetPersonalLoot:
        return TargetPersonalLoot(
            observed_item_name="Observed Tail",
            observed_count=3,
            resolution_status="exact",
            item_id=777,
            canonical_item_name="Observed Tail",
            reviewed_drop_known=reviewed,
        )

    def test_choice_label_keeps_personal_and_reviewed_evidence_distinct(self):
        personal = target_personal_loot_labels((self._resolved_row(reviewed=False),))[0]
        reviewed = target_personal_loot_labels((self._resolved_row(reviewed=True),))[0]

        self.assertIn("looted x3", personal)
        self.assertIn("exact item", personal)
        self.assertIn("personal observation only", personal)
        self.assertIn("personal observation + reviewed drop graph", reviewed)

    def test_installer_exposes_personal_loot_action_and_remains_idempotent(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_known_drops_ui()
        app_cls = app_module.EverQuestieApp

        self.assertTrue(callable(getattr(app_cls, "_target_personal_loot_browse", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_personal_loot_details", None)))

        before = app_cls._build_live
        install_target_known_drops_ui()
        self.assertIs(app_cls._build_live, before)

    def test_resolved_personal_loot_opens_exact_canonical_item_id(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_known_drops_ui()
        app_cls = app_module.EverQuestieApp
        row = self._resolved_row(reviewed=False)
        opened: list[int] = []
        statuses: list[str] = []
        summaries: list[str] = []
        target = SimpleNamespace(resolved=True, entity_id=123, canonical_name="Exact NPC")
        fake = SimpleNamespace(
            _target_intelligence_value=target,
            db=object(),
            target_known_drops_status=SimpleNamespace(set=lambda text: summaries.append(str(text))),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
            _open_knowledge_entity_exact=lambda entity_id: opened.append(int(entity_id)),
        )

        old_rows = live_ui.target_personal_loot
        old_ask = live_ui.ask_target_personal_loot
        try:
            live_ui.target_personal_loot = lambda _db, entity_id: (
                row if int(entity_id) == 123 else None
            ,)
            live_ui.ask_target_personal_loot = lambda _parent, _target_name, _rows: row
            app_cls._target_personal_loot_browse(fake)
        finally:
            live_ui.target_personal_loot = old_rows
            live_ui.ask_target_personal_loot = old_ask

        self.assertEqual(opened, [777])
        self.assertTrue(any("personal observation only" in text for text in statuses))
        self.assertTrue(any("3 loot event" in text for text in summaries))

    def test_unresolved_personal_observation_stays_visible_but_does_not_open_item(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_known_drops_ui()
        app_cls = app_module.EverQuestieApp
        row = TargetPersonalLoot(
            observed_item_name="Mystery Thing",
            observed_count=2,
            resolution_status="missing",
            item_id=None,
            canonical_item_name="",
            reviewed_drop_known=False,
        )
        opened: list[int] = []
        statuses: list[str] = []
        info: list[tuple[str, str]] = []
        target = SimpleNamespace(resolved=True, entity_id=123, canonical_name="Exact NPC")
        fake = SimpleNamespace(
            _target_intelligence_value=target,
            db=object(),
            target_known_drops_status=SimpleNamespace(set=lambda _text: None),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
            _open_knowledge_entity_exact=lambda entity_id: opened.append(int(entity_id)),
        )

        old_rows = live_ui.target_personal_loot
        old_ask = live_ui.ask_target_personal_loot
        old_info = live_ui.messagebox.showinfo
        try:
            live_ui.target_personal_loot = lambda _db, _entity_id: (row,)
            live_ui.ask_target_personal_loot = lambda _parent, _target_name, _rows: row
            live_ui.messagebox.showinfo = lambda title, text: info.append((str(title), str(text)))
            app_cls._target_personal_loot_browse(fake)
        finally:
            live_ui.target_personal_loot = old_rows
            live_ui.ask_target_personal_loot = old_ask
            live_ui.messagebox.showinfo = old_info

        self.assertEqual(opened, [])
        self.assertEqual(len(info), 1)
        self.assertIn("Personal Loot Observation", info[0][0])
        self.assertTrue(any("missing" in text for text in statuses))
        self.assertTrue(any("no exact canonical item" in text for text in statuses))

    def test_no_exact_target_fails_closed_before_personal_history_lookup(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_known_drops_ui()
        app_cls = app_module.EverQuestieApp
        statuses: list[str] = []
        fake = SimpleNamespace(
            _target_intelligence_value=SimpleNamespace(resolved=False, entity_id=None),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
        )

        app_cls._target_personal_loot_browse(fake)

        self.assertEqual(
            statuses,
            ["No exact current NPC target is available for personal loot history."],
        )


if __name__ == "__main__":
    unittest.main()
