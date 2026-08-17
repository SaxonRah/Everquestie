from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.approved_travel_supplements import (
    stage_builder_with_approved_travel_supplements,
)
from eqquest.db import Database
from eqquest.zone_alias_supplement import (
    ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
    ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
)


class ReleaseZoneAliasStagingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.source = self.root / "working.sqlite3"
        self.staged = self.root / "release-working.sqlite3"
        self.alias_dir = self.root / "zone-aliases"
        self.travel_dir = self.root / "travel-supplements"
        self.alias_dir.mkdir()
        self.travel_dir.mkdir()

        db = Database(self.source)
        try:
            db.upsert_entity(
                kind="zone",
                name="The Hole",
                external_id="39",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
            db.upsert_entity(
                kind="zone",
                name="Paineel",
                external_id="75",
                external_namespace="eqclient:zone",
                merge_by_name=False,
            )
        finally:
            db.close()

        (self.alias_dir / "old-paineel.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_name": "Release alias fixture",
                    "source_version": "test-1",
                    "aliases": [
                        {
                            "source_key": "old-paineel",
                            "canonical_name": "The Hole",
                            "eq_zone_id": "39",
                            "alias": "The Ruins of Old Paineel",
                            "source_url": "https://example.invalid/old-paineel",
                            "evidence": "Synthetic reviewed identity fixture.",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        # The travel source is intentionally named only by the reviewed alias. If
        # staging compiles travel before identity aliases, this manifest must fail.
        (self.travel_dir / "alias-dependent.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_name": "Alias-dependent travel fixture",
                    "source_version": "test-1",
                    "source_url": "https://example.invalid/travel",
                    "edges": [
                        {
                            "source_key": "old-paineel-to-paineel",
                            "source": "The Ruins of Old Paineel",
                            "target": "Paineel",
                            "connection_kind": "zone_line",
                            "bidirectional": False,
                            "evidence": "Synthetic ordering fixture.",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_stage_is_atomic_and_compiles_reviewed_identity_before_travel(self):
        progress: list[str] = []
        results = stage_builder_with_approved_travel_supplements(
            self.source,
            self.staged,
            self.travel_dir,
            zone_alias_dir=self.alias_dir,
            progress=progress.append,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].edges, 1)
        self.assertLess(
            next(i for i, line in enumerate(progress) if "[zone-alias] old-paineel.json" in line),
            next(i for i, line in enumerate(progress) if "[travel-supplement] alias-dependent.json" in line),
        )

        source = sqlite3.connect(self.source)
        source.row_factory = sqlite3.Row
        try:
            self.assertEqual(
                source.execute(
                    "SELECT COUNT(*) FROM source_pages WHERE source_kind=?",
                    (ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                source.execute(
                    "SELECT COUNT(*) FROM entity_aliases WHERE alias_type=?",
                    (ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,),
                ).fetchone()[0],
                0,
            )
            self.assertNotIn(
                "approved_zone_alias_count",
                dict(source.execute("SELECT key,value FROM app_meta").fetchall()),
            )
        finally:
            source.close()

        staged = sqlite3.connect(self.staged)
        staged.row_factory = sqlite3.Row
        try:
            alias = staged.execute(
                """
                SELECT ea.entity_id,ea.alias,ea.alias_type,sp.source_kind
                FROM entity_aliases ea
                JOIN source_pages sp ON sp.id=ea.source_page_id
                WHERE ea.normalized_alias='the ruins of old paineel'
                """
            ).fetchone()
            self.assertIsNotNone(alias)
            self.assertEqual(alias["alias_type"], ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE)
            self.assertEqual(alias["source_kind"], ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND)

            edge = staged.execute(
                """
                SELECT zte.source_zone_entity_id,zte.target_zone_entity_id,
                       se.name AS source_name,te.name AS target_name
                FROM zone_travel_edges zte
                JOIN entities se ON se.id=zte.source_zone_entity_id
                JOIN entities te ON te.id=zte.target_zone_entity_id
                WHERE zte.source_kind='curated_travel_manifest'
                """
            ).fetchone()
            self.assertIsNotNone(edge)
            self.assertEqual(edge["source_name"], "The Hole")
            self.assertEqual(edge["target_name"], "Paineel")

            meta = dict(staged.execute("SELECT key,value FROM app_meta").fetchall())
            self.assertEqual(meta["approved_zone_alias_supplement_count"], "1")
            self.assertEqual(meta["approved_zone_alias_count"], "1")
            self.assertEqual(meta["approved_travel_supplement_count"], "1")
            self.assertEqual(meta["approved_travel_supplement_edge_count"], "1")
        finally:
            staged.close()


if __name__ == "__main__":
    unittest.main()
