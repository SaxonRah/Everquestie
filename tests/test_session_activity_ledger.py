from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from eqquest.activity_pathways import ActivityPathwayEngine
from eqquest.db import Database
from eqquest.events import Event
from eqquest.session_activity_ledger import latest_observed_event, session_ledger_entry


class SessionActivityLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "ledger.sqlite3")
        self.page = self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/quest.html?quest=ledger",
            title="Ledger fixture",
            entity_type="quest",
            sha256="ledger-fixture",
            plain_text="fixture",
            raw_html="<html></html>",
        )
        self.rat = self.db.upsert_entity(
            kind="npc",
            name="a sewer rat",
            source_page_id=self.page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1001",
            external_id="npc:1001",
        )
        self.tail = self.db.upsert_entity(
            kind="item",
            name="Sewer Rat Tail",
            source_page_id=self.page,
            source_url="https://everquest.allakhazam.com/db/item.html?item=2001",
            external_id="item:2001",
        )
        self.tracked = self.db.upsert_entity(
            kind="quest",
            name="Tracked Rat Cleanup",
            source_page_id=self.page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=3001",
            external_id="quest:3001",
        )
        self.potential = self.db.upsert_entity(
            kind="quest",
            name="Potential Rat Research",
            source_page_id=self.page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=3002",
            external_id="quest:3002",
        )
        for quest_id in (self.tracked, self.potential):
            self.db.add_quest_step(
                quest_id,
                1,
                "Slay a sewer rat",
                zone="South Qeynos",
                match={"event": "kill", "npc_entity_id": self.rat, "count": 2},
                source_page_id=self.page,
            )
            self.db.add_quest_step(
                quest_id,
                2,
                "Loot a Sewer Rat Tail",
                match={"event": "loot", "item_entity_id": self.tail, "count": 1},
                source_page_id=self.page,
            )
        self.db.upsert_relationship(
            self.tracked,
            self.tail,
            "objective_turn_in_item",
            quantity=1,
            source_page_id=self.page,
            evidence="Reviewed tracked turn-in item",
        )
        self.db.upsert_relationship(
            self.potential,
            self.tail,
            "objective_turn_in_item",
            quantity=2,
            source_page_id=self.page,
            evidence="Reviewed potential turn-in item",
        )
        self.db.track_quest(self.tracked)

        # Pre-session history must not leak into live counts.
        self.db.add_event(
            Event(
                kind="kill",
                raw="old rat slain",
                actor="a sewer rat",
                target="OtherPlayer",
            )
        )
        self.boundary = int(
            self.db.conn.execute("SELECT MAX(id) AS n FROM observed_events").fetchone()["n"]
        )
        self.engine = ActivityPathwayEngine(self.db)
        self.engine.reset_session(self.boundary, starting_zone="South Qeynos")

    def tearDown(self) -> None:
        self.db.close()
        self.tempdir.cleanup()

    def _latest_id(self) -> int:
        return int(
            self.db.conn.execute("SELECT MAX(id) AS n FROM observed_events").fetchone()["n"]
        )

    def _suggestions(self):
        self.engine.refresh_observations()
        return tuple(self.engine.suggestions("South Qeynos", limit=25))

    def test_personal_and_generic_kills_are_distinct_and_session_scoped(self) -> None:
        self.db.add_event(
            Event(
                kind="kill",
                raw="You have slain a sewer rat!",
                actor="a sewer rat",
                target="You",
            )
        )
        personal_id = self._latest_id()
        personal = session_ledger_entry(
            self.db,
            personal_id,
            self.boundary,
            current_zone="South Qeynos",
            pathway_suggestions=self._suggestions(),
        )
        self.assertIsNotNone(personal)
        text = "\n".join(personal.annotations)
        self.assertIn("KILL TRACK | personal kill #1", text)
        self.assertIn("observed slain x1 this session", text)
        self.assertIn("TRACKED QUEST CONTEXT | Tracked Rat Cleanup", text)
        self.assertIn("POTENTIAL PATHWAY | Potential Rat Research", text)
        self.assertNotIn("old rat", text)
        self.assertNotIn("progressed", text.casefold())

        self.db.add_event(
            Event(
                kind="kill",
                raw="a sewer rat has been slain by HelpfulRanger!",
                actor="a sewer rat",
                target="HelpfulRanger",
            )
        )
        generic_id = self._latest_id()
        generic = session_ledger_entry(
            self.db,
            generic_id,
            self.boundary,
            current_zone="South Qeynos",
            pathway_suggestions=self._suggestions(),
        )
        self.assertIsNotNone(generic)
        text = "\n".join(generic.annotations)
        self.assertIn("observed slain x2 this session; killer: HelpfulRanger", text)
        self.assertIn("no personal kill credit inferred", text)
        self.assertIn("target observed slain; this log line does not prove your kill credit", text)
        self.assertIn("POTENTIAL PATHWAY | Potential Rat Research", text)

    def test_loot_tracks_count_corpse_source_pathway_and_reviewed_item_use(self) -> None:
        self.db.add_event(
            Event(
                kind="loot",
                raw="--You have looted a Sewer Rat Tail from a sewer rat's corpse.--",
                actor="a sewer rat",
                item="Sewer Rat Tail",
            )
        )
        event_id = self._latest_id()
        entry = session_ledger_entry(
            self.db,
            event_id,
            self.boundary,
            current_zone="South Qeynos",
            pathway_suggestions=self._suggestions(),
        )
        self.assertIsNotNone(entry)
        text = "\n".join(entry.annotations)
        self.assertIn("LOOT TRACK | Sewer Rat Tail x1 this session; from a sewer rat's corpse", text)
        self.assertIn("TRACKED QUEST CONTEXT | Tracked Rat Cleanup", text)
        self.assertIn("POTENTIAL PATHWAY | Potential Rat Research", text)
        self.assertIn("ITEM RELEVANCE | Tracked Rat Cleanup — turn-in item x1; tracked", text)
        self.assertIn("ITEM RELEVANCE | Potential Rat Research — turn-in item x2", text)
        self.assertNotIn("drop rate", text.casefold())

    def test_current_event_does_not_borrow_zone_bound_pathway_from_earlier_zone(self) -> None:
        self.db.add_event(Event(kind="zone", raw="entered qeynos", zone="South Qeynos"))
        self.db.add_event(
            Event(kind="kill", raw="qeynos rat", actor="a sewer rat", target="OtherPlayer")
        )
        self._suggestions()

        self.db.add_event(Event(kind="zone", raw="entered freeport", zone="West Freeport"))
        self.db.add_event(
            Event(kind="kill", raw="freeport rat", actor="a sewer rat", target="OtherPlayer")
        )
        event_id = self._latest_id()
        self.engine.refresh_observations()
        suggestions = tuple(self.engine.suggestions("West Freeport", limit=25))
        entry = session_ledger_entry(
            self.db,
            event_id,
            self.boundary,
            current_zone="West Freeport",
            pathway_suggestions=suggestions,
        )
        self.assertIsNotNone(entry)
        text = "\n".join(entry.annotations)
        self.assertIn("KILL TRACK", text)
        self.assertNotIn("POTENTIAL PATHWAY | Potential Rat Research — step 1", text)
        self.assertNotIn("TRACKED QUEST CONTEXT | Tracked Rat Cleanup", text)

    def test_latest_event_round_trips_the_same_summary_used_by_live_tail(self) -> None:
        event = Event(
            kind="loot",
            raw="loot fixture",
            timestamp=datetime(2026, 8, 18, 0, 30, 45),
            actor="a sewer rat",
            item="Sewer Rat Tail",
            amount=2,
            fields={"source": "corpse", "reviewed": True},
        )
        self.db.add_event(event)
        latest = latest_observed_event(self.db)
        self.assertIsNotNone(latest)
        _event_id, restored = latest
        history_restored = self.db.observed_event_history()[-1]
        self.assertEqual(restored, event)
        self.assertEqual(history_restored, event)
        self.assertEqual(restored.summary(), event.summary())
        self.assertEqual(history_restored.summary(), event.summary())


if __name__ == "__main__":
    unittest.main()
