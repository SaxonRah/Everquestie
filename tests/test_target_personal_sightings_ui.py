from __future__ import annotations

from types import SimpleNamespace
import unittest

from eqquest.target_intelligence_ui import install_target_intelligence_ui
from eqquest.target_personal_sightings import (
    TargetPersonalSighting,
    TargetPersonalSightingAction,
)
from eqquest.target_personal_sightings_live_ui import install_target_personal_sightings_ui
from eqquest.target_personal_sightings_ui import target_personal_sighting_labels
import eqquest.target_personal_sightings_live_ui as live_ui


class TargetPersonalSightingsUITests(unittest.TestCase):
    def _row(self, *, actionable: bool = True) -> TargetPersonalSighting:
        return TargetPersonalSighting(
            observed_zone_name="Logged Moors",
            total_count=4,
            actions=(
                TargetPersonalSightingAction("Observed slain", 3),
                TargetPersonalSightingAction("Targeted", 1),
            ),
            resolution_status="linked" if actionable else "ambiguous",
            resolution_kind="canonical_name" if actionable else "",
            canonical_zone_entity_id=202 if actionable else None,
            canonical_zone_name="Blightfire Moors" if actionable else "",
            resolution_reason="exact canonical zone" if actionable else "duplicate zone identity",
        )

    def test_choice_label_states_personal_action_counts_and_zone_resolution(self):
        label = target_personal_sighting_labels((self._row(),))[0]
        self.assertIn("Logged Moors", label)
        self.assertIn("4 observation", label)
        self.assertIn("Observed slain x3", label)
        self.assertIn("Targeted x1", label)
        self.assertIn("Blightfire Moors", label)

    def test_installer_exposes_personal_sightings_action_and_is_idempotent(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_personal_sightings_ui()
        app_cls = app_module.EverQuestieApp

        self.assertTrue(getattr(app_cls, "_everquestie_target_personal_sightings_ui", False))
        self.assertTrue(callable(getattr(app_cls, "_target_personal_sightings_browse", None)))
        self.assertTrue(callable(getattr(app_cls, "_target_personal_sighting_details", None)))

        before = app_cls._build_live
        install_target_personal_sightings_ui()
        self.assertIs(app_cls._build_live, before)

    def test_remote_personal_sighting_hands_only_canonical_zone_to_travel(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_personal_sightings_ui()
        app_cls = app_module.EverQuestieApp
        row = self._row(actionable=True)
        routes: list[str] = []
        selected_tabs: list[object] = []
        statuses: list[str] = []
        travel = SimpleNamespace(route_to_zone=lambda zone: routes.append(str(zone)) or True)
        target = SimpleNamespace(resolved=True, entity_id=123, canonical_name="Exact NPC")
        fake = SimpleNamespace(
            _target_intelligence_value=target,
            db=object(),
            state_model=SimpleNamespace(current_zone=""),
            target_personal_sightings_status=SimpleNamespace(set=lambda _text: None),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
            travel_tab=travel,
            notebook=SimpleNamespace(select=lambda tab: selected_tabs.append(tab)),
        )

        old_rows = live_ui.target_personal_sightings
        old_ask = live_ui.ask_target_personal_sighting
        try:
            live_ui.target_personal_sightings = lambda _db, entity_id: (
                row if int(entity_id) == 123 else None,
            )
            live_ui.ask_target_personal_sighting = lambda _parent, _name, _rows: row
            app_cls._target_personal_sightings_browse(fake)
        finally:
            live_ui.target_personal_sightings = old_rows
            live_ui.ask_target_personal_sighting = old_ask

        self.assertEqual(routes, ["Blightfire Moors"])
        self.assertEqual(selected_tabs, [travel])
        self.assertTrue(any("personal sighting zone Blightfire Moors" in text for text in statuses))
        self.assertTrue(any("not canonical spawn evidence" in text for text in statuses))

    def test_same_canonical_zone_does_not_invent_map_location_or_route(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_personal_sightings_ui()
        app_cls = app_module.EverQuestieApp
        row = self._row(actionable=True)
        routes: list[str] = []
        statuses: list[str] = []
        info: list[tuple[str, str]] = []
        target = SimpleNamespace(resolved=True, entity_id=123, canonical_name="Exact NPC")
        fake = SimpleNamespace(
            _target_intelligence_value=target,
            db=object(),
            state_model=SimpleNamespace(current_zone="Blightfire Moors"),
            target_personal_sightings_status=SimpleNamespace(set=lambda _text: None),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
            travel_tab=SimpleNamespace(route_to_zone=lambda zone: routes.append(str(zone)) or True),
            notebook=SimpleNamespace(select=lambda _tab: None),
        )

        old_rows = live_ui.target_personal_sightings
        old_ask = live_ui.ask_target_personal_sighting
        old_resolve = live_ui.resolve_authoritative_zone
        old_info = live_ui.messagebox.showinfo
        try:
            live_ui.target_personal_sightings = lambda _db, _entity_id: (row,)
            live_ui.ask_target_personal_sighting = lambda _parent, _name, _rows: row
            live_ui.resolve_authoritative_zone = lambda _db, _zone: SimpleNamespace(
                identity=SimpleNamespace(entity_id=202)
            )
            live_ui.messagebox.showinfo = lambda title, text: info.append((str(title), str(text)))
            app_cls._target_personal_sightings_browse(fake)
        finally:
            live_ui.target_personal_sightings = old_rows
            live_ui.ask_target_personal_sighting = old_ask
            live_ui.resolve_authoritative_zone = old_resolve
            live_ui.messagebox.showinfo = old_info

        self.assertEqual(routes, [])
        self.assertEqual(len(info), 1)
        self.assertTrue(any("Already in personal sighting zone" in text for text in statuses))
        self.assertTrue(any("no exact NPC /loc" in text for text in statuses))

    def test_ambiguous_personal_zone_stays_visible_but_never_routes(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_personal_sightings_ui()
        app_cls = app_module.EverQuestieApp
        row = self._row(actionable=False)
        routes: list[str] = []
        statuses: list[str] = []
        info: list[tuple[str, str]] = []
        target = SimpleNamespace(resolved=True, entity_id=123, canonical_name="Exact NPC")
        fake = SimpleNamespace(
            _target_intelligence_value=target,
            db=object(),
            state_model=SimpleNamespace(current_zone="Somewhere"),
            target_personal_sightings_status=SimpleNamespace(set=lambda _text: None),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
            travel_tab=SimpleNamespace(route_to_zone=lambda zone: routes.append(str(zone)) or True),
            notebook=SimpleNamespace(select=lambda _tab: None),
        )

        old_rows = live_ui.target_personal_sightings
        old_ask = live_ui.ask_target_personal_sighting
        old_info = live_ui.messagebox.showinfo
        try:
            live_ui.target_personal_sightings = lambda _db, _entity_id: (row,)
            live_ui.ask_target_personal_sighting = lambda _parent, _name, _rows: row
            live_ui.messagebox.showinfo = lambda title, text: info.append((str(title), str(text)))
            app_cls._target_personal_sightings_browse(fake)
        finally:
            live_ui.target_personal_sightings = old_rows
            live_ui.ask_target_personal_sighting = old_ask
            live_ui.messagebox.showinfo = old_info

        self.assertEqual(routes, [])
        self.assertEqual(len(info), 1)
        self.assertTrue(any("ambiguous" in text for text in statuses))
        self.assertTrue(any("will not guess" in text for text in statuses))

    def test_no_exact_target_fails_closed_before_history_lookup(self):
        from eqquest import app as app_module

        install_target_intelligence_ui()
        install_target_personal_sightings_ui()
        app_cls = app_module.EverQuestieApp
        statuses: list[str] = []
        fake = SimpleNamespace(
            _target_intelligence_value=SimpleNamespace(resolved=False, entity_id=None),
            status=SimpleNamespace(set=lambda text: statuses.append(str(text))),
        )

        app_cls._target_personal_sightings_browse(fake)

        self.assertEqual(
            statuses,
            ["No exact current NPC target is available for personal sighting history."],
        )


if __name__ == "__main__":
    unittest.main()
