from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.zone_opportunities import zone_opportunities, zone_opportunity_text


class ZoneOpportunityTests(unittest.TestCase):
    def _zone(self, db: Database, name: str, external_id: str) -> int:
        return db.upsert_entity(
            kind="zone",
            name=name,
            external_id=external_id,
            external_namespace="eqclient:zone",
        )

    def _quest(self, db: Database, name: str, external_id: str, zone: str, steps: int = 1) -> int:
        quest = db.upsert_entity(kind="quest", name=name, external_id=external_id)
        for order in range(1, steps + 1):
            db.add_quest_step(
                quest,
                order,
                f"Objective {order} in {zone}",
                zone=zone,
                match={"event": "kill", "npc": f"Mob {order}"},
            )
        return quest

    def test_untracked_structured_current_zone_objectives_are_projected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                self._zone(db, "Test Zone", "9001")
                quest = self._quest(db, "Test Quest", "quest:test", "Test Zone", steps=2)

                rows = zone_opportunities(db, "Test Zone")

                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].quest_id, quest)
                self.assertEqual(rows[0].zone_name, "Test Zone")
                self.assertEqual([step.step_order for step in rows[0].steps], [1, 2])
                self.assertEqual(rows[0].primary_step_order, 1)
                self.assertFalse(rows[0].activity_match)
                self.assertIn("2 structured objectives", rows[0].primary_reason)
                text = zone_opportunity_text(rows[0])
                self.assertIn("Why here", text)
                self.assertIn("does not mean the quest is currently owned", text)
            finally:
                db.close()

    def test_tracked_quest_is_owned_by_normal_guidance_not_zone_opportunities(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                self._zone(db, "Test Zone", "9002")
                quest = self._quest(db, "Tracked Quest", "quest:tracked", "Test Zone")
                db.track_quest(quest)

                self.assertEqual(zone_opportunities(db, "Test Zone"), ())
            finally:
                db.close()

    def test_activity_overlap_ranks_but_cannot_create_zone_opportunity(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                self._zone(db, "Test Zone", "9003")
                first = self._quest(db, "Alphabetical First", "quest:first", "Test Zone")
                second = self._quest(db, "Activity Match", "quest:activity", "Test Zone")
                remote = self._quest(db, "Remote Activity Only", "quest:remote", "Other Zone")
                self._zone(db, "Other Zone", "9004")

                rows = zone_opportunities(
                    db,
                    "Test Zone",
                    activity_quest_ids=(second, remote),
                )

                self.assertEqual([row.quest_id for row in rows], [second, first])
                self.assertTrue(rows[0].activity_match)
                self.assertFalse(rows[1].activity_match)
                self.assertNotIn(remote, [row.quest_id for row in rows])
            finally:
                db.close()

    def test_p99_suppresses_quest_whose_only_current_zone_is_forced_modern(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                self._zone(db, "Plane of Knowledge", "202")
                self._quest(db, "Modern Hub Quest", "quest:modern-hub", "Plane of Knowledge")

                self.assertEqual(
                    zone_opportunities(db, "Plane of Knowledge", profile_id="p99"),
                    (),
                )
            finally:
                db.close()

    def test_ambiguous_current_zone_identity_returns_no_opportunities(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                self._zone(db, "Duplicate Zone", "9101")
                self._zone(db, "Duplicate Zone", "9102")
                self._quest(db, "Ambiguous Quest", "quest:ambiguous", "Duplicate Zone")

                self.assertEqual(zone_opportunities(db, "Duplicate Zone"), ())
            finally:
                db.close()

    def test_limit_is_applied_after_activity_and_step_count_ranking(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                self._zone(db, "Rank Zone", "9201")
                one = self._quest(db, "One Step", "quest:one", "Rank Zone", steps=1)
                two = self._quest(db, "Two Steps", "quest:two", "Rank Zone", steps=2)
                activity = self._quest(db, "Activity", "quest:activity-rank", "Rank Zone", steps=1)

                rows = zone_opportunities(
                    db,
                    "Rank Zone",
                    activity_quest_ids=(activity,),
                    limit=2,
                )
                self.assertEqual([row.quest_id for row in rows], [activity, two])
                self.assertNotIn(one, [row.quest_id for row in rows])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
