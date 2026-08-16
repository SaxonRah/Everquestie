from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.session_activity import session_activity_summary, session_activity_text


class SessionActivityTests(unittest.TestCase):
    def test_summary_respects_boundary_and_reports_observations_without_causality(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.add_event(Event(kind="kill", raw="old kill", actor="old mob"))
                boundary = int(
                    db.conn.execute("SELECT MAX(id) AS n FROM observed_events").fetchone()["n"]
                )

                db.add_event(Event(kind="kill", raw="kill 1", actor="a bloodsaber"))
                db.add_event(Event(kind="kill", raw="kill 2", actor="A Bloodsaber"))
                db.add_event(Event(kind="kill", raw="kill 3", actor="a rat"))
                db.add_event(Event(kind="loot", raw="loot 1", item="Bloodsaber Blade"))
                db.add_event(Event(kind="loot", raw="loot 2", item="Bloodsaber Blade"))
                db.add_event(Event(kind="loot", raw="loot 3", item="Rat Whisker"))
                db.add_event(Event(kind="faction_up", raw="faction +", target="Guards of Qeynos"))
                db.add_event(Event(kind="faction_down", raw="faction -", target="Bloodsabers"))
                db.add_event(Event(kind="death", raw="death", actor="a bloodsaber"))
                db.add_event(Event(kind="level_gain", raw="level", fields={"level": 20}))
                db.add_event(Event(kind="task_assigned", raw="task", text="Test Task"))
                db.add_event(Event(kind="task_update", raw="task update", text="Test Task"))
                db.add_event(Event(kind="merchant_sale", raw="sale", actor="Merchant Test", item="Rusty Sword"))
                db.add_event(Event(kind="zone", raw="zone", zone="Qeynos Catacombs"))

                summary = session_activity_summary(
                    db,
                    boundary,
                    starting_zone="South Qeynos",
                    current_zone="Qeynos Catacombs",
                    pathway_count=3,
                )

                self.assertEqual(summary.mobs_observed_slain, 3)
                self.assertEqual(summary.unique_mobs_observed_slain, 2)
                self.assertEqual(summary.top_mobs[0].label.casefold(), "a bloodsaber")
                self.assertEqual(summary.top_mobs[0].count, 2)
                self.assertEqual(summary.items_looted, 3)
                self.assertEqual(summary.unique_items_looted, 2)
                self.assertEqual(summary.top_items[0].count, 2)
                self.assertEqual(summary.faction_up, 1)
                self.assertEqual(summary.faction_down, 1)
                self.assertEqual(set(summary.factions_touched), {"Guards of Qeynos", "Bloodsabers"})
                self.assertEqual(summary.deaths, 1)
                self.assertEqual(summary.levels_gained, 1)
                self.assertEqual(summary.levels_lost, 0)
                self.assertEqual(summary.tasks_assigned, 1)
                self.assertEqual(summary.task_updates, 1)
                self.assertEqual(summary.merchant_sales, 1)
                self.assertEqual(summary.pathway_count, 3)
                self.assertEqual(summary.zones, ("South Qeynos", "Qeynos Catacombs"))

                text = session_activity_text(summary)
                self.assertIn("Mobs observed slain: 3", text)
                self.assertIn("Items you looted: 3", text)
                self.assertIn("Potential pathways currently surfaced: 3", text)
                self.assertIn("not guaranteed personal kills", text)
                self.assertIn("not attributed to a specific kill", text)
                self.assertNotIn("old mob", text)
            finally:
                db.close()

    def test_zone_path_preserves_start_transition_order_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.add_event(Event(kind="zone", raw="b", zone="Zone B"))
                db.add_event(Event(kind="zone", raw="a again", zone="Zone A"))
                db.add_event(Event(kind="zone", raw="c", zone="Zone C"))
                summary = session_activity_summary(
                    db,
                    0,
                    starting_zone="Zone A",
                    current_zone="Zone C",
                )
                self.assertEqual(summary.zones, ("Zone A", "Zone B", "Zone C"))
            finally:
                db.close()

    def test_empty_session_can_still_name_current_zone(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                summary = session_activity_summary(
                    db,
                    0,
                    starting_zone="The Nexus",
                    current_zone="The Nexus",
                )
                self.assertTrue(summary.empty)
                self.assertEqual(summary.zones, ("The Nexus",))
                text = session_activity_text(summary)
                self.assertIn("No parsed log activity", text)
                self.assertIn("The Nexus", text)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
