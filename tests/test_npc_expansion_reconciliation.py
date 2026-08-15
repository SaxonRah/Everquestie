from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.npc_expansion_reconciliation import (
    DERIVED_FROM,
    RELATION,
    NPCExpansionReconciliationCatalog,
)
from eqquest.runtime import RuntimeDatabase
from eqquest.world_entity_context import build_world_entity_context


class NPCExpansionReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

        self.serpent = self._client_expansion("The Serpent's Spine", "12")
        self.manual_expansion = self._client_expansion("Manual Expansion", "13")
        self.twin_one = self._client_expansion("Twin Expansion", "21")
        self.twin_two = self._client_expansion("Twin Expansion", "22")

        npc_page = self._source("npc:1001", "Scout Fana", "npc", "Allakhazam")
        self.npc = self.db.upsert_entity(
            kind="npc",
            name="Scout Fana",
            source_page_id=npc_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1001",
            external_id="npc:1001",
            data={"npc_type": "Quest NPC", "expansion": "The Serpent's Spine"},
        )
        ambiguous_page = self._source("npc:1002", "Twin Scout", "npc", "Allakhazam")
        self.ambiguous_npc = self.db.upsert_entity(
            kind="npc",
            name="Twin Scout",
            source_page_id=ambiguous_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1002",
            external_id="npc:1002",
            data={"expansion": "Twin Expansion"},
        )
        missing_page = self._source("npc:1003", "Unknown Scout", "npc", "Allakhazam")
        self.missing_npc = self.db.upsert_entity(
            kind="npc",
            name="Unknown Scout",
            source_page_id=missing_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1003",
            external_id="npc:1003",
            data={"expansion": "Unreleased Expansion Name"},
        )

        # A provider-only same-name expansion is not an identity candidate.
        self.provider_serpent = self.db.upsert_entity(
            kind="expansion",
            name="The Serpent's Spine",
            external_id="provider:tss",
        )

        # An unrelated/manual relationship with the same relation vocabulary must
        # survive compiler rebuilds because it is not owned by this compiler.
        self.db.upsert_relationship(
            self.npc,
            self.manual_expansion,
            RELATION,
            source_page_id=npc_page,
            evidence="manual curated expansion fact",
            data={"confidence": "curated", "derived_from": "manual_fixture"},
        )

        future_page = self._source("npc:future:1", "Future NPC", "npc", "FutureProvider")
        self.future_npc = self.db.upsert_entity(
            kind="npc",
            name="Future NPC",
            source_page_id=future_page,
            source_url="future://npc/1",
            external_id="future:1",
            data={"expansion": "The Serpent's Spine"},
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _client_expansion(self, name: str, external_id: str) -> int:
        return self.db.upsert_entity(
            kind="expansion",
            name=name,
            external_id=external_id,
            external_namespace="eqclient:expansion",
        )

    def _source(self, key: str, title: str, entity_type: str, source_name: str) -> int:
        return self.db.upsert_source_page(
            url=(
                f"https://everquest.allakhazam.com/{key.replace(':', '/')}"
                if source_name == "Allakhazam"
                else f"future://{key.replace(':', '/')}"
            ),
            title=title,
            entity_type=entity_type,
            sha256=key,
            plain_text=title,
            raw_html="<html></html>",
            source_name=source_name,
            source_kind="local_mirror" if source_name == "Allakhazam" else "fixture",
            source_key=key,
            source_version="mirror-2026-08-14" if source_name == "Allakhazam" else "",
        )

    def _owned_rows(self):
        rows = self.db.conn.execute(
            """
            SELECT r.*,e.name AS expansion_name
            FROM entity_relationships r
            JOIN entities e ON e.id=r.target_entity_id
            WHERE r.relation=?
            ORDER BY r.source_entity_id,e.name,r.id
            """,
            (RELATION,),
        ).fetchall()
        result = []
        for row in rows:
            data = json.loads(row["data_json"] or "{}")
            if data.get("derived_from") == DERIVED_FROM:
                result.append((row, data))
        return result

    def test_exact_unique_client_expansion_links_and_gaps_stay_raw(self):
        stats = NPCExpansionReconciliationCatalog(self.db).reconcile()
        self.assertEqual(stats.npcs_scanned, 3)
        self.assertEqual(stats.expansion_names, 3)
        self.assertEqual(stats.linked, 1)
        self.assertEqual(stats.ambiguous, 1)
        self.assertEqual(stats.unresolved, 1)
        self.assertEqual(stats.stale_removed, 0)

        owned = self._owned_rows()
        self.assertEqual(len(owned), 1)
        row, data = owned[0]
        self.assertEqual(int(row["source_entity_id"]), self.npc)
        self.assertEqual(int(row["target_entity_id"]), self.serpent)
        self.assertNotEqual(int(row["target_entity_id"]), self.provider_serpent)
        self.assertEqual(str(row["evidence"]), "Expansion: The Serpent's Spine")
        self.assertEqual(data["source_field"], "Expansion")
        self.assertEqual(data["identity_policy"], "exact_unique_eqclient_expansion_name")

        # Ambiguous/missing names stay as source metadata and do not guess targets.
        self.assertEqual(
            json.loads(self.db.entity(self.ambiguous_npc)["data_json"])["expansion"],
            "Twin Expansion",
        )
        target_ids = {int(r["target_entity_id"]) for r, _data in owned}
        self.assertNotIn(self.twin_one, target_ids)
        self.assertNotIn(self.twin_two, target_ids)
        self.assertEqual(
            json.loads(self.db.entity(self.missing_npc)["data_json"])["expansion"],
            "Unreleased Expansion Name",
        )

        # Arbitrary future-provider JSON is not silently interpreted as Allakhazam's
        # structured NPC source contract.
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE source_entity_id=?",
                (self.future_npc,),
            ).fetchone()[0],
            0,
        )

    def test_rebuild_is_idempotent_and_removes_only_owned_stale_edges(self):
        catalog = NPCExpansionReconciliationCatalog(self.db)
        first = catalog.reconcile()
        self.assertEqual(first.linked, 1)
        second = catalog.reconcile()
        self.assertEqual(second.stale_removed, 1)
        self.assertEqual(second.linked, 1)
        self.assertEqual(len(self._owned_rows()), 1)

        self.db.conn.execute(
            "UPDATE entities SET data_json=? WHERE id=?",
            (json.dumps({"npc_type": "Quest NPC"}), self.npc),
        )
        self.db.conn.commit()
        third = catalog.reconcile()
        self.assertEqual(third.stale_removed, 1)
        self.assertEqual(third.expansion_names, 2)
        self.assertEqual(third.linked, 0)
        self.assertEqual(len(self._owned_rows()), 0)

        manual = self.db.conn.execute(
            """
            SELECT data_json FROM entity_relationships
            WHERE source_entity_id=? AND target_entity_id=? AND relation=?
            """,
            (self.npc, self.manual_expansion, RELATION),
        ).fetchone()
        self.assertIsNotNone(manual)
        self.assertEqual(json.loads(manual["data_json"])["derived_from"], "manual_fixture")

    def test_finalization_compiles_expansion_edge_and_runtime_reads_it(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        report = create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="npc-expansion-test",
        )
        self.assertEqual(report.npc_expansion_reconciliation["npcs_scanned"], 3)
        self.assertEqual(report.npc_expansion_reconciliation["linked"], 1)
        self.assertEqual(report.npc_expansion_reconciliation["ambiguous"], 1)
        self.assertEqual(report.npc_expansion_reconciliation["unresolved"], 1)

        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            context, status = build_world_entity_context(runtime, "Scout Fana", "npc")
            self.assertEqual(status, "exact")
            self.assertIsNotNone(context)
            assert context is not None
            expansion = next(
                row
                for row in context.relationships
                if row.relation == RELATION and row.derived_from == DERIVED_FROM
            )
            self.assertEqual(expansion.other_entity_id, self.serpent)
            self.assertEqual(expansion.other_kind, "expansion")
            self.assertEqual(expansion.source_name, "Allakhazam")
            self.assertEqual(expansion.data["raw_name"], "The Serpent's Spine")
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_relationships SET relation='mutated'")
            with self.assertRaises(RuntimeError):
                NPCExpansionReconciliationCatalog(runtime).reconcile()
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
