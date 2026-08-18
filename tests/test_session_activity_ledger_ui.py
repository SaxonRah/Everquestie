from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.session_activity_ledger_ui import install_session_activity_ledger_ui


class _Parent:
    def __init__(self):
        self.text = "Observed EQ events"

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = str(kwargs["text"])


class _EventText:
    def __init__(self):
        self.master = _Parent()


class _Engine:
    def __init__(self):
        self.refreshes = 0

    def refresh_observations(self):
        self.refreshes += 1
        return 0

    def suggestions(self, _zone, *, limit=25):
        return []


class SessionActivityLedgerUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "ledger-ui.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.tempdir.cleanup()

    def test_installer_annotates_only_exact_persisted_event_summary_and_resets_boundary(self):
        from eqquest import app as app_module

        original = app_module.EverQuestieApp

        class FakeApp:
            def _build_live(self):
                self.event_text = _EventText()
                self.lines = []
                self.activity_pathway_engine = _Engine()
                self._activity_session_start_event_id = 0

            def _append_event(self, text):
                self.lines.append(str(text))

            def _start(self):
                row = self.db.conn.execute(
                    "SELECT COALESCE(MAX(id),0) AS n FROM observed_events"
                ).fetchone()
                self._activity_session_start_event_id = int(row["n"])

        try:
            app_module.EverQuestieApp = FakeApp
            install_session_activity_ledger_ui()
            app = FakeApp()
            app.db = self.db
            app.state_model = SimpleNamespace(current_zone="South Qeynos")
            app._build_live()

            self.assertEqual(app.event_text.master.text, "Live session ledger")

            kill = Event(
                kind="kill",
                raw="You have slain a sewer rat!",
                actor="a sewer rat",
                target="You",
            )
            self.db.add_event(kill)
            app._append_event(kill.summary())
            self.assertEqual(app.lines[0], kill.summary())
            self.assertTrue(any("↳ KILL TRACK | personal kill #1" in line for line in app.lines))
            self.assertEqual(app.activity_pathway_engine.refreshes, 1)

            before = list(app.lines)
            app._append_event("COMMAND | status")
            self.assertEqual(app.lines[:-1], before)
            self.assertEqual(app.lines[-1], "COMMAND | status")
            self.assertEqual(app.activity_pathway_engine.refreshes, 1)

            # A new monitoring start excludes the first kill from subsequent counts.
            app._start()
            second = Event(
                kind="kill",
                raw="You have slain a sewer rat again!",
                actor="a sewer rat",
                target="You",
            )
            self.db.add_event(second)
            app._append_event(second.summary())
            self.assertTrue(any("↳ KILL TRACK | personal kill #1" in line for line in app.lines[-3:]))
            self.assertFalse(any("observed slain x2 this session" in line for line in app.lines[-3:]))
            self.assertEqual(app.activity_pathway_engine.refreshes, 2)
        finally:
            app_module.EverQuestieApp = original


if __name__ == "__main__":
    unittest.main()
