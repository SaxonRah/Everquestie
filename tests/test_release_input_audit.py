from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.release_input_audit import audit_reviewed_release_inputs
from eqquest.runtime import RuntimeDatabase
from eqquest.travel_supplement import TRAVEL_SUPPLEMENT_SOURCE_KIND
from eqquest.zone_alias_supplement import (
    ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
    ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
)
from eqquest.zone_travel import ZoneTravelCatalog


class ReviewedReleaseInputAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.working = self.root / "working.sqlite3"
        self.snapshot = self.root / "everquestie-knowledge.sqlite3"
        self.state = self.root / "everquestie-user.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _set_counters(db: Database, *, aliases: int = 1, travel_edges: int = 1) -> None:
        db.set_meta("approved_zone_alias_supplement_count", "1")
        db.set_meta("approved_zone_alias_count", str(aliases))
        db.set_meta("approved_travel_supplement_count", "1")
        db.set_meta("approved_travel_supplement_edge_count", str(travel_edges))

    def _populate_matching_reviewed_evidence(self, db: Database) -> None:
        source_zone = db.upsert_entity(
            kind="zone",
            name="Audit Source Zone",
            external_id="9001",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )
        target_zone = db.upsert_entity(
            kind="zone",
            name="Audit Target Zone",
            external_id="9002",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )

        alias_source = db.upsert_source_page(
            url="https://example.invalid/reviewed-alias#audit-source",
            title="Reviewed zone alias: Old Audit Source -> Audit Source Zone",
            entity_type="zone_alias",
            sha256="audit-alias-sha",
            plain_text="Reviewed alias evidence.",
            raw_html="",
            source_name="Audit reviewed zone identity",
            source_kind=ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
            source_key="audit-source-alias",
            source_version="1",
        )
        db.add_alias(
            source_zone,
            "Old Audit Source",
            alias_type=ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
            source_page_id=alias_source,
        )

        ZoneTravelCatalog(db).add_provider_connection(
            source_zone,
            target_zone,
            connection_kind="portal",
            source_name="Audit reviewed travel",
            source_kind=TRAVEL_SUPPLEMENT_SOURCE_KIND,
            source_key="audit-source-to-target",
            source_version="1",
            evidence="Reviewed portal evidence.",
            data={
                "manifest_schema_version": 1,
                "manifest_source_key": "audit-source-to-target",
                "travel_requirements": [],
            },
        )
        self._set_counters(db)
        db.conn.commit()

    def test_matching_persisted_reviewed_evidence_matches_counters(self):
        db = Database(self.working)
        try:
            self._populate_matching_reviewed_evidence(db)
            audit = audit_reviewed_release_inputs(db)
            self.assertTrue(audit.recorded)
            self.assertTrue(audit.ok)
            self.assertEqual(audit.status, "ok")
            self.assertEqual(
                audit.actual,
                {
                    "zone_alias_supplements": 1,
                    "zone_aliases": 1,
                    "travel_supplements": 1,
                    "travel_edges": 1,
                },
            )
            self.assertEqual(audit.metadata["approved_travel_supplement_edge_count"], 1)
        finally:
            db.close()

    def test_missing_counters_remain_backward_compatible(self):
        db = Database(self.working)
        db.close()

        report = create_knowledge_snapshot(
            self.working,
            self.snapshot,
            snapshot_version="legacy-no-reviewed-counters",
        )
        reviewed = report.diagnostics["reviewed_release_inputs"]
        self.assertFalse(reviewed["recorded"])
        self.assertEqual(reviewed["status"], "not_recorded")
        self.assertEqual(reviewed["errors"], [])

    def test_stale_counter_blocks_snapshot_publication_atomically(self):
        db = Database(self.working)
        try:
            self._populate_matching_reviewed_evidence(db)
            db.set_meta("approved_travel_supplement_edge_count", "2")
            db.conn.commit()
        finally:
            db.close()

        with self.assertRaisesRegex(ValueError, "Reviewed release inputs are inconsistent"):
            create_knowledge_snapshot(
                self.working,
                self.snapshot,
                snapshot_version="stale-reviewed-counter",
            )
        self.assertFalse(self.snapshot.exists())

    def test_malformed_manifest_key_blocks_snapshot_even_when_counts_match(self):
        db = Database(self.working)
        try:
            self._populate_matching_reviewed_evidence(db)
            row = db.conn.execute(
                "SELECT id,data_json FROM zone_travel_edges WHERE source_kind=?",
                (TRAVEL_SUPPLEMENT_SOURCE_KIND,),
            ).fetchone()
            payload = json.loads(str(row["data_json"]))
            payload["manifest_source_key"] = "wrong-key"
            db.conn.execute(
                "UPDATE zone_travel_edges SET data_json=? WHERE id=?",
                (json.dumps(payload), int(row["id"])),
            )
            db.conn.commit()
        finally:
            db.close()

        with self.assertRaisesRegex(ValueError, "manifest_source_key"):
            create_knowledge_snapshot(
                self.working,
                self.snapshot,
                snapshot_version="malformed-reviewed-edge",
            )
        self.assertFalse(self.snapshot.exists())

    def test_runtime_audit_reads_immutable_knowledge_not_shadowing_user_meta(self):
        db = Database(self.working)
        try:
            self._populate_matching_reviewed_evidence(db)
        finally:
            db.close()
        create_knowledge_snapshot(
            self.working,
            self.snapshot,
            snapshot_version="runtime-reviewed-audit",
        )

        before = self.snapshot.read_bytes()
        runtime = RuntimeDatabase(self.snapshot, self.state, migrate_legacy=False)
        try:
            runtime.set_meta("approved_travel_supplement_edge_count", "999")
            self.assertEqual(runtime.get_meta("approved_travel_supplement_edge_count"), "999")

            audit = audit_reviewed_release_inputs(runtime)
            self.assertTrue(audit.recorded)
            self.assertTrue(audit.ok)
            self.assertEqual(audit.metadata["approved_travel_supplement_edge_count"], 1)
            self.assertEqual(audit.actual["travel_edges"], 1)
        finally:
            runtime.close()

        self.assertEqual(self.snapshot.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
