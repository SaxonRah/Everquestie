from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_coverage import ZoneCoverageCatalog, zone_coverage_audit_text
from eqquest.zone_travel import ZoneTravelCatalog


class ZoneCoverageTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zones(self) -> tuple[int, int, int]:
        client_source = self.db.upsert_source_page(
            url="eqclient://Resources/ZoneNames.txt",
            title="ZoneNames",
            entity_type="zone",
            sha256="zones",
            plain_text="fixture",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/ZoneNames.txt",
        )
        stone = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            source_page_id=client_source,
            source_url="eqclient://Resources/ZoneNames.txt",
            external_id="396",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            level_min=40,
            level_max=70,
        )
        mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            source_page_id=client_source,
            source_url="eqclient://Resources/ZoneNames.txt",
            external_id="397",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        future = self.db.upsert_entity(
            kind="zone",
            name="Future Provider Zone",
            external_id="future-1",
            external_namespace="futuremirror:zone",
            merge_by_name=True,
        )
        return stone, mesa, future

    def test_summary_projects_identity_map_and_travel_coverage(self):
        stone, mesa, future = self._zones()
        MapCatalog(self.db)
        ZoneMapCatalog(self.db).ensure_schema()
        self.db.conn.execute(
            """
            INSERT INTO zone_map_bindings(
                source_name,source_version,map_stem,zone_entity_id,zone_name,
                status,reason,catalog_version,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            ("Brewall", "1", "stonehive", stone, "Stone Hive", "linked", "fixture", "1", "now"),
        )
        self.db.conn.commit()
        ZoneTravelCatalog(self.db).add_provider_connection(
            stone,
            mesa,
            source_name="Fixture",
            source_kind="provider",
            source_key="stone-to-mesa",
            evidence="fixture edge",
        )

        summary = ZoneCoverageCatalog(self.db).summary()
        self.assertEqual(summary.zones, 3)
        self.assertEqual(summary.client_identity, 2)
        self.assertEqual(summary.level_data, 1)
        self.assertEqual(summary.mapped, 1)
        self.assertEqual(summary.travel_connected, 2)
        self.assertEqual(summary.isolated, 1)
        self.assertEqual(summary.zones_without_client_identity, ("Future Provider Zone",))
        self.assertIn("Goru'kar Mesa", summary.zones_without_maps)
        self.assertEqual(summary.zones_without_travel, ("Future Provider Zone",))

        rows = {row.name: row for row in ZoneCoverageCatalog(self.db).rows()}
        self.assertEqual(rows["Stone Hive"].travel_outgoing, 1)
        self.assertEqual(rows["Goru'kar Mesa"].travel_incoming, 1)
        self.assertGreaterEqual(rows["Stone Hive"].source_count, 1)

    def test_audit_names_gaps_instead_of_inventing_zone_facts(self):
        self._zones()
        text = zone_coverage_audit_text(self.db)
        self.assertIn("Canonical zones: 3", text)
        self.assertIn("EQ-client identities: 2/3", text)
        self.assertIn("Future Provider Zone", text)
        self.assertIn("Zones without confirmed map binding", text)

    def test_snapshot_persists_release_coverage_and_runtime_can_query_it(self):
        self._zones()
        self.db.close()
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"
        report = create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="zone-coverage-test",
        )
        self.assertEqual(report.zone_coverage["zones"], 3)
        self.assertEqual(report.zone_coverage["client_identity"], 2)

        runtime = RuntimeDatabase(snapshot, state)
        try:
            summary = ZoneCoverageCatalog(runtime).summary()
            self.assertEqual(summary.zones, 3)
            self.assertEqual(summary.client_identity, 2)
            self.assertTrue(runtime.get_meta("zone_catalog_coverage", ""))
            with self.assertRaisesRegex(RuntimeError, "builder-only"):
                ZoneCoverageCatalog(runtime).compile_summary()
        finally:
            runtime.close()

        self.db = Database(self.root / "throwaway.sqlite3")


if __name__ == "__main__":
    unittest.main()
