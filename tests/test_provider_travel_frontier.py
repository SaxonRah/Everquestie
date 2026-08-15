from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from eqquest.db import Database
from eqquest.provider_travel_frontier import ProviderTravelFrontierAudit, provider_travel_frontier_text
from eqquest.provider_zone_travel import ProviderZoneTravelCatalog
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class ProviderTravelFrontierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "knowledge.sqlite3"
        self.db = Database(self.path)

    def tearDown(self):
        if self.db is not None:
            self.db.close()
        self.tmp.cleanup()

    def _client(self, name: str, zone_id: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=zone_id,
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )

    def _provider(self, name: str, provider_id: str) -> tuple[int, int]:
        page = self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/db/zone.html?zstrat={provider_id}",
            title=f"{name} :: EverQuest",
            entity_type="zone",
            sha256=f"sha-{provider_id}",
            plain_text="Connected Zones",
            raw_html="",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=f"zone:{provider_id}",
            source_version="frontier-test",
        )
        entity = self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=f"zone:{provider_id}",
            external_namespace="allakhazam:zone",
            source_page_id=page,
            merge_by_name=False,
        )
        return entity, page

    def _connected(self, source: int, target: int, page: int, direction: str = "Both") -> None:
        self.db.upsert_relationship(
            source,
            target,
            "connected_to",
            source_page_id=page,
            evidence=f"Connected Zones / {direction}",
            data={"confidence": "structured", "direction": direction},
        )

    def _linked_pair(self):
        stone = self._client("Stone Hive", "400")
        blight = self._client("Blightfire Moors", "401")
        p_stone, stone_page = self._provider("Stone Hive", "100")
        p_blight, _ = self._provider("Blightfire Moors", "101")
        self._connected(p_stone, p_blight, stone_page)
        ProviderZoneReconciliationCatalog(self.db).reconcile()
        return stone, blight, p_stone, p_blight

    def test_compiled_relationship_is_traced_to_final_edge(self):
        _stone, blight, _p_stone, _p_blight = self._linked_pair()
        ProviderZoneTravelCatalog(self.db).reconcile()

        result = ProviderTravelFrontierAudit(self.db).zone("Blightfire Moors")
        self.assertEqual(result.canonical_zone_entity_id, blight)
        self.assertEqual(result.classification, "compiled")
        self.assertEqual(result.incoming_count, 1)
        self.assertEqual(result.outgoing_count, 1)
        self.assertEqual(len(result.relationships), 1)
        relation = result.relationships[0]
        self.assertEqual(relation.classification, "compiled")
        self.assertIsNotNone(relation.compiled_edge_id)
        self.assertEqual(relation.interpreted_source_name, "Stone Hive")
        self.assertEqual(relation.interpreted_target_name, "Blightfire Moors")
        self.assertTrue(relation.direction_bidirectional)

        payload = result.as_dict()
        self.assertEqual(payload["compiler_eligible_relationship_count"], 1)
        self.assertEqual(payload["bindings"][0]["source_key"], "zone:101")

    def test_compiler_eligible_missing_edge_is_a_distinct_defect(self):
        self._linked_pair()
        result = ProviderTravelFrontierAudit(self.db).zone("Stone Hive")
        self.assertEqual(result.classification, "provider_rows_uncompiled")
        self.assertEqual(result.relationships[0].classification, "compiler_eligible_missing_edge")
        self.assertIsNone(result.relationships[0].compiled_edge_id)

    def test_candidate_provider_page_without_connections_is_named_explicitly(self):
        target = self._client("Labyrinth of Spite", "900")
        provider, _page = self._provider("Labyrinth of Spite", "900-provider")
        stats = ProviderZoneReconciliationCatalog(self.db).reconcile()
        self.assertEqual(stats.candidate, 1)

        result = ProviderTravelFrontierAudit(self.db).zone("Labyrinth of Spite")
        self.assertEqual(result.canonical_zone_entity_id, target)
        self.assertEqual(result.classification, "no_structured_provider_topology")
        self.assertEqual(len(result.bindings), 1)
        self.assertEqual(result.bindings[0]["provider_zone_entity_id"], provider)
        self.assertEqual(result.bindings[0]["status"], "candidate")
        self.assertEqual(result.bindings[0]["source_key"], "zone:900-provider")
        self.assertEqual(result.relationships, ())

    def test_blocked_target_is_visible_alongside_compiled_rows(self):
        stone, _blight, p_stone, _p_blight = self._linked_pair()
        unknown, _unknown_page = self._provider("Unknown Expansion Zone", "999")
        stone_page = self.db.conn.execute(
            "SELECT source_page_id FROM entities WHERE id=?", (p_stone,)
        ).fetchone()["source_page_id"]
        self._connected(p_stone, unknown, int(stone_page), "North")

        ProviderZoneReconciliationCatalog(self.db).reconcile()
        stats = ProviderZoneTravelCatalog(self.db).reconcile()
        self.assertEqual(stats.linked, 1)
        self.assertEqual(stats.blocked_target, 1)

        result = ProviderTravelFrontierAudit(self.db).zone("Stone Hive")
        self.assertEqual(result.canonical_zone_entity_id, stone)
        classes = {relationship.classification for relationship in result.relationships}
        self.assertIn("compiled", classes)
        self.assertIn("blocked_target", classes)
        blocked = next(r for r in result.relationships if r.classification == "blocked_target")
        self.assertEqual(blocked.target_provider_name, "Unknown Expansion Zone")
        self.assertIsNone(blocked.canonical_target_entity_id)

    def test_read_only_snapshot_audit_does_not_mutate_database(self):
        self._linked_pair()
        ProviderZoneTravelCatalog(self.db).reconcile()
        self.db.close()
        self.db = None
        before = self.path.read_bytes()

        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            result = ProviderTravelFrontierAudit(SimpleNamespace(conn=conn)).zone("Stone Hive")
            self.assertEqual(result.classification, "compiled")
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM entities")
        finally:
            conn.close()
        self.assertEqual(self.path.read_bytes(), before)

    def test_human_report_explains_relationship_direction_and_page(self):
        self._linked_pair()
        ProviderZoneTravelCatalog(self.db).reconcile()
        text = provider_travel_frontier_text(self.db, ("Stone Hive",))
        self.assertIn("EverQuestie provider travel frontier audit", text)
        self.assertIn("Stone Hive: compiled", text)
        self.assertIn("page=zone:100", text)
        self.assertIn("direction=Both / both", text)
        self.assertIn("Stone Hive -> Blightfire Moors (two-way)", text)


if __name__ == "__main__":
    unittest.main()
