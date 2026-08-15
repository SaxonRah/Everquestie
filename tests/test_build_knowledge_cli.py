from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.provider_zone_travel import ProviderZoneTravelCatalog
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog
from eqquest.zone_travel import ZoneTravelCatalog
from tools.build_knowledge_db import (
    audit_snapshot_provider_travel_frontier,
    audit_snapshot_routes,
    build_invocations,
    parser,
    route_failure_frontier_zones,
    validate_audit_options,
    write_provider_travel_frontier_report,
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

    def test_audit_report_paths_cannot_overwrite_database_outputs_or_each_other(self):
        working = self.root / "working.sqlite3"
        snapshot = self.root / "snapshot.sqlite3"
        shared_report = self.root / "report.json"

        args = parser().parse_args(
            self._base_args() + ["--route-report", str(snapshot)]
        )
        with self.assertRaisesRegex(ValueError, "must not overwrite --snapshot-db"):
            validate_audit_options(args)

        args = parser().parse_args(
            self._base_args()
            + ["--provider-travel-frontier-report", str(working)]
        )
        with self.assertRaisesRegex(ValueError, "must not overwrite --working-db"):
            validate_audit_options(args)

        args = parser().parse_args(
            self._base_args()
            + [
                "--route-report",
                str(shared_report),
                "--provider-travel-frontier-report",
                str(shared_report),
            ]
        )
        with self.assertRaisesRegex(ValueError, "must use different paths"):
            validate_audit_options(args)

        args = parser().parse_args(
            self._base_args()
            + [
                "--skip-route-audit",
                "--provider-travel-frontier-report",
                str(self.root / "frontier.json"),
            ]
        )
        with self.assertRaisesRegex(ValueError, "cannot be used with --skip-route-audit"):
            validate_audit_options(args)

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

    def test_route_failure_frontier_zones_include_only_failed_topology_endpoints(self):
        path = self.root / "frontier-targets.sqlite3"
        db = Database(path)
        try:
            alpha = db.upsert_entity(
                kind="zone",
                name="Alpha",
                external_id="9201",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            db.upsert_entity(
                kind="zone",
                name="Beta",
                external_id="9202",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            gamma = db.upsert_entity(
                kind="zone",
                name="Gamma",
                external_id="9203",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            ZoneTravelCatalog(db).add_provider_connection(
                alpha,
                gamma,
                source_name="test-provider",
                source_key="alpha-gamma",
            )
        finally:
            db.close()

        summary = audit_snapshot_routes(
            path,
            (("Alpha", "Beta"), ("Alpha", "Gamma"), ("Missing Zone", "Gamma")),
        )
        self.assertEqual(summary.status_counts, (("disconnected", 1), ("reachable", 1), ("source_unresolved", 1)))
        self.assertEqual(route_failure_frontier_zones(summary), ("Alpha", "Beta"))

    def test_provider_frontier_report_is_machine_readable_and_read_only(self):
        path = self.root / "provider-frontier.sqlite3"
        db = Database(path)
        try:
            alpha = db.upsert_entity(
                kind="zone",
                name="Alpha",
                external_id="9301",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            beta = db.upsert_entity(
                kind="zone",
                name="Beta",
                external_id="9302",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            alpha_page = db.upsert_source_page(
                url="https://everquest.allakhazam.com/db/zone.html?zstrat=alpha",
                title="Alpha :: EverQuest",
                entity_type="zone",
                sha256="alpha-sha",
                plain_text="Connected Zones",
                raw_html="",
                source_name="Allakhazam",
                source_kind="local_mirror",
                source_key="zone:alpha",
                source_version="test-capture",
            )
            beta_page = db.upsert_source_page(
                url="https://everquest.allakhazam.com/db/zone.html?zstrat=beta",
                title="Beta :: EverQuest",
                entity_type="zone",
                sha256="beta-sha",
                plain_text="Connected Zones",
                raw_html="",
                source_name="Allakhazam",
                source_kind="local_mirror",
                source_key="zone:beta",
                source_version="test-capture",
            )
            provider_alpha = db.upsert_entity(
                kind="zone",
                name="Alpha",
                external_id="zone:alpha",
                external_namespace="allakhazam:zone",
                source_page_id=alpha_page,
                merge_by_name=False,
            )
            provider_beta = db.upsert_entity(
                kind="zone",
                name="Beta",
                external_id="zone:beta",
                external_namespace="allakhazam:zone",
                source_page_id=beta_page,
                merge_by_name=False,
            )
            db.upsert_relationship(
                provider_alpha,
                provider_beta,
                "connected_to",
                source_page_id=alpha_page,
                evidence="Beta / Both",
                data={"confidence": "structured", "direction": "Both"},
            )
            stats = ProviderZoneReconciliationCatalog(db).reconcile()
            self.assertEqual(stats.linked, 2)
            travel = ProviderZoneTravelCatalog(db).reconcile()
            self.assertEqual(travel.linked, 1)
            self.assertNotEqual(alpha, provider_alpha)
            self.assertNotEqual(beta, provider_beta)
        finally:
            db.close()

        before = path.read_bytes()
        wal = Path(str(path) + "-wal")
        shm = Path(str(path) + "-shm")
        wal_before = wal.read_bytes() if wal.exists() else None
        shm_before = shm.read_bytes() if shm.exists() else None

        summary = audit_snapshot_provider_travel_frontier(path, ("Beta",))
        self.assertEqual(len(summary.zones), 1)
        self.assertEqual(summary.zones[0].classification, "compiled")
        output = write_provider_travel_frontier_report(
            self.root / "reports" / "provider-frontier.json",
            summary,
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["status_counts"], {"compiled": 1})
        self.assertEqual(payload["zones"][0]["canonical_zone_name"], "Beta")
        self.assertEqual(payload["zones"][0]["relationships"][0]["classification"], "compiled")
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