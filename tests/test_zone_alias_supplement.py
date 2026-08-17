from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.zone_alias_supplement import (
    ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
    ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
    ZoneAliasSupplementImporter,
)
from eqquest.zone_identity import ZoneIdentityIndex


class ZoneAliasSupplementTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.hole = self.db.upsert_entity(
            kind="zone",
            name="The Hole",
            external_id="39",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )
        self.paineel = self.db.upsert_entity(
            kind="zone",
            name="Paineel",
            external_id="75",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _manifest(
        self,
        *,
        source_name: str = "Reviewed zone identity fixture",
        canonical_name: str = "The Hole",
        eq_zone_id: str = "39",
        alias: str = "The Ruins of Old Paineel",
        source_key: str = "old-paineel",
    ) -> Path:
        path = self.root / f"{source_key}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_name": source_name,
                    "source_version": "test-1",
                    "aliases": [
                        {
                            "source_key": source_key,
                            "canonical_name": canonical_name,
                            "eq_zone_id": eq_zone_id,
                            "alias": alias,
                            "source_urls": [
                                "https://www.everquest.com/news/imported-eq-enus-50994",
                                "https://www.everquest.com/news/eq-vaniki-server-faq",
                            ],
                            "evidence": "Reviewed fixture identity evidence.",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_exact_client_identity_gets_source_backed_alias(self):
        result = ZoneAliasSupplementImporter(self.db).import_manifest(self._manifest())
        self.assertEqual(result.aliases, 1)

        resolution = ZoneIdentityIndex(self.db).resolve("The Ruins of Old Paineel")
        self.assertEqual(resolution.status, "linked")
        self.assertEqual(resolution.match_kind, "alias")
        self.assertEqual(resolution.entity_id, self.hole)

        row = self.db.conn.execute(
            """
            SELECT ea.alias,ea.alias_type,sp.source_name,sp.source_kind,sp.source_key,
                   sp.source_version,sp.plain_text,es.role,es.confidence
            FROM entity_aliases ea
            JOIN source_pages sp ON sp.id=ea.source_page_id
            LEFT JOIN entity_sources es
              ON es.entity_id=ea.entity_id AND es.source_page_id=sp.id
            WHERE ea.entity_id=? AND ea.normalized_alias=?
            """,
            (self.hole, "the ruins of old paineel"),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["alias"], "The Ruins of Old Paineel")
        self.assertEqual(row["alias_type"], ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE)
        self.assertEqual(row["source_kind"], ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND)
        self.assertEqual(row["source_key"], "old-paineel")
        self.assertEqual(row["role"], "identity_alias")
        self.assertEqual(float(row["confidence"]), 1.0)
        self.assertIn("Supporting source:", row["plain_text"])

    def test_exact_client_id_name_mismatch_is_atomic(self):
        importer = ZoneAliasSupplementImporter(self.db)
        importer.import_manifest(self._manifest())
        before = self.db.conn.execute(
            "SELECT COUNT(*) FROM entity_aliases WHERE alias_type=?",
            (ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,),
        ).fetchone()[0]

        bad = self._manifest(canonical_name="Paineel", eq_zone_id="39")
        with self.assertRaisesRegex(ValueError, "does not match eqclient zone ID"):
            importer.import_manifest(bad)

        after = self.db.conn.execute(
            "SELECT COUNT(*) FROM entity_aliases WHERE alias_type=?",
            (ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,),
        ).fetchone()[0]
        self.assertEqual(after, before)
        self.assertEqual(
            ZoneIdentityIndex(self.db).resolve("The Ruins of Old Paineel").entity_id,
            self.hole,
        )

    def test_alias_collision_with_other_canonical_zone_fails_closed(self):
        self.db.upsert_entity(
            kind="zone",
            name="The Ruins of Old Paineel",
            external_id="9999",
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )
        with self.assertRaisesRegex(ValueError, "already resolves to a different canonical zone"):
            ZoneAliasSupplementImporter(self.db).import_manifest(self._manifest())
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM source_pages WHERE source_kind=?",
                (ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,),
            ).fetchone()[0],
            0,
        )

    def test_reimport_replaces_only_same_reviewed_source(self):
        importer = ZoneAliasSupplementImporter(self.db)
        importer.import_manifest(self._manifest(alias="The Ruins of Old Paineel"))
        other_page = self.db.upsert_source_page(
            url="https://example.invalid/unrelated",
            title="unrelated alias source",
            entity_type="zone_alias",
            sha256="unrelated",
            plain_text="unrelated",
            raw_html="",
            source_name="Another source",
            source_kind=ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
            source_key="other",
            source_version="1",
        )
        self.db.add_alias(
            self.paineel,
            "Heretic City",
            alias_type=ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
            source_page_id=other_page,
        )

        importer.import_manifest(
            self._manifest(alias="Old Paineel Ruins", source_key="replacement")
        )
        index = ZoneIdentityIndex(self.db)
        self.assertEqual(index.resolve("The Ruins of Old Paineel").status, "unresolved")
        self.assertEqual(index.resolve("Old Paineel Ruins").entity_id, self.hole)
        self.assertEqual(index.resolve("Heretic City").entity_id, self.paineel)

    def test_finalized_snapshot_role_is_rejected(self):
        self.db.set_meta("database_role", "knowledge_snapshot")
        with self.assertRaisesRegex(RuntimeError, "refuses finalized knowledge snapshots"):
            ZoneAliasSupplementImporter(self.db)


if __name__ == "__main__":
    unittest.main()
