from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_context import build_zone_context, zone_context_text
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class ProviderZoneWorldContextTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.working = self.root / "working.sqlite3"
        self.db = Database(self.working)

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _client_zone(self, name: str, zone_id: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=zone_id,
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )

    def _provider_zone(self, name: str, provider_id: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=f"zone:{provider_id}",
            external_namespace="allakhazam:zone",
            merge_by_name=False,
        )

    def _page(self, name: str, key: str, *, source_name: str = "Allakhazam") -> int:
        url = (
            f"https://everquest.allakhazam.com/db/zone.html?zstrat={key}"
            if source_name == "Allakhazam"
            else f"test://{source_name.casefold().replace(' ', '-')}/{key}"
        )
        return self.db.upsert_source_page(
            url=url,
            title=name,
            entity_type="zone",
            sha256=f"{source_name}-{key}",
            plain_text="structured provider fixture",
            raw_html="",
            source_name=source_name,
            source_kind="local_mirror" if source_name == "Allakhazam" else "fixture",
            source_key=f"zone:{key}",
            source_version="world-context-test",
        )

    def _entity(self, kind: str, name: str, external_id: str) -> int:
        return self.db.upsert_entity(
            kind=kind,
            name=name,
            external_id=external_id,
            external_namespace=f"allakhazam:{kind}",
            merge_by_name=False,
        )

    def _fixture(self):
        client_stone = self._client_zone("Stone Hive", "400")
        self._client_zone("Blightfire Moors", "401")
        self._client_zone("Goru'kar Mesa", "402")
        provider_stone = self._provider_zone("Stone Hive", "100")
        provider_blight = self._provider_zone("Blightfire Moors", "101")
        provider_mesa = self._provider_zone("Goru'kar Mesa", "102")

        stone_page = self._page("Stone Hive :: EverQuest", "100")
        self.db.upsert_relationship(
            provider_stone,
            provider_blight,
            "connected_to",
            source_page_id=stone_page,
            evidence="Blightfire Moors / North",
            data={"confidence": "structured", "direction": "North"},
        )

        npc = self._entity("npc", "A Hive Guardian", "npc:900")
        item = self._entity("item", "Stone Hive Carapace", "item:901")
        starter = self._entity("quest", "The Hive's First Task", "quest:902")
        occurring = self._entity("quest", "Into the Hive", "quest:903")
        candidate_npc = self._entity("npc", "A Mesa Candidate", "npc:904")
        weak_npc = self._entity("npc", "A Weak Inference", "npc:905")
        direct_npc = self._entity("npc", "A Canonical Observer", "npc:906")

        self.db.upsert_relationship(
            npc,
            provider_stone,
            "found_in",
            source_page_id=stone_page,
            evidence="NPCs_t preview: A Hive Guardian",
            data={"confidence": "structured", "preview": True, "shown": 25, "total": 342},
        )
        self.db.upsert_relationship(
            item,
            provider_stone,
            "found_in",
            source_page_id=stone_page,
            evidence="Items_t preview: Stone Hive Carapace",
            data={"confidence": "structured", "preview": True, "shown": 25, "total": 178},
        )
        self.db.upsert_relationship(
            starter,
            provider_stone,
            "starts_in",
            source_page_id=stone_page,
            evidence="Quests_Starting_t preview: The Hive's First Task",
            data={"confidence": "structured", "preview": True, "shown": 25, "total": 47},
        )
        self.db.upsert_relationship(
            occurring,
            provider_stone,
            "occurs_in",
            source_page_id=stone_page,
            evidence="Quests_In_t preview: Into the Hive",
            data={"confidence": "structured", "preview": True, "shown": 25, "total": 91},
        )

        # Same-name Mesa is only a candidate because it has no structured topology
        # corroboration. Its otherwise structured entity relation must not leak into
        # gameplay Mesa or Stone Hive context.
        mesa_page = self._page("Goru'kar Mesa :: EverQuest", "102")
        self.db.upsert_relationship(
            candidate_npc,
            provider_mesa,
            "found_in",
            source_page_id=mesa_page,
            evidence="NPCs_t preview: A Mesa Candidate",
            data={"confidence": "structured", "preview": True, "shown": 25, "total": 200},
        )

        # A weak relation against a projection-safe provider zone is still excluded;
        # the safe zone binding does not launder inferred relationship evidence.
        weak_page = self._page("Weak relation", "weak", source_name="Weak Fixture")
        self.db.upsert_relationship(
            weak_npc,
            provider_stone,
            "found_in",
            source_page_id=weak_page,
            evidence="inferred same-zone relation",
            data={"confidence": "inferred"},
        )

        # Knowledge already attached directly to canonical gameplay identity stays
        # visible; provider-crossing evidence gates do not hide canonical graph facts.
        self.db.upsert_relationship(
            direct_npc,
            client_stone,
            "found_in",
            source_page_id=None,
            evidence="canonical fixture relation",
            data={"confidence": "inferred"},
        )

        return {
            "client_stone": client_stone,
            "provider_stone": provider_stone,
            "provider_mesa": provider_mesa,
            "npc": npc,
            "item": item,
            "starter": starter,
            "occurring": occurring,
            "candidate_npc": candidate_npc,
            "weak_npc": weak_npc,
            "direct_npc": direct_npc,
        }

    def test_builder_context_projects_structured_provider_relationships_with_preview_semantics(self):
        ids = self._fixture()
        stats = ProviderZoneReconciliationCatalog(self.db).reconcile()
        self.assertEqual(stats.linked, 2)
        self.assertEqual(stats.candidate, 1)

        context, status = build_zone_context(self.db, "Stone Hive")
        self.assertEqual(status, "linked")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.identity.entity_id, ids["client_stone"])

        related_ids = {row.entity_id for row in context.related_entities}
        self.assertEqual(
            related_ids,
            {ids["npc"], ids["item"], ids["starter"], ids["occurring"], ids["direct_npc"]},
        )
        self.assertNotIn(ids["candidate_npc"], related_ids)
        self.assertNotIn(ids["weak_npc"], related_ids)
        self.assertEqual(context.related_entity_count, 5)
        self.assertEqual(len(context.known_npcs), 2)
        self.assertEqual(len(context.known_items), 1)
        self.assertEqual(len(context.quests_starting), 1)
        self.assertEqual(len(context.quests_occurring), 1)

        guardian = next(row for row in context.related_entities if row.entity_id == ids["npc"])
        self.assertEqual(guardian.zone_entity_id, ids["client_stone"])
        self.assertEqual(guardian.zone_name, "Stone Hive")
        self.assertEqual(guardian.original_zone_entity_id, ids["provider_stone"])
        self.assertEqual(guardian.projected_from_zone_entity_id, ids["provider_stone"])
        self.assertEqual(guardian.source_name, "Allakhazam")
        self.assertEqual(guardian.confidence, "structured")
        self.assertTrue(guardian.preview)
        self.assertEqual(guardian.shown, 25)
        self.assertEqual(guardian.total, 342)
        self.assertEqual(guardian.preview_text, "preview 25 of 342")

        direct = next(row for row in context.related_entities if row.entity_id == ids["direct_npc"])
        self.assertEqual(direct.original_zone_entity_id, ids["client_stone"])
        self.assertIsNone(direct.projected_from_zone_entity_id)

    def test_zone_context_text_exposes_known_world_facts_without_claiming_completeness(self):
        ids = self._fixture()
        ProviderZoneReconciliationCatalog(self.db).reconcile()

        text = zone_context_text(self.db, "400", relationship_limit=10)
        self.assertIn("Known NPCs (evidence-backed; not exhaustive):", text)
        self.assertIn("Quests starting here (evidence-backed; not exhaustive):", text)
        self.assertIn("Quests occurring here (evidence-backed; not exhaustive):", text)
        self.assertIn("Items associated with this zone (evidence-backed; not exhaustive):", text)
        self.assertIn("A Hive Guardian | Allakhazam world-context-test | preview 25 of 342", text)
        self.assertIn("The Hive's First Task", text)
        self.assertIn("Into the Hive", text)
        self.assertIn("Stone Hive Carapace", text)
        self.assertIn("A Canonical Observer", text)
        self.assertNotIn("A Mesa Candidate", text)
        self.assertNotIn("A Weak Inference", text)
        self.assertIn("Projected provider knowledge:", text)
        self.assertNotIn(str(ids["provider_mesa"]), text)

    def test_finalized_runtime_projects_same_relationship_context_read_only(self):
        ids = self._fixture()
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        report = create_knowledge_snapshot(
            self.working,
            snapshot,
            snapshot_version="provider-zone-world-context-test",
        )
        self.assertEqual(report.provider_zone_reconciliation["linked"], 2)
        self.assertEqual(report.provider_zone_reconciliation["candidate"], 1)

        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            context, status = build_zone_context(runtime, "Stone Hive")
            self.assertEqual(status, "linked")
            self.assertIsNotNone(context)
            assert context is not None
            related_ids = {row.entity_id for row in context.related_entities}
            self.assertEqual(
                related_ids,
                {ids["npc"], ids["item"], ids["starter"], ids["occurring"], ids["direct_npc"]},
            )
            self.assertNotIn(ids["candidate_npc"], related_ids)
            self.assertNotIn(ids["weak_npc"], related_ids)
            self.assertEqual(context.known_npcs[0].zone_entity_id, ids["client_stone"])

            with self.assertRaises(Exception):
                runtime.conn.execute("DELETE FROM entity_relationships")
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
