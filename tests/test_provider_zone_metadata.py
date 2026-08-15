from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.provider_zone_metadata import provider_zone_metadata_for_gameplay_zone
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_context import build_zone_context, zone_context_text
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class ProviderZoneMetadataTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

        self.client_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
            level_min=40,
            level_max=48,
            data={"authority": "client"},
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

        stone_page = self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/zone.html?zstrat=351",
            title="The Stone Hive",
            entity_type="zone",
            sha256="stone",
            plain_text="Stone Hive zone page",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key="zone:351",
            source_version="mirror-2026-08-14",
        )
        self.provider_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            source_page_id=stone_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=351",
            external_id="zone:351",
            level_min=44,
            level_max=52,
            data={
                "hot_zone": True,
                "zone_type": "Outdoor",
                "expansion": "The Serpent's Spine",
                "instanced": "No",
                "keyed": "No",
                "level_range": [44, 52],
            },
        )
        self.provider_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=202",
            external_id="zone:202",
        )
        self.db.upsert_relationship(
            self.provider_stone,
            self.provider_blight,
            "connected_to",
            source_page_id=stone_page,
            evidence="Blightfire Moors / south",
            data={"confidence": "structured", "direction": "south"},
        )

        mesa_page = self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/zone.html?zstrat=397",
            title="Goru'kar Mesa",
            entity_type="zone",
            sha256="mesa",
            plain_text="Mesa zone page",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key="zone:397",
            source_version="mirror-2026-08-14",
        )
        self.provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            source_page_id=mesa_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=397",
            external_id="zone:397",
            level_min=10,
            level_max=20,
            data={"expansion": "provider-only candidate fact"},
        )

        ProviderZoneReconciliationCatalog(self.db).reconcile()

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_metadata_is_separate_source_aware_evidence_not_client_overwrite(self):
        rows = provider_zone_metadata_for_gameplay_zone(self.db, self.client_stone)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.provider_zone_entity_id, self.provider_stone)
        self.assertEqual(row.gameplay_zone_entity_id, self.client_stone)
        self.assertEqual(row.level_range_text, "44-52")
        self.assertEqual(row.expansion, "The Serpent's Spine")
        self.assertEqual(row.instanced, "No")
        self.assertEqual(row.keyed, "No")
        self.assertTrue(row.hot_zone)
        self.assertEqual(row.source_label, "Allakhazam mirror-2026-08-14")

        context, status = build_zone_context(self.db, "The Stone Hive")
        self.assertEqual(status, "linked")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual((context.level_min, context.level_max), (40, 48))
        self.assertEqual(context.data.get("authority"), "client")
        self.assertEqual(context.provider_metadata[0].level_range_text, "44-52")

    def test_candidate_provider_zone_metadata_never_projects(self):
        rows = provider_zone_metadata_for_gameplay_zone(self.db, self.client_mesa)
        self.assertEqual(rows, ())
        context, status = build_zone_context(self.db, "Goru'kar Mesa")
        self.assertEqual(status, "linked")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.provider_metadata, ())

    def test_finalized_runtime_exposes_same_metadata_read_only_and_text_is_source_scoped(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="provider-zone-metadata-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            context, status = build_zone_context(runtime, "The Stone Hive")
            self.assertEqual(status, "linked")
            self.assertIsNotNone(context)
            assert context is not None
            self.assertEqual((context.level_min, context.level_max), (40, 48))
            self.assertEqual(context.provider_metadata[0].level_range_text, "44-52")
            text = zone_context_text(runtime, "The Stone Hive")
            self.assertIn("Provider zone facts (source-specific):", text)
            self.assertIn("Allakhazam mirror-2026-08-14", text)
            self.assertIn("level 44-52", text)
            self.assertIn("The Serpent's Spine", text)
            self.assertIn("hot zone: yes", text)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entities SET level_min=1")
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
