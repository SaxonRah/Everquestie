from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.npc_relevance import npc_relevance_text, recent_npc_relevance


class NPCRelevanceTests(unittest.TestCase):
    def _db(self, tempdir: str) -> Database:
        return Database(Path(tempdir) / "working.sqlite3")

    def _source(self, db: Database, suffix: str = "1") -> int:
        return db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/db/quest.html?quest={suffix}",
            title=f"Quest {suffix}",
            entity_type="quest",
            sha256=f"sha-{suffix}",
            plain_text="structured quest source",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=f"quest:{suffix}",
        )

    def test_target_and_consider_project_reviewed_connections(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                source = self._source(db)
                npc = db.upsert_entity(kind="npc", name="Brewer Brolin", external_id="npc:1")
                starter = db.upsert_entity(
                    kind="quest",
                    name="Brolin's Beginning",
                    external_id="quest:1",
                    source_page_id=source,
                )
                turnin = db.upsert_entity(
                    kind="quest",
                    name="Bark for the Brewer",
                    external_id="quest:2",
                    source_page_id=source,
                )
                speak = db.upsert_entity(
                    kind="quest",
                    name="Ask the Brewer",
                    external_id="quest:3",
                    source_page_id=source,
                )
                kill = db.upsert_entity(
                    kind="quest",
                    name="A Bad Brewer",
                    external_id="quest:4",
                    source_page_id=source,
                )
                db.upsert_relationship(
                    starter,
                    npc,
                    "started_by",
                    source_page_id=source,
                    evidence="Quest Started By: Brewer Brolin",
                )
                db.upsert_relationship(
                    turnin,
                    npc,
                    "objective_turn_in_to",
                    source_page_id=source,
                    evidence="Give the bark to Brewer Brolin.",
                )
                db.upsert_relationship(
                    speak,
                    npc,
                    "objective_speak",
                    source_page_id=source,
                    evidence="Speak with Brewer Brolin.",
                )
                db.upsert_relationship(
                    kill,
                    npc,
                    "objective_kill",
                    source_page_id=source,
                    evidence="Defeat Brewer Brolin.",
                )
                db.track_quest(turnin)
                db.add_event(Event(kind="target_npc", raw="target", target="Brewer Brolin"))
                db.add_event(Event(kind="consider", raw="consider", target="brewer brolin"))
                db.add_event(Event(kind="target_npc", raw="target again", target="Brewer Brolin"))

                rows = recent_npc_relevance(db, 0)
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row.npc_id, npc)
                self.assertEqual(row.targeted_count, 2)
                self.assertEqual(row.considered_count, 1)
                self.assertEqual(row.observation_count, 3)
                self.assertEqual(row.observation_text, "targeted x2, considered x1")
                self.assertEqual(row.connections[0].quest_id, turnin)
                self.assertTrue(row.connections[0].tracked)
                self.assertEqual(
                    {connection.relation for connection in row.connections},
                    {"started_by", "objective_turn_in_to", "objective_speak", "objective_kill"},
                )

                text = npc_relevance_text(row)
                self.assertIn("targeted x2, considered x1", text)
                self.assertIn("quest starter", text)
                self.assertIn("turn-in NPC", text)
                self.assertIn("does not mean the quest is owned", text)
                self.assertIn("or that the NPC should be killed", text)
            finally:
                db.close()

    def test_session_boundary_excludes_old_npc_observations(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                source = self._source(db)
                npc = db.upsert_entity(kind="npc", name="Scout Fana", external_id="npc:1")
                quest = db.upsert_entity(
                    kind="quest",
                    name="Scout's Work",
                    external_id="quest:1",
                    source_page_id=source,
                )
                db.upsert_relationship(
                    quest,
                    npc,
                    "started_by",
                    source_page_id=source,
                    evidence="Quest Started By: Scout Fana",
                )
                db.add_event(Event(kind="target_npc", raw="old", target="Scout Fana"))
                boundary = int(
                    db.conn.execute("SELECT MAX(id) AS n FROM observed_events").fetchone()["n"]
                )
                self.assertEqual(recent_npc_relevance(db, boundary), ())
                db.add_event(Event(kind="consider", raw="new", target="Scout Fana"))
                rows = recent_npc_relevance(db, boundary)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].targeted_count, 0)
                self.assertEqual(rows[0].considered_count, 1)
            finally:
                db.close()

    def test_ambiguous_npc_name_is_never_attached(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                source = self._source(db)
                first = db.upsert_entity(kind="npc", name="a guard", external_id="npc:1")
                db.upsert_entity(kind="npc", name="a guard", external_id="npc:2")
                quest = db.upsert_entity(
                    kind="quest",
                    name="Guard Duty",
                    external_id="quest:1",
                    source_page_id=source,
                )
                db.upsert_relationship(
                    quest,
                    first,
                    "objective_speak",
                    source_page_id=source,
                    evidence="Speak to a guard.",
                )
                db.add_event(Event(kind="target_npc", raw="target", target="a guard"))
                self.assertEqual(recent_npc_relevance(db, 0), ())
            finally:
                db.close()

    def test_relationship_without_source_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                npc = db.upsert_entity(kind="npc", name="Rumored Sage", external_id="npc:1")
                quest = db.upsert_entity(kind="quest", name="Rumor", external_id="quest:1")
                db.upsert_relationship(
                    quest,
                    npc,
                    "started_by",
                    evidence="synthetic relation without source provenance",
                )
                db.add_event(Event(kind="consider", raw="consider", target="Rumored Sage"))
                self.assertEqual(recent_npc_relevance(db, 0), ())
            finally:
                db.close()

    def test_nearby_speech_and_combat_do_not_create_npc_relevance(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = self._db(tempdir)
            try:
                source = self._source(db)
                npc = db.upsert_entity(kind="npc", name="Chatty Sage", external_id="npc:1")
                quest = db.upsert_entity(
                    kind="quest",
                    name="Sage Advice",
                    external_id="quest:1",
                    source_page_id=source,
                )
                db.upsert_relationship(
                    quest,
                    npc,
                    "objective_speak",
                    source_page_id=source,
                    evidence="Speak to Chatty Sage.",
                )
                db.add_event(Event(kind="npc_say", raw="says", actor="Chatty Sage", text="Hello"))
                db.add_event(Event(kind="kill", raw="slain", actor="Chatty Sage", target="Someone"))
                self.assertEqual(recent_npc_relevance(db, 0), ())
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
