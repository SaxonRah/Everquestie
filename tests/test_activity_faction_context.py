from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.activity_clusters import activity_cluster_summary, activity_cluster_text
from eqquest.db import Database
from eqquest.events import Event


class ActivityFactionContextTests(unittest.TestCase):
    def test_active_cluster_lists_same_segment_faction_messages_without_causality(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.add_event(Event(kind="zone", raw="zone", zone="Qeynos Catacombs"))
                for _ in range(4):
                    db.add_event(Event(kind="kill", raw="kill", actor="a bloodsaber"))
                db.add_event(
                    Event(kind="faction_up", raw="up", target="Guards of Qeynos")
                )
                db.add_event(
                    Event(kind="faction_up", raw="up", target="Guards of Qeynos")
                )
                db.add_event(
                    Event(kind="faction_down", raw="down", target="Bloodsabers")
                )

                summary = activity_cluster_summary(
                    db,
                    0,
                    current_zone="Qeynos Catacombs",
                )
                self.assertTrue(summary.active)
                self.assertEqual(summary.faction_messages, 3)
                self.assertEqual(summary.top_factions[0].label, "Guards of Qeynos")
                self.assertEqual(summary.top_factions[0].better, 2)
                self.assertEqual(summary.top_factions[0].worse, 0)

                text = activity_cluster_text(summary)
                self.assertIn("Faction messages in this same activity segment", text)
                self.assertIn("Guards of Qeynos better ×2", text)
                self.assertIn("Bloodsabers worse ×1", text)
                self.assertIn("Timing only", text)
                self.assertIn("does not infer which activity caused them", text)
            finally:
                db.close()

    def test_latest_zone_transition_excludes_old_faction_messages(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.add_event(Event(kind="faction_up", raw="old", target="Old Faction"))
                db.add_event(Event(kind="zone", raw="zone", zone="New Zone"))
                for _ in range(3):
                    db.add_event(Event(kind="kill", raw="kill", actor="New Mob"))
                db.add_event(Event(kind="faction_down", raw="new", target="New Faction"))

                summary = activity_cluster_summary(db, 0, current_zone="New Zone")
                self.assertEqual(summary.faction_messages, 1)
                self.assertEqual([row.label for row in summary.top_factions], ["New Faction"])
                self.assertNotIn("Old Faction", activity_cluster_text(summary))
            finally:
                db.close()

    def test_faction_messages_alone_never_create_activity_cluster(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                for _ in range(8):
                    db.add_event(Event(kind="faction_up", raw="up", target="Test Faction"))

                summary = activity_cluster_summary(db, 0, current_zone="Quiet Zone")
                self.assertEqual(summary.faction_messages, 8)
                self.assertEqual(summary.relevant_events, 0)
                self.assertFalse(summary.active)
                self.assertEqual(activity_cluster_text(summary), "")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
