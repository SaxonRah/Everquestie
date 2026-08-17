from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.travel_supplement import TRAVEL_SUPPLEMENT_SOURCE_KIND
from eqquest.zone_alias_supplement import (
    ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
    ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
)
from eqquest.zone_travel import ZoneTravelCatalog


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_TOOL = REPO_ROOT / "tools" / "audit_release_inputs.py"


class ReleaseInputAuditCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.working = self.root / "working.sqlite3"
        self.snapshot = self.root / "everquestie-knowledge.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def _populate_reviewed_release_inputs(self) -> None:
        db = Database(self.working)
        try:
            source_zone = db.upsert_entity(
                kind="zone",
                name="CLI Audit Source",
                external_id="9101",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            target_zone = db.upsert_entity(
                kind="zone",
                name="CLI Audit Target",
                external_id="9102",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            alias_source = db.upsert_source_page(
                url="https://example.invalid/release-input-cli#alias",
                title="Reviewed zone alias: Old CLI Source -> CLI Audit Source",
                entity_type="zone_alias",
                sha256="release-input-cli-alias",
                plain_text="Reviewed alias evidence.",
                raw_html="",
                source_name="CLI reviewed alias fixture",
                source_kind=ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
                source_key="old-cli-source",
                source_version="1",
            )
            db.add_alias(
                source_zone,
                "Old CLI Source",
                alias_type=ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
                source_page_id=alias_source,
            )
            ZoneTravelCatalog(db).add_provider_connection(
                source_zone,
                target_zone,
                connection_kind="portal",
                source_name="CLI reviewed travel fixture",
                source_kind=TRAVEL_SUPPLEMENT_SOURCE_KIND,
                source_key="cli-source-to-target",
                source_version="1",
                evidence="Reviewed portal evidence.",
                data={
                    "manifest_schema_version": 1,
                    "manifest_source_key": "cli-source-to-target",
                    "travel_requirements": [],
                },
            )
            db.set_meta("approved_zone_alias_supplement_count", "1")
            db.set_meta("approved_zone_alias_count", "1")
            db.set_meta("approved_travel_supplement_count", "1")
            db.set_meta("approved_travel_supplement_edge_count", "1")
            db.conn.commit()
        finally:
            db.close()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(AUDIT_TOOL), str(self.snapshot), *args],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_json_publish_gate_passes_finalized_snapshot_read_only(self):
        self._populate_reviewed_release_inputs()
        create_knowledge_snapshot(
            self.working,
            self.snapshot,
            snapshot_version="release-input-cli-valid",
        )
        before = self.snapshot.read_bytes()

        completed = self._run("--json", "--require-release-inputs")
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["publish_ready"])
        self.assertEqual(payload["actual"]["zone_aliases"], 1)
        self.assertEqual(payload["actual"]["travel_edges"], 1)
        self.assertEqual(self.snapshot.read_bytes(), before)

    def test_legacy_snapshot_is_diagnostic_but_not_publishable(self):
        db = Database(self.working)
        db.close()
        create_knowledge_snapshot(
            self.working,
            self.snapshot,
            snapshot_version="release-input-cli-legacy",
        )

        diagnostic = self._run("--json")
        self.assertEqual(diagnostic.returncode, 0, diagnostic.stderr or diagnostic.stdout)
        payload = json.loads(diagnostic.stdout)
        self.assertEqual(payload["status"], "not_recorded")
        self.assertFalse(payload["publish_ready"])

        publish = self._run("--require-release-inputs")
        self.assertEqual(publish.returncode, 2)
        self.assertIn("Publish-ready reviewed inputs: no", publish.stdout)
        self.assertIn("zone-alias", publish.stdout)
        self.assertIn("travel", publish.stdout)

    def test_tampered_finalized_counter_fails_without_further_mutation(self):
        self._populate_reviewed_release_inputs()
        create_knowledge_snapshot(
            self.working,
            self.snapshot,
            snapshot_version="release-input-cli-tampered",
        )
        conn = sqlite3.connect(self.snapshot)
        try:
            conn.execute(
                "UPDATE app_meta SET value='2' "
                "WHERE key='approved_travel_supplement_edge_count'"
            )
            conn.commit()
        finally:
            conn.close()
        before_audit = self.snapshot.read_bytes()

        completed = self._run("--json", "--require-release-inputs")
        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertFalse(payload["publish_ready"])
        self.assertTrue(
            any(
                "approved_travel_supplement_edge_count records 2" in error
                for error in payload["errors"]
            )
        )
        self.assertEqual(self.snapshot.read_bytes(), before_audit)


if __name__ == "__main__":
    unittest.main()
