from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_opportunities import zone_opportunities


class ZoneOpportunityRuntimeTests(unittest.TestCase):
    def test_packaged_runtime_projects_zone_opportunity_without_knowledge_write(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            working = root / "working.sqlite3"
            knowledge = root / "everquestie-knowledge.sqlite3"
            state = root / "everquestie-user.sqlite3"

            builder = Database(working)
            try:
                source = builder.upsert_source_page(
                    url="https://everquest.allakhazam.com/db/quest.html?quest=opportunity-runtime",
                    title="Opportunity Quest",
                    entity_type="quest",
                    sha256="sha-opportunity-runtime",
                    plain_text="reviewed structured quest objective",
                    raw_html="<html></html>",
                    source_name="Allakhazam",
                    source_kind="local_mirror",
                    source_key="quest:opportunity-runtime",
                )
                builder.upsert_entity(
                    kind="zone",
                    name="Opportunity Zone",
                    external_id="9901",
                    external_namespace="eqclient:zone",
                )
                quest = builder.upsert_entity(
                    kind="quest",
                    name="Opportunity Quest",
                    external_id="quest:opportunity-runtime",
                )
                builder.add_quest_step(
                    quest,
                    1,
                    "Defeat the opportunity target",
                    zone="Opportunity Zone",
                    match={"event": "kill", "npc": "Opportunity Target"},
                    source_page_id=source,
                )
            finally:
                builder.close()

            create_knowledge_snapshot(
                working,
                knowledge,
                snapshot_version="zone-opportunity-runtime-test",
                overwrite=True,
            )
            before = sha256(knowledge.read_bytes()).hexdigest()

            runtime = RuntimeDatabase(knowledge, state)
            try:
                rows = zone_opportunities(runtime, "Opportunity Zone")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].quest_name, "Opportunity Quest")
                self.assertEqual(rows[0].steps[0].step_order, 1)
            finally:
                runtime.close()

            self.assertEqual(sha256(knowledge.read_bytes()).hexdigest(), before)
            self.assertFalse(Path(str(knowledge) + "-wal").exists())
            self.assertFalse(Path(str(knowledge) + "-shm").exists())


if __name__ == "__main__":
    unittest.main()
