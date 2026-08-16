from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.activity_clusters import (
    activity_cluster_summary,
    activity_cluster_text,
    related_pathway_names,
)
from eqquest.activity_pathways import PathwayEvidence, PathwaySuggestion
from eqquest.db import Database
from eqquest.events import Event


class ActivityClusterTests(unittest.TestCase):
    def test_repeated_current_zone_activity_surfaces_compact_cluster(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                boundary = 0
                db.add_event(Event(kind="zone", raw="zone", zone="Lower Guk"))
                for _ in range(4):
                    db.add_event(Event(kind="kill", raw="kill", actor="a froglok tactician"))
                for _ in range(2):
                    db.add_event(Event(kind="loot", raw="loot", item="Froglok Meat"))

                summary = activity_cluster_summary(
                    db,
                    boundary,
                    current_zone="Lower Guk",
                )
                self.assertTrue(summary.active)
                self.assertEqual(summary.mobs_observed_slain, 4)
                self.assertEqual(summary.items_looted, 2)
                self.assertEqual(summary.top_mobs[0].label, "a froglok tactician")
                self.assertEqual(summary.top_mobs[0].count, 4)

                text = activity_cluster_text(summary, pathway_names=("Froglok Research",))
                self.assertIn("Lower Guk", text)
                self.assertIn("observed slain: a froglok tactician ×4", text)
                self.assertIn("you looted: Froglok Meat ×2", text)
                self.assertIn("Related pathways: Froglok Research", text)
                self.assertIn("not guaranteed personal kills", text)
            finally:
                db.close()

    def test_latest_zone_transition_discards_previous_activity_cluster(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                for _ in range(8):
                    db.add_event(Event(kind="kill", raw="old kill", actor="an old mob"))
                db.add_event(Event(kind="zone", raw="zone", zone="New Zone"))
                db.add_event(Event(kind="kill", raw="new kill", actor="a new mob"))
                db.add_event(Event(kind="kill", raw="new kill", actor="a new mob"))
                db.add_event(Event(kind="loot", raw="new loot", item="New Token"))

                summary = activity_cluster_summary(db, 0, current_zone="New Zone")
                self.assertTrue(summary.active)
                self.assertEqual(summary.mobs_observed_slain, 2)
                self.assertEqual(summary.items_looted, 1)
                self.assertEqual(summary.top_mobs[0].label, "a new mob")
                self.assertNotIn("old", activity_cluster_text(summary).casefold())
            finally:
                db.close()

    def test_welcome_discards_prior_zone_and_clears_stale_zone_label(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.add_event(Event(kind="zone", raw="zone", zone="Old Zone"))
                for _ in range(4):
                    db.add_event(Event(kind="kill", raw="old kill", actor="Old Mob"))
                db.add_event(Event(kind="welcome", raw="Welcome to EverQuest!"))
                for _ in range(3):
                    db.add_event(Event(kind="kill", raw="new kill", actor="Unlocated Mob"))

                # Deliberately pass stale caller state. The explicit Welcome boundary is
                # stronger evidence and must prevent the old zone from owning new rows.
                summary = activity_cluster_summary(db, 0, current_zone="Old Zone")

                self.assertTrue(summary.active)
                self.assertEqual(summary.zone, "")
                self.assertEqual(summary.mobs_observed_slain, 3)
                self.assertEqual(summary.top_mobs[0].label, "Unlocated Mob")
                text = activity_cluster_text(summary)
                self.assertIn("Zone unknown", text)
                self.assertIn("Unlocated Mob ×3", text)
                self.assertNotIn("Old Zone", text)
                self.assertNotIn("Old Mob", text)
            finally:
                db.close()

    def test_zone_entry_after_welcome_restores_new_cluster_geography(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.add_event(Event(kind="zone", raw="zone", zone="Old Zone"))
                for _ in range(3):
                    db.add_event(Event(kind="kill", raw="old kill", actor="Old Mob"))
                db.add_event(Event(kind="welcome", raw="Welcome to EverQuest!"))
                for _ in range(3):
                    db.add_event(Event(kind="kill", raw="unlocated kill", actor="Between Mob"))
                db.add_event(Event(kind="zone", raw="zone", zone="New Zone"))
                for _ in range(3):
                    db.add_event(Event(kind="kill", raw="new kill", actor="New Mob"))

                summary = activity_cluster_summary(db, 0, current_zone="Old Zone")

                self.assertTrue(summary.active)
                self.assertEqual(summary.zone, "New Zone")
                self.assertEqual(summary.mobs_observed_slain, 3)
                self.assertEqual(summary.top_mobs[0].label, "New Mob")
                text = activity_cluster_text(summary)
                self.assertIn("New Zone", text)
                self.assertIn("New Mob ×3", text)
                self.assertNotIn("Old Mob", text)
                self.assertNotIn("Between Mob", text)
            finally:
                db.close()

    def test_one_off_events_stay_quiet(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.add_event(Event(kind="kill", raw="kill", actor="one mob"))
                db.add_event(Event(kind="loot", raw="loot", item="one item"))
                summary = activity_cluster_summary(db, 0, current_zone="Quiet Zone")
                self.assertFalse(summary.active)
                self.assertEqual(activity_cluster_text(summary), "")
            finally:
                db.close()

    def test_related_pathways_require_exact_cluster_evidence_overlap(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                for _ in range(3):
                    db.add_event(Event(kind="kill", raw="kill", actor="Cluster Mob"))
                summary = activity_cluster_summary(db, 0, current_zone="Test Zone")

                matching = PathwaySuggestion(
                    quest_id=1,
                    quest_name="Matching Quest",
                    score=80,
                    evidence=(
                        PathwayEvidence(
                            "kill",
                            "cluster mob",
                            3,
                            1,
                            "Defeat Cluster Mob",
                            "Test Zone",
                        ),
                    ),
                    profile_status="available",
                )
                unrelated = PathwaySuggestion(
                    quest_id=2,
                    quest_name="Unrelated Quest",
                    score=100,
                    evidence=(
                        PathwayEvidence(
                            "loot",
                            "Different Item",
                            5,
                            1,
                            "Collect Different Item",
                            "Test Zone",
                        ),
                    ),
                    profile_status="available",
                )

                self.assertEqual(
                    related_pathway_names(summary, (unrelated, matching)),
                    ("Matching Quest",),
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
