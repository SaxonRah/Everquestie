from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.personal_observations import personal_observation_text
from eqquest.runtime import RuntimeDatabase


class PersonalObservationZoneRuntimeTests(unittest.TestCase):
    def test_packaged_runtime_keeps_zone_history_in_user_state_only(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            working = root / "working.sqlite3"
            knowledge = root / "everquestie-knowledge.sqlite3"
            state = root / "everquestie-user.sqlite3"

            builder = Database(working)
            try:
                builder.upsert_entity(
                    kind="npc",
                    name="Packaged Encounter",
                    external_id="npc:packaged-encounter",
                )
            finally:
                builder.close()
            create_knowledge_snapshot(
                working,
                knowledge,
                snapshot_version="personal-zone-context-test",
                overwrite=True,
            )
            before = sha256(knowledge.read_bytes()).hexdigest()

            runtime = RuntimeDatabase(knowledge, state)
            try:
                row = runtime.conn.execute(
                    "SELECT id FROM entities WHERE kind='npc' AND name='Packaged Encounter'"
                ).fetchone()
                runtime.add_event(Event(kind="zone", raw="zone", zone="Runtime Zone"))
                runtime.add_event(
                    Event(kind="kill", raw="kill", actor="Packaged Encounter")
                )
                text = personal_observation_text(runtime, int(row["id"]))
                self.assertIn("Runtime Zone — Observed slain ×1", text)
                self.assertIn("personal log geography", text)
            finally:
                runtime.close()

            self.assertEqual(sha256(knowledge.read_bytes()).hexdigest(), before)
            self.assertFalse(Path(str(knowledge) + "-wal").exists())
            self.assertFalse(Path(str(knowledge) + "-shm").exists())


if __name__ == "__main__":
    unittest.main()
