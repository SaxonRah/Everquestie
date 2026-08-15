from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_context import build_zone_context, zone_context_text
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class ProviderZoneProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.working = self.root / "working.sqlite3"
        self.db = Database(self.working)

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone_fixture(self):
        client_stone = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            external_id="400",
            external_namespace="eqclient:zone",
            data={"authoritative_identity_source": "EverQuest Client"},
        )
        client_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="401",
            external_namespace="eqclient:zone",
        )
        client_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="402",
            external_namespace="eqclient:zone",
        )
        provider_stone = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            external_id="zone:100",
            external_namespace="allakhazam:zone",
        )
        provider_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="zone:101",
            external_namespace="allakhazam:zone",
        )
        provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="zone:102",
            external_namespace="allakhazam:zone",
        )
        page = self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/zone.html?zstrat=100",
            title="Stone Hive :: EverQuest",
            entity_type="zone",
            sha256="stone-hive-provider",
            plain_text="Connected Zones: Blightfire Moors",
            raw_html="",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key="zone:100",
            source_version="mirror-test",
        )
        self.db.upsert_relationship(
            provider_stone,
            provider_blight,
            "connected_to",
            source_page_id=page,
            evidence="Blightfire Moors / North",
            data={"confidence": "structured", "direction": "North"},
        )

        guardian = self.db.upsert_entity(
            kind="npc",
            name="A Hive Guardian",
            external_id="npc:900",
            external_namespace="allakhazam:npc",
        )
        self.db.add_location(
            guardian,
            zone_entity_id=provider_stone,
            x=123.0,
            y=456.0,
            z=9.0,
            label="provider spawn",
            source_page_id=page,
            evidence="structured Allakhazam Stone Hive location",
        )

        unprojected = self.db.upsert_entity(
            kind="npc",
            name="A Mesa Candidate",
            external_id="npc:901",
            external_namespace="allakhazam:npc",
        )
        self.db.add_location(
            unprojected,
            zone_entity_id=provider_mesa,
            x=10.0,
            y=20.0,
            z=3.0,
            label="candidate-only spawn",
            source_page_id=page,
            evidence="same-name provider zone without corroboration",
        )
        return {
            "client_stone": client_stone,
            "client_blight": client_blight,
            "client_mesa": client_mesa,
            "provider_stone": provider_stone,
            "provider_blight": provider_blight,
            "provider_mesa": provider_mesa,
            "guardian": guardian,
            "unprojected": unprojected,
        }

    def test_builder_zone_context_projects_only_linked_provider_locations(self):
        ids = self._zone_fixture()
        stats = ProviderZoneReconciliationCatalog(self.db).reconcile()
        self.assertEqual(stats.linked, 2)
        self.assertEqual(stats.candidate, 1)

        context, status = build_zone_context(self.db, "400")
        self.assertEqual(status, "linked")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.identity.entity_id, ids["client_stone"])
        self.assertEqual(len(context.provider_bindings), 1)
        self.assertEqual(
            context.provider_bindings[0].provider_zone_entity_id,
            ids["provider_stone"],
        )

        guardian_rows = [row for row in context.locations if row.entity_id == ids["guardian"]]
        self.assertEqual(len(guardian_rows), 1)
        guardian = guardian_rows[0]
        self.assertEqual(guardian.projected_from_zone_entity_id, ids["provider_stone"])
        self.assertEqual(guardian.location.zone_entity_id, ids["client_stone"])
        self.assertEqual(guardian.location.zone_name, "Stone Hive")
        self.assertEqual((guardian.location.x, guardian.location.y, guardian.location.z), (123.0, 456.0, 9.0))
        self.assertEqual(guardian.location.source_name, "Allakhazam")
        self.assertNotIn(ids["unprojected"], {row.entity_id for row in context.locations})

        text = zone_context_text(self.db, "Stone Hive")
        self.assertIn("Projected provider knowledge:", text)
        self.assertIn("Stone Hive | 1 structured zone-link corroboration(s)", text)
        self.assertIn("A Hive Guardian", text)

    def test_snapshot_finalization_compiles_bindings_and_runtime_projects_read_only(self):
        ids = self._zone_fixture()
        # Do not run ProviderZoneReconciliationCatalog.reconcile() here. Snapshot
        # finalization owns deterministic builder-side compilation after all providers.
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        report = create_knowledge_snapshot(
            self.working,
            snapshot,
            snapshot_version="provider-zone-projection-test",
        )
        self.assertEqual(report.provider_zone_reconciliation["linked"], 2)
        self.assertEqual(report.provider_zone_reconciliation["candidate"], 1)

        raw = sqlite3.connect(snapshot)
        raw.row_factory = sqlite3.Row
        try:
            rows = raw.execute(
                "SELECT provider_zone_entity_id,gameplay_zone_entity_id,status "
                "FROM zone_provider_bindings ORDER BY provider_zone_entity_id"
            ).fetchall()
            self.assertEqual(len(rows), 3)
            linked = {
                int(row["provider_zone_entity_id"]): int(row["gameplay_zone_entity_id"])
                for row in rows
                if row["status"] == "linked"
            }
            self.assertEqual(linked[ids["provider_stone"]], ids["client_stone"])
            self.assertEqual(linked[ids["provider_blight"]], ids["client_blight"])
            meta = dict(raw.execute("SELECT key,value FROM app_meta").fetchall())
            self.assertEqual(meta["provider_zone_catalog_version"], "1")
            self.assertIn("provider_zone_catalog_coverage", meta)
        finally:
            raw.close()

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
            self.assertEqual(context.identity.entity_id, ids["client_stone"])
            self.assertEqual({row.entity_id for row in context.locations}, {ids["guardian"]})
            row = context.locations[0]
            self.assertEqual(row.projected_from_zone_entity_id, ids["provider_stone"])
            self.assertEqual(row.location.zone_entity_id, ids["client_stone"])
            self.assertEqual(len(context.provider_bindings), 1)

            # Runtime knowledge remains immutable; reconciliation never runs here.
            with self.assertRaises(Exception):
                runtime.conn.execute(
                    "UPDATE zone_provider_bindings SET status='candidate' "
                    "WHERE provider_zone_entity_id=?",
                    (ids["provider_stone"],),
                )
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
