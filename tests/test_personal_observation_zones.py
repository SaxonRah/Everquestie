from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.personal_observations import personal_observation_summary, personal_observation_text


class PersonalObservationZoneTests(unittest.TestCase):
    def test_npc_history_groups_actions_by_explicit_logged_zone_context(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                npc = db.upsert_entity(
                    kind="npc",
                    name="a froglok tactician",
                    external_id="npc:froglok-tactician",
                )
                db.add_event(Event(kind="zone", raw="zone", zone="Lower Guk"))
                db.add_event(Event(kind="kill", raw="kill", actor="a froglok tactician"))
                db.add_event(Event(kind="kill", raw="kill", actor="A Froglok Tactician"))
                db.add_event(
                    Event(
                        kind="loot",
                        raw="corpse loot",
                        actor="a froglok tactician",
                        item="Froglok Meat",
                    )
                )
                db.add_event(Event(kind="zone", raw="zone", zone="Upper Guk"))
                db.add_event(Event(kind="kill", raw="kill", actor="a froglok tactician"))

                summary = personal_observation_summary(db, npc)
                self.assertEqual(
                    [zone.zone for zone in summary.zone_context],
                    ["Lower Guk", "Upper Guk"],
                )
                self.assertEqual(
                    [(row.label, row.count) for row in summary.zone_context[0].counts],
                    [("Observed slain", 2), ("Explicit corpse loot", 1)],
                )
                self.assertEqual(
                    [(row.label, row.count) for row in summary.zone_context[1].counts],
                    [("Observed slain", 1)],
                )

                text = personal_observation_text(db, npc)
                self.assertIn("Logged zone context", text)
                self.assertIn("Lower Guk — Observed slain ×2; Explicit corpse loot ×1", text)
                self.assertIn("Upper Guk — Observed slain ×1", text)
                self.assertIn("not a canonical spawn/drop/location claim", text)
            finally:
                db.close()

    def test_welcome_clears_stale_zone_until_new_zone_entry(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                npc = db.upsert_entity(
                    kind="npc",
                    name="Session Mob",
                    external_id="npc:session-mob",
                )
                db.add_event(Event(kind="zone", raw="old zone", zone="Old Zone"))
                db.add_event(Event(kind="kill", raw="old kill", actor="Session Mob"))
                db.add_event(Event(kind="welcome", raw="Welcome to EverQuest!"))
                # This observation is still counted personally, but deliberately has no
                # geographic attribution because the new session has no zone entry yet.
                db.add_event(Event(kind="kill", raw="unlocated kill", actor="Session Mob"))
                db.add_event(Event(kind="zone", raw="new zone", zone="New Zone"))
                db.add_event(Event(kind="kill", raw="new kill", actor="Session Mob"))

                summary = personal_observation_summary(db, npc)
                self.assertEqual(
                    [(row.label, row.count) for row in summary.counts],
                    [("Observed slain", 3)],
                )
                self.assertEqual(
                    [
                        (zone.zone, [(row.label, row.count) for row in zone.counts])
                        for zone in summary.zone_context
                    ],
                    [
                        ("New Zone", [("Observed slain", 1)]),
                        ("Old Zone", [("Observed slain", 1)]),
                    ],
                )
                text = personal_observation_text(db, npc)
                self.assertIn("new Welcome line clears stale context", text)
            finally:
                db.close()

    def test_item_history_keeps_logged_loot_geography_separate_from_canonical_sources(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                item = db.upsert_entity(
                    kind="item",
                    name="Ancient Token",
                    external_id="item:ancient-token",
                )
                db.add_event(Event(kind="zone", raw="zone", zone="Temple Zone"))
                db.add_event(
                    Event(
                        kind="loot",
                        raw="loot one",
                        item="Ancient Token",
                        actor="an ancient guard",
                    )
                )
                db.add_event(Event(kind="loot", raw="loot two", item="Ancient Token"))

                summary = personal_observation_summary(db, item)
                self.assertEqual(
                    [(zone.zone, [(row.label, row.count) for row in zone.counts]) for zone in summary.zone_context],
                    [("Temple Zone", [("You looted", 2)])],
                )
                self.assertEqual(
                    [(row.label, row.count) for row in summary.direct_sources],
                    [("an ancient guard", 1)],
                )
                text = personal_observation_text(db, item)
                self.assertIn("Temple Zone — You looted ×2", text)
                self.assertIn("an ancient guard: 1", text)
                self.assertIn("personal log geography", text)
            finally:
                db.close()

    def test_ambiguous_entity_name_gets_no_personal_zone_attachment(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                first = db.upsert_entity(kind="npc", name="Shared Mob", external_id="npc:one")
                second = db.upsert_entity(kind="npc", name="Shared Mob", external_id="npc:two")
                db.add_event(Event(kind="zone", raw="zone", zone="Somewhere"))
                db.add_event(Event(kind="kill", raw="kill", actor="Shared Mob"))

                self.assertEqual(personal_observation_summary(db, first).zone_context, ())
                self.assertEqual(personal_observation_summary(db, second).zone_context, ())
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
