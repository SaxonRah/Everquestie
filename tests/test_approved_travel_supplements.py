from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.approved_travel_supplements import (
    approved_travel_manifest_paths,
    build_and_finalize_with_approved_travel_supplements,
    stage_builder_with_approved_travel_supplements,
)
from eqquest.knowledge_build import (
    KnowledgeProviderRegistry,
    ProviderBuildResult,
    ProviderInvocation,
    build_working_knowledge_db,
)


class ApprovedTravelSupplementBuildTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.working = self.root / "working.sqlite3"
        self.staged = self.root / "release-working.sqlite3"
        self.snapshot = self.root / "knowledge.sqlite3"
        self.supplements = self.root / "travel-supplements"
        self.supplements.mkdir()

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _zone_fixture_provider(context, _config):
        context.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )
        context.db.upsert_entity(
            kind="zone",
            name="West Freeport",
            external_id="9",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )
        return ProviderBuildResult(
            provider="zone-fixture",
            label="canonical zone fixture",
            counts={"zones": 2},
        )

    def _registry(self) -> KnowledgeProviderRegistry:
        registry = KnowledgeProviderRegistry()
        registry.register("zone-fixture", self._zone_fixture_provider)
        return registry

    def _write_manifest(self, name: str = "portal.json") -> Path:
        path = self.supplements / name
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_name": "Approved portal fixture",
                    "source_version": "test-1",
                    "source_url": "https://example.invalid/portal",
                    "edges": [
                        {
                            "source_key": "pok-west-freeport-test",
                            "source": "The Plane of Knowledge",
                            "target": "West Freeport",
                            "connection_kind": "portal",
                            "bidirectional": True,
                            "evidence": "Test fixture explicitly supports both directions.",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_manifest_discovery_is_sorted_and_requires_json(self):
        self._write_manifest("z-last.json")
        self._write_manifest("A-first.JSON")
        (self.supplements / "notes.txt").write_text("ignored", encoding="utf-8")

        manifests = approved_travel_manifest_paths(self.supplements)
        self.assertEqual(
            [path.name for path in manifests],
            ["A-first.JSON", "z-last.json"],
        )

    def test_empty_approved_directory_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "contains no JSON manifests"):
            approved_travel_manifest_paths(self.supplements)

    def test_release_staging_clones_then_compiles_without_mutating_source(self):
        self._write_manifest()
        build_working_knowledge_db(
            self.working,
            [ProviderInvocation("zone-fixture")],
            registry=self._registry(),
        )

        progress: list[str] = []
        results = stage_builder_with_approved_travel_supplements(
            self.working,
            self.staged,
            self.supplements,
            progress=progress.append,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].edges, 1)
        self.assertTrue(any("[release-stage] cloning builder DB" in line for line in progress))
        self.assertTrue(any("[travel-supplement] portal.json" in line for line in progress))
        self.assertTrue(any("[release-stage] ready" in line for line in progress))

        source = sqlite3.connect(self.working)
        source.row_factory = sqlite3.Row
        try:
            source_rows = source.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='zone_travel_edges'"
            ).fetchone()[0]
            if source_rows:
                curated = source.execute(
                    "SELECT COUNT(*) FROM zone_travel_edges WHERE source_kind='curated_travel_manifest'"
                ).fetchone()[0]
                self.assertEqual(curated, 0)
            source_meta = dict(source.execute("SELECT key,value FROM app_meta").fetchall())
            self.assertNotIn("approved_travel_supplement_count", source_meta)
        finally:
            source.close()

        staged = sqlite3.connect(self.staged)
        staged.row_factory = sqlite3.Row
        try:
            row = staged.execute(
                """
                SELECT source_name,source_key,bidirectional,status
                FROM zone_travel_edges
                WHERE source_kind='curated_travel_manifest'
                """
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["source_name"], "Approved portal fixture")
            self.assertEqual(row["source_key"], "pok-west-freeport-test")
            self.assertEqual(int(row["bidirectional"]), 1)
            self.assertEqual(row["status"], "linked")
            meta = dict(staged.execute("SELECT key,value FROM app_meta").fetchall())
            self.assertEqual(meta["approved_travel_supplement_count"], "1")
            self.assertEqual(meta["approved_travel_supplement_edge_count"], "1")
        finally:
            staged.close()

    def test_release_build_compiles_supplements_before_finalization(self):
        self._write_manifest()
        progress: list[str] = []

        report = build_and_finalize_with_approved_travel_supplements(
            self.working,
            self.snapshot,
            [ProviderInvocation("zone-fixture")],
            snapshot_version="approved-travel-test",
            supplement_dir=self.supplements,
            registry=self._registry(),
            progress=progress.append,
        )

        self.assertIsNotNone(report.snapshot)
        self.assertTrue(any("[travel-supplement] portal.json" in line for line in progress))
        self.assertTrue(any("compiled portal.json" in line for line in progress))

        working = sqlite3.connect(self.working)
        working.row_factory = sqlite3.Row
        try:
            meta = dict(working.execute("SELECT key,value FROM app_meta").fetchall())
            self.assertEqual(meta["approved_travel_supplement_count"], "1")
            self.assertEqual(meta["approved_travel_supplement_edge_count"], "1")
            row = working.execute(
                """
                SELECT source_kind,source_name,source_key,bidirectional,status
                FROM zone_travel_edges
                WHERE source_kind='curated_travel_manifest'
                """
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["source_name"], "Approved portal fixture")
            self.assertEqual(row["source_key"], "pok-west-freeport-test")
            self.assertEqual(int(row["bidirectional"]), 1)
            self.assertEqual(row["status"], "linked")
        finally:
            working.close()

        snapshot = sqlite3.connect(self.snapshot)
        snapshot.row_factory = sqlite3.Row
        try:
            row = snapshot.execute(
                """
                SELECT zte.bidirectional,zte.source_kind,se.name AS source_name,
                       te.name AS target_name
                FROM zone_travel_edges zte
                JOIN entities se ON se.id=zte.source_zone_entity_id
                JOIN entities te ON te.id=zte.target_zone_entity_id
                WHERE zte.source_kind='curated_travel_manifest'
                """
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["source_name"], "The Plane of Knowledge")
            self.assertEqual(row["target_name"], "West Freeport")
            self.assertEqual(int(row["bidirectional"]), 1)
        finally:
            snapshot.close()


if __name__ == "__main__":
    unittest.main()
