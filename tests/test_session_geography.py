from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.events import Event
from eqquest.log_geography import LogGeography, recover_log_geography
from eqquest.parser import EQLogParser
from eqquest.session_geography_ui import _mark_loaded_map_as_reference, _render_session_geography
from eqquest.state import SessionState


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class SessionGeographyTests(unittest.TestCase):
    def test_welcome_clears_zone_source_and_location(self):
        state = SessionState(
            current_zone="Old Zone",
            zone_source="log",
            last_location=(1.0, 2.0, 3.0),
        )

        state.apply(Event(kind="welcome", raw="Welcome to EverQuest!"))

        self.assertIsNone(state.current_zone)
        self.assertEqual(state.zone_source, "unknown")
        self.assertIsNone(state.last_location)

    def test_loc_is_not_accepted_until_geography_is_reestablished(self):
        state = SessionState()
        loc = Event(kind="loc", raw="loc", fields={"x": 1.0, "y": 2.0, "z": 3.0})

        state.apply(loc)
        self.assertIsNone(state.last_location)

        state.apply(Event(kind="zone", raw="zone", zone="New Zone"))
        state.apply(loc)
        self.assertEqual(state.last_location, (1.0, 2.0, 3.0))

    def test_zone_change_invalidates_location_and_next_loc_restores_it(self):
        state = SessionState(current_zone="Old Zone", zone_source="log", last_location=(9, 8, 7))
        state.apply(Event(kind="zone", raw="zone", zone="New Zone"))
        self.assertIsNone(state.last_location)
        state.apply(Event(kind="loc", raw="loc", fields={"x": 4, "y": 5, "z": 6}))
        self.assertEqual(state.last_location, (4.0, 5.0, 6.0))

    def test_log_recovery_welcome_is_hard_boundary_for_zone_and_loc(self):
        parser = EQLogParser()
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "eqlog.txt"
            path.write_text(
                "You have entered Old Zone.\n"
                "Your Location is 20, 10, 3\n"
                "Welcome to EverQuest!\n"
                "Your Location is 200, 100, 30\n",
                encoding="utf-8",
            )

            result = recover_log_geography(path, parser)

        self.assertEqual(result, LogGeography())

    def test_log_recovery_accepts_new_zone_and_loc_after_welcome(self):
        parser = EQLogParser()
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "eqlog.txt"
            path.write_text(
                "You have entered Old Zone.\n"
                "Your Location is 20, 10, 3\n"
                "Welcome to EverQuest!\n"
                "You have entered New Zone.\n"
                "Your Location is 50, 40, 6\n",
                encoding="utf-8",
            )

            result = recover_log_geography(path, parser)

        self.assertIsNotNone(result)
        self.assertEqual(result.zone, "New Zone")
        # Parser converts EQ's Y,X,Z display into game-space X,Y,Z.
        self.assertEqual(result.location, (40.0, 50.0, 6.0))

    def test_ui_explicitly_renders_unknown_and_marks_old_map_reference_only(self):
        zone_var = _Var()
        loc_var = _Var("Location: 1.0, 2.0, 3.0")
        manual_zone = _Var("Old Zone")
        map_status = _Var("Old Zone loaded")
        redraws = []
        app = SimpleNamespace(
            state_model=SessionState(),
            zone_var=zone_var,
            loc_var=loc_var,
            _update_zone_display=lambda: zone_var.set("Zone: unknown"),
            map_view=SimpleNamespace(
                manual_zone=manual_zone,
                map_status=map_status,
                zone_map=object(),
                _redraw_position=lambda: redraws.append(True),
            ),
        )

        _render_session_geography(app)
        _mark_loaded_map_as_reference(app)

        self.assertEqual(zone_var.get(), "Zone: unknown")
        self.assertEqual(loc_var.get(), "Location: unknown")
        self.assertEqual(manual_zone.get(), "")
        self.assertIn("reference only", map_status.get())
        self.assertEqual(redraws, [True])


if __name__ == "__main__":
    unittest.main()
