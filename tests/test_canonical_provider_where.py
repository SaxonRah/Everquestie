from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.locations import location_evidence_for_entity, where_text
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class CanonicalProviderWhereTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

        self.client_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.client_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )
        self.client_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="397",
            external_namespace="eqclient:zone",
        )

        stone_page = self._page("zone:351", "The Stone Hive", "zone")
        blight_page = self._page("zone:202", "Blightfire Moors", "zone")
        mesa_page = self._page("zone:397", "Goru'kar Mesa", "zone")
        self.provider_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            source_page_id=stone_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=351",
            external_id="zone:351",
        )
        self.provider_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            source_page_id=blight_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=202",
            external_id="zone:202",
        )
        self.provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            source_page_id=mesa_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=397",
            external_id="zone:397",
        )
        self.db.upsert_relationship(
            self.provider_stone,
            self.provider_blight,
            "connected_to",
            source_page_id=stone_page,
            evidence="Blightfire Moors / south",
            data={"confidence": "structured", "direction": "south"},
        )

        self.linked_page = self._page("npc:2001", "Linked Scout", "npc")
        self.linked_npc = self.db.upsert_entity(
            kind="npc",
            name="Linked Scout",
            source_page_id=self.linked_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=2001",
            external_id="npc:2001",
        )
        self.db.add_location(
            self.linked_npc,
            zone_entity_id=self.provider_stone,
            y=125.0,
            x=-42.0,
            z=7.0,
            label="quest starter",
            source_page_id=self.linked_page,
            evidence="Linked Scout at 125, -42, 7",
        )

        self.candidate_page = self._page("npc:2002", "Candidate Scout", "npc")
        self.candidate_npc = self.db.upsert_entity(
            kind="npc",
            name="Candidate Scout",
            source_page_id=self.candidate_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=2002",
            external_id="npc:2002",
        )
        self.db.add_location(
            self.candidate_npc,
            zone_entity_id=self.provider_mesa,
            y=10.0,
            x=20.0,
            z=1.0,
            label="reported spawn",
            source_page_id=self.candidate_page,
            evidence="Candidate Scout at 10, 20, 1",
        )

        self.client_page = self._page("npc:2003", "Client Scout", "npc")
        self.client_npc = self.db.upsert_entity(
            kind="npc",
            name="Client Scout",
            source_page_id=self.client_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=2003",
            external_id="npc:2003",
        )
        self.db.add_location(
            self.client_npc,
            zone_entity_id=self.client_stone,
            y=5.0,
            x=6.0,
            label="client-zone location",
            source_page_id=self.client_page,
            evidence="Direct canonical location",
        )

        ProviderZoneReconciliationCatalog(self.db).reconcile()

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _page(self, key: str, title: str, entity_type: str) -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/{key.replace(':', '/')}",
            title=title,
            entity_type=entity_type,
            sha256=key,
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="mirror-2026-08-14",
        )

    def test_linked_provider_location_projects_to_gameplay_zone_and_preserves_source_zone(self):
        rows = location_evidence_for_entity(
            self.db,
            self.linked_npc,
            include_maps=False,
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.zone_entity_id, self.client_stone)
        self.assertEqual(row.zone_name, "The Stone Hive")
        self.assertEqual(row.source_zone_entity_id, self.provider_stone)
        self.assertEqual(row.source_zone_name, "The Stone Hive")
        self.assertEqual(row.zone_projection_status, "linked_provider")
        self.assertTrue(row.navigable)
        self.assertEqual(row.loc_text, "Y=125 X=-42 Z=7")

        text = where_text(self.db, self.linked_npc)
        self.assertIn("The Stone Hive | Y=125 X=-42 Z=7", text)
        self.assertNotIn("not map-targetable", text)

    def test_candidate_provider_location_remains_visible_but_has_no_gameplay_zone(self):
        rows = location_evidence_for_entity(
            self.db,
            self.candidate_npc,
            include_maps=False,
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsNone(row.zone_entity_id)
        self.assertEqual(row.zone_name, "Goru'kar Mesa")
        self.assertEqual(row.source_zone_entity_id, self.provider_mesa)
        self.assertEqual(row.zone_projection_status, "provider_candidate")
        self.assertFalse(row.navigable)

        text = where_text(self.db, self.candidate_npc)
        self.assertIn("Goru'kar Mesa | Y=10 X=20 Z=1", text)
        self.assertIn("provider_candidate; not map-targetable", text)

    def test_direct_client_zone_location_remains_canonical(self):
        row = location_evidence_for_entity(
            self.db,
            self.client_npc,
            include_maps=False,
        )[0]
        self.assertEqual(row.zone_entity_id, self.client_stone)
        self.assertIsNone(row.source_zone_entity_id)
        self.assertEqual(row.zone_projection_status, "canonical")
        self.assertTrue(row.navigable)

    def test_finalized_runtime_preserves_projection_without_provider_reconciliation_writes(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="canonical-provider-where-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            linked = location_evidence_for_entity(
                runtime,
                self.linked_npc,
                include_maps=False,
            )[0]
            candidate = location_evidence_for_entity(
                runtime,
                self.candidate_npc,
                include_maps=False,
            )[0]
            self.assertEqual(linked.zone_entity_id, self.client_stone)
            self.assertEqual(linked.source_zone_entity_id, self.provider_stone)
            self.assertTrue(linked.navigable)
            self.assertIsNone(candidate.zone_entity_id)
            self.assertEqual(candidate.zone_projection_status, "provider_candidate")
            self.assertFalse(candidate.navigable)
            self.assertIn("provider_candidate; not map-targetable", where_text(runtime, self.candidate_npc))
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE zone_provider_bindings SET status='linked'")
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
