from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.travel_requirements import travel_requirements_for_hop
from eqquest.travel_supplement import (
    TRAVEL_SUPPLEMENT_SOURCE_KIND,
    TravelSupplementImporter,
)
from eqquest.zone_travel import ZoneTravelCatalog


class TravelSupplementTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "working.sqlite3"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, number: int) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=str(number),
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )

    def _manifest(self, payload: dict) -> Path:
        path = self.root / "travel-supplement.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def test_compiles_canonical_directed_edge_with_provenance_and_requirement(self):
        alpha = self._zone("Alpha", 1001)
        beta = self._zone("Beta", 1002)
        manifest = self._manifest(
            {
                "schema_version": 1,
                "source_name": "Curated EQ travel",
                "source_version": "test-v1",
                "source_url": "https://example.invalid/travel",
                "edges": [
                    {
                        "source_key": "alpha-to-beta",
                        "source": "Alpha",
                        "target": "Beta",
                        "connection_kind": "portal",
                        "evidence": "Explicit source describes travel from Alpha to Beta.",
                        "travel_requirements": [
                            {
                                "kind": "minimum_level",
                                "minimum_level": 10,
                                "text": "Minimum level 10",
                                "direction": "forward",
                            }
                        ],
                    }
                ],
            }
        )

        stats = TravelSupplementImporter(self.db).import_manifest(manifest)
        self.assertEqual(stats.edges, 1)
        self.assertEqual(stats.bidirectional_edges, 0)
        self.assertEqual(stats.requirements, 1)

        catalog = ZoneTravelCatalog(self.db)
        self.assertEqual(catalog.shortest_path(alpha, beta), [alpha, beta])
        self.assertEqual(catalog.shortest_path(beta, alpha), [])

        row = self.db.conn.execute(
            """
            SELECT source_name,source_kind,source_key,source_version,evidence,data_json
            FROM zone_travel_edges
            WHERE source_kind=?
            """,
            (TRAVEL_SUPPLEMENT_SOURCE_KIND,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["source_name"], "Curated EQ travel")
        self.assertEqual(row["source_key"], "alpha-to-beta")
        self.assertEqual(row["source_version"], "test-v1")
        self.assertIn("Explicit source describes travel", row["evidence"])
        data = json.loads(row["data_json"])
        self.assertEqual(data["source_url"], "https://example.invalid/travel")
        self.assertEqual(data["manifest_schema_version"], 1)

        requirements = travel_requirements_for_hop(self.db, alpha, beta)
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0].text, "Minimum level 10")
        self.assertEqual(requirements[0].minimum_level, 10)

    def test_bidirectional_is_explicit_not_inferred(self):
        alpha = self._zone("Alpha", 1001)
        beta = self._zone("Beta", 1002)
        manifest = self._manifest(
            {
                "source_name": "Curated EQ travel",
                "source_version": "test-v1",
                "edges": [
                    {
                        "source_key": "alpha-beta",
                        "source": "Alpha",
                        "target": "Beta",
                        "bidirectional": True,
                        "evidence": "Source explicitly states travel works both ways.",
                    }
                ],
            }
        )

        stats = TravelSupplementImporter(self.db).import_manifest(manifest)
        self.assertEqual(stats.bidirectional_edges, 1)
        catalog = ZoneTravelCatalog(self.db)
        self.assertEqual(catalog.shortest_path(alpha, beta), [alpha, beta])
        self.assertEqual(catalog.shortest_path(beta, alpha), [beta, alpha])

    def test_reimport_replaces_only_same_supplement_source(self):
        alpha = self._zone("Alpha", 1001)
        beta = self._zone("Beta", 1002)
        gamma = self._zone("Gamma", 1003)
        importer = TravelSupplementImporter(self.db)

        first = self._manifest(
            {
                "source_name": "Curated EQ travel",
                "source_version": "test-v1",
                "edges": [
                    {
                        "source_key": "alpha-beta",
                        "source": "Alpha",
                        "target": "Beta",
                        "evidence": "First version.",
                    }
                ],
            }
        )
        importer.import_manifest(first)

        other = ZoneTravelCatalog(self.db)
        other.add_provider_connection(
            alpha,
            gamma,
            source_name="Independent provider",
            source_kind="provider",
            source_key="alpha-gamma",
            evidence="Independent evidence.",
        )

        second = self._manifest(
            {
                "source_name": "Curated EQ travel",
                "source_version": "test-v2",
                "edges": [
                    {
                        "source_key": "beta-gamma",
                        "source": "Beta",
                        "target": "Gamma",
                        "evidence": "Second version.",
                    }
                ],
            }
        )
        importer.import_manifest(second)

        supplement_rows = self.db.conn.execute(
            """
            SELECT source_key,source_version
            FROM zone_travel_edges
            WHERE source_kind=? AND source_name='Curated EQ travel'
            ORDER BY source_key
            """,
            (TRAVEL_SUPPLEMENT_SOURCE_KIND,),
        ).fetchall()
        self.assertEqual(
            [(row["source_key"], row["source_version"]) for row in supplement_rows],
            [("beta-gamma", "test-v2")],
        )
        independent = self.db.conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM zone_travel_edges
            WHERE source_kind='provider' AND source_name='Independent provider'
            """
        ).fetchone()
        self.assertEqual(int(independent["n"]), 1)

    def test_invalid_manifest_is_validated_before_existing_rows_are_replaced(self):
        alpha = self._zone("Alpha", 1001)
        beta = self._zone("Beta", 1002)
        importer = TravelSupplementImporter(self.db)

        good = self._manifest(
            {
                "source_name": "Curated EQ travel",
                "source_version": "test-v1",
                "edges": [
                    {
                        "source_key": "alpha-beta",
                        "source": "Alpha",
                        "target": "Beta",
                        "evidence": "Known-good evidence.",
                    }
                ],
            }
        )
        importer.import_manifest(good)

        bad = self._manifest(
            {
                "source_name": "Curated EQ travel",
                "source_version": "test-v2",
                "edges": [
                    {
                        "source_key": "alpha-missing",
                        "source": "Alpha",
                        "target": "Missing Zone",
                        "evidence": "Bad endpoint should fail.",
                    }
                ],
            }
        )
        with self.assertRaisesRegex(ValueError, "no authoritative canonical zone identity"):
            importer.import_manifest(bad)

        rows = self.db.conn.execute(
            """
            SELECT source_key,source_version
            FROM zone_travel_edges
            WHERE source_kind=? AND source_name='Curated EQ travel'
            """,
            (TRAVEL_SUPPLEMENT_SOURCE_KIND,),
        ).fetchall()
        self.assertEqual(
            [(row["source_key"], row["source_version"]) for row in rows],
            [("alpha-beta", "test-v1")],
        )
        self.assertEqual(ZoneTravelCatalog(self.db).shortest_path(alpha, beta), [alpha, beta])

    def test_missing_evidence_and_duplicate_keys_are_rejected(self):
        self._zone("Alpha", 1001)
        self._zone("Beta", 1002)
        importer = TravelSupplementImporter(self.db)

        missing_evidence = self._manifest(
            {
                "source_name": "Curated EQ travel",
                "source_version": "test-v1",
                "edges": [
                    {
                        "source_key": "alpha-beta",
                        "source": "Alpha",
                        "target": "Beta",
                    }
                ],
            }
        )
        with self.assertRaisesRegex(ValueError, "requires explicit evidence"):
            importer.import_manifest(missing_evidence)

        duplicate = self._manifest(
            {
                "source_name": "Curated EQ travel",
                "source_version": "test-v1",
                "edges": [
                    {
                        "source_key": "same-key",
                        "source": "Alpha",
                        "target": "Beta",
                        "evidence": "First.",
                    },
                    {
                        "source_key": "same-key",
                        "source": "Beta",
                        "target": "Alpha",
                        "evidence": "Second.",
                    },
                ],
            }
        )
        with self.assertRaisesRegex(ValueError, "duplicate travel supplement source_key"):
            importer.import_manifest(duplicate)

    def test_read_only_runtime_adapter_is_rejected(self):
        runtime_like = type(
            "RuntimeLike",
            (),
            {"knowledge_writable": False},
        )()
        with self.assertRaisesRegex(RuntimeError, "builder-only"):
            TravelSupplementImporter(runtime_like)


if __name__ == "__main__":
    unittest.main()
