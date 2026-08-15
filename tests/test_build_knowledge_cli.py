from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.zone_travel import ZoneTravelCatalog
from tools.build_knowledge_db import (
    audit_snapshot_routes,
    build_invocations,
    parser,
    write_route_report,
)


class BuildKnowledgeCliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def _base_args(self) -> list[str]:
        return [
            "--working-db",
            str(self.root / "working.sqlite3"),
            "--snapshot-db",
            str(self.root / "snapshot.sqlite3"),
            "--version",
            "test-version",
        ]

    def test_allakhazam_mirror_is_a_first_class_cli_provider(self):
        mirror = self.root / "mirror"
        args = parser().parse_args(
            self._base_args()
            + [
                "--allakhazam-mirror",
                str(mirror),
                "--allakhazam-version",
                "capture-2026-08-15",
            ]
        )
        invocations = build_invocations(args)
        self.assertEqual(len(invocations), 1)
        invocation = invocations[0]
        self.assertEqual(invocation.provider, "allakhazam-mirror")
        self.assertEqual(invocation.config["path"], str(mirror))
        self.assertEqual(invocation.config["source_version"], "capture-2026-08-15")

    def test_allakhazam_version_without_mirror_is_rejected(self):
        args = parser().parse_args(
            self._base_args() + ["--allakhazam-version", "capture-only"]
        )
        with self.assertRaisesRegex(ValueError, "requires --allakhazam-mirror"):
            build_invocations(args)

    def test_route_audit_reads_existing_graph_without_mutating_database(self):
        path = self.root / "knowledge.sqlite3"
        db = Database(path)
        try:
            source = db.upsert_entity(
                kind="zone",
                name="Alpha",
                external_id="9001",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            target = db.upsert_entity(
                kind="zone",
                name="Beta",
                external_id="9002",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            ZoneTravelCatalog(db).add_provider_connection(
                source,
                target,
                bidirectional=True,
                source_name="test-provider",
                source_key="alpha-beta",
                evidence="test reciprocal transition",
            )
        finally:
            db.close()

        before = path.read_bytes()
        wal = Path(str(path) + "-wal")
        shm = Path(str(path) + "-shm")
        wal_before = wal.read_bytes() if wal.exists() else None
        shm_before = shm.read_bytes() if shm.exists() else None

        summary = audit_snapshot_routes(path, (("Alpha", "Beta"), ("Beta", "Alpha")))
        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.accepted, 2)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(wal.read_bytes() if wal.exists() else None, wal_before)
        self.assertEqual(shm.read_bytes() if shm.exists() else None, shm_before)

    def test_route_report_is_machine_readable(self):
        path = self.root / "knowledge.sqlite3"
        db = Database(path)
        try:
            source = db.upsert_entity(
                kind="zone",
                name="Alpha",
                external_id="9101",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            target = db.upsert_entity(
                kind="zone",
                name="Beta",
                external_id="9102",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            ZoneTravelCatalog(db).add_provider_connection(
                source,
                target,
                source_name="test-provider",
                source_key="alpha-beta",
            )
        finally:
            db.close()

        summary = audit_snapshot_routes(path, (("Alpha", "Beta"),))
        output = write_route_report(self.root / "reports" / "routes.json", summary)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["accepted"], 1)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["results"][0]["status"], "reachable")


if __name__ == "__main__":
    unittest.main()
