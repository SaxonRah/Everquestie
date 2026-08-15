from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge import entity_detail_text
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class WorldEntityKnowledgeDetailTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _source_page(self, key: str, title: str, kind: str) -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/{key.replace(':', '/')}",
            title=title,
            entity_type=kind,
            sha256=key,
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="mirror-2026-08-14",
        )

    def _zone_fixture(self):
        client_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )
        client_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="397",
            external_namespace="eqclient:zone",
        )
        stone_page = self._source_page("zone:351", "The Stone Hive", "zone")
        blight_page = self._source_page("zone:202", "Blightfire Moors", "zone")
        mesa_page = self._source_page("zone:397", "Goru'kar Mesa", "zone")
        provider_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            source_page_id=stone_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=351",
            external_id="zone:351",
        )
        provider_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            source_page_id=blight_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=202",
            external_id="zone:202",
        )
        provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            source_page_id=mesa_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=397",
            external_id="zone:397",
        )
        self.db.upsert_relationship(
            provider_stone,
            provider_blight,
            "connected_to",
            source_page_id=stone_page,
            evidence="Blightfire Moors / south",
            data={"confidence": "structured"},
        )
        ProviderZoneReconciliationCatalog(self.db).reconcile()
        return client_stone, client_mesa, provider_stone, provider_mesa

    def test_selected_duplicate_name_uses_entity_id_without_reresolving_name(self):
        page_a = self._source_page("npc:1001", "A Duplicate Scout", "npc")
        page_b = self._source_page("npc:1002", "A Duplicate Scout", "npc")
        npc_a = self.db.upsert_entity(
            kind="npc",
            name="A Duplicate Scout",
            external_id="npc:1001",
            source_page_id=page_a,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1001",
        )
        npc_b = self.db.upsert_entity(
            kind="npc",
            name="A Duplicate Scout",
            external_id="npc:1002",
            source_page_id=page_b,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1002",
        )
        item_a = self.db.upsert_entity(kind="item", name="Scout A Token", external_id="item:a")
        item_b = self.db.upsert_entity(kind="item", name="Scout B Token", external_id="item:b")
        self.db.upsert_relationship(
            npc_a,
            item_a,
            "related_quest",
            source_page_id=page_a,
            evidence="A-only relation",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            npc_b,
            item_b,
            "related_quest",
            source_page_id=page_b,
            evidence="B-only relation",
            data={"confidence": "structured"},
        )

        detail = entity_detail_text(self.db, npc_a)
        self.assertIn("Scout A Token", detail)
        self.assertNotIn("Scout B Token", detail)
        self.assertIn("World relationships (evidence-backed; not exhaustive):", detail)

    def test_linked_and_candidate_provider_locations_render_with_different_actionability(self):
        client_stone, _client_mesa, provider_stone, provider_mesa = self._zone_fixture()
        linked_page = self._source_page("npc:1101", "Linked Scout", "npc")
        linked = self.db.upsert_entity(
            kind="npc",
            name="Linked Scout",
            external_id="npc:1101",
            source_page_id=linked_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1101",
        )
        self.db.add_location(
            linked,
            zone_entity_id=provider_stone,
            y=100.0,
            x=-50.0,
            z=4.0,
            label="spawn",
            source_page_id=linked_page,
            evidence="linked location",
        )
        candidate_page = self._source_page("npc:1102", "Candidate Scout", "npc")
        candidate = self.db.upsert_entity(
            kind="npc",
            name="Candidate Scout",
            external_id="npc:1102",
            source_page_id=candidate_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1102",
        )
        self.db.add_location(
            candidate,
            zone_entity_id=provider_mesa,
            y=10.0,
            x=20.0,
            label="reported spawn",
            source_page_id=candidate_page,
            evidence="candidate location",
        )

        linked_detail = entity_detail_text(self.db, linked)
        self.assertIn("World locations:", linked_detail)
        self.assertIn("The Stone Hive", linked_detail)
        self.assertIn("/loc Y=100 X=-50 Z=4", linked_detail)
        self.assertNotIn("not map-targetable", linked_detail)

        candidate_detail = entity_detail_text(self.db, candidate)
        self.assertIn("Goru'kar Mesa", candidate_detail)
        self.assertIn("provider_candidate; not map-targetable", candidate_detail)
        self.assertNotIn(f"gameplay_zone_entity_id={client_stone}", candidate_detail)

    def test_preview_relationship_semantics_are_preserved_in_knowledge_detail(self):
        zone = self.db.upsert_entity(kind="zone", name="Preview Zone", external_id="zone:preview")
        page = self._source_page("npc:1201", "Preview NPC", "npc")
        npc = self.db.upsert_entity(
            kind="npc",
            name="Preview NPC",
            external_id="npc:1201",
            source_page_id=page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1201",
        )
        self.db.upsert_relationship(
            npc,
            zone,
            "found_in",
            source_page_id=page,
            evidence="known habitat preview",
            data={
                "confidence": "structured",
                "preview": True,
                "shown": 3,
                "total": 17,
            },
        )
        detail = entity_detail_text(self.db, npc)
        self.assertIn("preview 3 of 17", detail)
        self.assertIn("structured", detail)

    def test_runtime_user_progress_does_not_change_knowledge_quest_steps(self):
        page = self._source_page("quest:5001", "Progress Isolation Quest", "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name="Progress Isolation Quest",
            external_id="quest:5001",
            external_namespace="allakhazam:quest",
            source_page_id=page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=5001",
        )
        self.db.add_quest_step(
            quest,
            1,
            "Collect three test tokens",
            zone="Test Zone",
            match={"event": "loot", "item": "Test Token", "count": 3},
            source_page_id=page,
        )
        before = entity_detail_text(self.db, quest)
        self.assertIn("Knowledge quest steps:", before)
        self.assertIn("1. Collect three test tokens", before)
        self.assertNotIn("[done]", before)
        self.assertNotIn("[3/3]", before)

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="knowledge-detail-progress-isolation",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            runtime.track_quest(quest)
            runtime.set_step_progress(quest, 1, 3, True)
            live_step = runtime.quest_steps(quest)[0]
            self.assertEqual(live_step["progress_count"], 3)
            self.assertEqual(live_step["complete"], 1)

            after = entity_detail_text(runtime, quest)
            self.assertIn("Knowledge quest steps:", after)
            self.assertIn("1. Collect three test tokens", after)
            self.assertNotIn("[done]", after)
            self.assertNotIn("[3/3]", after)
            self.assertNotIn("progress_count", after)
            self.assertEqual(before, after)
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
