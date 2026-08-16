from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.personal_observations import personal_observation_summary, personal_observation_text
from eqquest.runtime import RuntimeDatabase


class PersonalObservationTests(unittest.TestCase):
    def test_npc_history_separates_observed_slain_and_explicit_corpse_loot(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                npc = db.upsert_entity(kind="npc", name="a bloodsaber", external_id="npc:bloodsaber")
                db.add_event(
                    Event(
                        kind="kill",
                        raw="kill",
                        actor="A Bloodsaber",
                        timestamp=datetime(2026, 8, 16, 9, 0, 0),
                    )
                )
                db.add_event(
                    Event(
                        kind="loot",
                        raw="corpse loot",
                        actor="a bloodsaber",
                        item="Bloodsaber Blade",
                        timestamp=datetime(2026, 8, 16, 9, 1, 0),
                    )
                )
                # Generic loot with no corpse actor must never be assigned to this NPC.
                db.add_event(
                    Event(
                        kind="loot",
                        raw="generic loot",
                        item="Unrelated Item",
                        timestamp=datetime(2026, 8, 16, 9, 2, 0),
                    )
                )

                summary = personal_observation_summary(db, npc)
                self.assertIsNotNone(summary)
                self.assertEqual(
                    [(row.label, row.count) for row in summary.counts],
                    [("Observed slain", 1)],
                )
                self.assertEqual(
                    [(row.label, row.count) for row in summary.direct_loot],
                    [("Bloodsaber Blade", 1)],
                )
                text = personal_observation_text(db, npc)
                self.assertIn("Personal/local history only", text)
                self.assertIn("Observed slain: 1", text)
                self.assertIn("Bloodsaber Blade: 1", text)
                self.assertNotIn("Unrelated Item", text)
                self.assertIn("not a calculated drop rate", text)
                self.assertIn("not guaranteed personal kills", text)
            finally:
                db.close()

    def test_item_history_lists_only_explicit_logged_corpse_sources(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                item = db.upsert_entity(kind="item", name="Ancient Token", external_id="item:token")
                db.add_event(Event(kind="loot", raw="one", item="Ancient Token", actor="an ancient guard"))
                db.add_event(Event(kind="loot", raw="two", item="Ancient Token", actor="an ancient guard"))
                db.add_event(Event(kind="loot", raw="three", item="Ancient Token"))

                summary = personal_observation_summary(db, item)
                self.assertEqual(
                    [(row.label, row.count) for row in summary.counts],
                    [("You looted", 3)],
                )
                self.assertEqual(
                    [(row.label, row.count) for row in summary.direct_sources],
                    [("an ancient guard", 2)],
                )
                text = personal_observation_text(db, item)
                self.assertIn("You looted: 3", text)
                self.assertIn("an ancient guard: 2", text)
                self.assertIn("not canonical drop-table claims", text)
            finally:
                db.close()

    def test_duplicate_canonical_npc_name_is_not_attached_to_one_entity(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                first = db.upsert_entity(kind="npc", name="a shared mob", external_id="npc:one")
                second = db.upsert_entity(kind="npc", name="a shared mob", external_id="npc:two")
                db.add_event(Event(kind="kill", raw="kill", actor="a shared mob"))

                self.assertFalse(personal_observation_summary(db, first).observed)
                self.assertFalse(personal_observation_summary(db, second).observed)
                self.assertEqual(personal_observation_text(db, first), "")
                self.assertEqual(personal_observation_text(db, second), "")
            finally:
                db.close()

    def test_multiple_observation_kinds_are_kept_separate(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                npc = db.upsert_entity(kind="npc", name="Keeper Test", external_id="npc:keeper")
                db.add_event(Event(kind="target_npc", raw="target", target="Keeper Test"))
                db.add_event(Event(kind="consider", raw="consider", target="keeper test"))
                db.add_event(Event(kind="npc_say", raw="say", actor="Keeper Test", text="Hail"))
                db.add_event(Event(kind="death", raw="death", actor="Keeper Test"))
                db.add_event(Event(kind="merchant_sale", raw="sale", actor="Keeper Test", item="Rusty Sword"))

                summary = personal_observation_summary(db, npc)
                self.assertEqual(
                    [(row.label, row.count) for row in summary.counts],
                    [
                        ("Targeted", 1),
                        ("Considered", 1),
                        ("Heard speaking", 1),
                        ("Slain you", 1),
                        ("Merchant sales involving this NPC", 1),
                    ],
                )
            finally:
                db.close()

    def test_packaged_runtime_reads_user_history_without_mutating_knowledge(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            working = root / "working.sqlite3"
            knowledge = root / "everquestie-knowledge.sqlite3"
            state = root / "everquestie-user.sqlite3"

            builder = Database(working)
            try:
                builder.upsert_entity(kind="item", name="Packaged Token", external_id="item:packaged")
            finally:
                builder.close()
            create_knowledge_snapshot(
                working,
                knowledge,
                snapshot_version="personal-observation-test",
                overwrite=True,
            )
            before = sha256(knowledge.read_bytes()).hexdigest()

            runtime = RuntimeDatabase(knowledge, state)
            try:
                item = runtime.conn.execute(
                    "SELECT id FROM entities WHERE kind='item' AND name='Packaged Token'"
                ).fetchone()
                runtime.add_event(Event(kind="loot", raw="loot", item="Packaged Token", actor="test corpse"))
                text = personal_observation_text(runtime, int(item["id"]))
                self.assertIn("You looted: 1", text)
                self.assertIn("test corpse: 1", text)
            finally:
                runtime.close()

            self.assertEqual(sha256(knowledge.read_bytes()).hexdigest(), before)
            self.assertFalse(Path(str(knowledge) + "-wal").exists())
            self.assertFalse(Path(str(knowledge) + "-shm").exists())


if __name__ == "__main__":
    unittest.main()
