from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.quest_faction_reconciliation import (
    DERIVED_FROM,
    QuestFactionReconciliationCatalog,
)
from eqquest.runtime import RuntimeDatabase
from eqquest.world_entity_context import build_world_entity_context


class QuestFactionReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

        self.quest_page = self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/quest.html?quest=9001",
            title="A Question of Allegiance",
            entity_type="quest",
            sha256="quest-9001",
            plain_text="quest",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key="quest:9001",
            source_version="mirror-2026-08-14",
        )
        self.quest = self.db.upsert_entity(
            kind="quest",
            name="A Question of Allegiance",
            source_page_id=self.quest_page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=9001",
            external_id="quest:9001",
            data={
                "factions_raised": [
                    "Guardians of the Vale",
                    "Twin Standing",
                    "Missing Standing",
                ],
                "factions_lowered": ["Enemies of the Vale"],
            },
        )

        self.guardians = self._client_faction("Guardians of the Vale", "101")
        self.enemies = self._client_faction("Enemies of the Vale", "102")
        self.manual_faction = self._client_faction("Manual Standing", "103")
        self.twin_one = self._client_faction("Twin Standing", "201")
        self.twin_two = self._client_faction("Twin Standing", "202")

        # A provider-only same-name faction must not compete with one authoritative
        # client-backed target.
        self.provider_guardians = self.db.upsert_entity(
            kind="faction",
            name="Guardians of the Vale",
            external_id="provider:guardians",
        )

        # Native/manual edges with the same relation vocabulary are not compiler-owned
        # and must survive every reconciliation pass.
        self.db.upsert_relationship(
            self.quest,
            self.manual_faction,
            "raises_faction",
            source_page_id=self.quest_page,
            evidence="manual curated faction fact",
            data={"confidence": "curated", "derived_from": "manual_fixture"},
        )

        future_page = self.db.upsert_source_page(
            url="future://quest/1",
            title="Future quest",
            entity_type="quest",
            sha256="future-quest",
            plain_text="future",
            raw_html="",
            source_name="FutureProvider",
            source_kind="fixture",
            source_key="quest:future:1",
        )
        self.future_quest = self.db.upsert_entity(
            kind="quest",
            name="Future quest",
            source_page_id=future_page,
            source_url="future://quest/1",
            external_id="future:1",
            data={"factions_raised": ["Guardians of the Vale"]},
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _client_faction(self, name: str, external_id: str) -> int:
        return self.db.upsert_entity(
            kind="faction",
            name=name,
            external_id=external_id,
            external_namespace="eqclient:faction",
        )

    def _derived_rows(self):
        rows = self.db.conn.execute(
            """
            SELECT r.*,e.name AS faction_name
            FROM entity_relationships r
            JOIN entities e ON e.id=r.target_entity_id
            WHERE r.source_entity_id=?
              AND r.relation IN ('raises_faction','lowers_faction')
            ORDER BY r.relation,e.name,r.id
            """,
            (self.quest,),
        ).fetchall()
        result = []
        for row in rows:
            data = json.loads(row["data_json"] or "{}")
            if data.get("derived_from") == DERIVED_FROM:
                result.append((row, data))
        return result

    def test_exact_unique_client_factions_link_and_gaps_remain_unresolved(self):
        stats = QuestFactionReconciliationCatalog(self.db).reconcile()
        self.assertEqual(stats.quests_scanned, 1)
        self.assertEqual(stats.faction_names, 4)
        self.assertEqual(stats.linked, 2)
        self.assertEqual(stats.ambiguous, 1)
        self.assertEqual(stats.unresolved, 1)
        self.assertEqual(stats.stale_removed, 0)

        derived = self._derived_rows()
        self.assertEqual(len(derived), 2)
        by_relation = {str(row["relation"]): (row, data) for row, data in derived}
        raised, raised_data = by_relation["raises_faction"]
        lowered, lowered_data = by_relation["lowers_faction"]

        self.assertEqual(int(raised["target_entity_id"]), self.guardians)
        self.assertNotEqual(int(raised["target_entity_id"]), self.provider_guardians)
        self.assertEqual(str(raised["evidence"]), "Factions Raised: Guardians of the Vale")
        self.assertEqual(raised_data["source_field"], "Factions Raised")
        self.assertEqual(raised_data["identity_policy"], "exact_unique_eqclient_faction_name")
        self.assertEqual(int(lowered["target_entity_id"]), self.enemies)
        self.assertEqual(lowered_data["raw_name"], "Enemies of the Vale")

        # Ambiguous/missing names remain in the original structured quest metadata and
        # are not replaced with guessed faction entities.
        quest_data = json.loads(self.db.entity(self.quest)["data_json"])
        self.assertIn("Twin Standing", quest_data["factions_raised"])
        self.assertIn("Missing Standing", quest_data["factions_raised"])
        target_ids = {int(row["target_entity_id"]) for row, _data in derived}
        self.assertNotIn(self.twin_one, target_ids)
        self.assertNotIn(self.twin_two, target_ids)

        # The future-provider fixture is intentionally ignored until that source has an
        # explicit structured contract of its own.
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE source_entity_id=?",
                (self.future_quest,),
            ).fetchone()[0],
            0,
        )

    def test_rebuild_removes_only_owned_stale_edges_and_is_idempotent(self):
        catalog = QuestFactionReconciliationCatalog(self.db)
        first = catalog.reconcile()
        self.assertEqual(first.linked, 2)

        second = catalog.reconcile()
        self.assertEqual(second.stale_removed, 2)
        self.assertEqual(second.linked, 2)
        self.assertEqual(len(self._derived_rows()), 2)

        self.db.conn.execute(
            "UPDATE entities SET data_json=? WHERE id=?",
            (json.dumps({"factions_lowered": ["Enemies of the Vale"]}), self.quest),
        )
        self.db.conn.commit()
        third = catalog.reconcile()
        self.assertEqual(third.stale_removed, 2)
        self.assertEqual(third.faction_names, 1)
        self.assertEqual(third.linked, 1)
        derived = self._derived_rows()
        self.assertEqual(len(derived), 1)
        self.assertEqual(str(derived[0][0]["relation"]), "lowers_faction")

        manual = self.db.conn.execute(
            """
            SELECT data_json FROM entity_relationships
            WHERE source_entity_id=? AND target_entity_id=? AND relation='raises_faction'
            """,
            (self.quest, self.manual_faction),
        ).fetchone()
        self.assertIsNotNone(manual)
        self.assertEqual(json.loads(manual["data_json"])["derived_from"], "manual_fixture")

    def test_finalization_compiles_edges_and_runtime_projects_them_read_only(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        report = create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="quest-faction-test",
        )
        self.assertEqual(report.quest_faction_reconciliation["quests_scanned"], 1)
        self.assertEqual(report.quest_faction_reconciliation["linked"], 2)
        self.assertEqual(report.quest_faction_reconciliation["ambiguous"], 1)
        self.assertEqual(report.quest_faction_reconciliation["unresolved"], 1)

        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            context, status = build_world_entity_context(
                runtime,
                "A Question of Allegiance",
                "quest",
            )
            self.assertEqual(status, "exact")
            self.assertIsNotNone(context)
            assert context is not None
            derived = [
                row
                for row in context.relationships
                if row.derived_from == DERIVED_FROM
            ]
            self.assertEqual(
                {(row.relation, row.other_entity_id) for row in derived},
                {
                    ("raises_faction", self.guardians),
                    ("lowers_faction", self.enemies),
                },
            )
            self.assertTrue(all(row.source_name == "Allakhazam" for row in derived))
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_relationships SET relation='mutated'")
            with self.assertRaises(RuntimeError):
                QuestFactionReconciliationCatalog(runtime).reconcile()
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
