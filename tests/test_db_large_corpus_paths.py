from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import DATABASE_SCHEMA_VERSION, Database


class DatabaseLargeCorpusPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "working.sqlite3"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_preversioned_identity_tables_are_not_backfilled_again_on_reopen(self):
        db = Database(self.path)
        try:
            source_id = db.upsert_source_page(
                url="https://everquest.allakhazam.com/db/item.html?item=900001",
                title="Migration Token",
                entity_type="item",
                sha256="migration-token",
                plain_text="source text",
                raw_html="<html>source</html>",
                source_name="Allakhazam",
                source_kind="local_mirror",
                source_key="item/900001.html",
            )
            entity_id = db.upsert_entity(
                kind="item",
                name="Migration Token",
                source_page_id=source_id,
                source_url="https://everquest.allakhazam.com/db/item.html?item=900001",
                external_id="900001",
                external_namespace="allakhazam:item",
            )

            # Simulate upgrading a database created by the immediately preceding
            # unversioned schema. The identity tables already existed and had already
            # been backfilled by that build, but no migration marker was present.
            db.conn.execute(
                "DELETE FROM entity_sources WHERE entity_id=?",
                (entity_id,),
            )
            db.conn.execute(
                "DELETE FROM app_meta WHERE key='database_schema_version'"
            )
            db.conn.commit()
        finally:
            db.close()

        reopened = Database(self.path)
        try:
            self.assertEqual(
                reopened.get_meta("database_schema_version"),
                str(DATABASE_SCHEMA_VERSION),
            )
            # Reopening must not replay the old corpus-wide INSERT...SELECT backfill.
            self.assertIsNone(
                reopened.conn.execute(
                    "SELECT 1 FROM entity_sources WHERE entity_id=?",
                    (entity_id,),
                ).fetchone()
            )
        finally:
            reopened.close()

    def test_entity_metadata_does_not_materialize_source_page_bodies(self):
        db = Database(self.path)
        try:
            source_id = db.upsert_source_page(
                url="https://everquest.allakhazam.com/db/quest.html?quest=900002",
                title="Large Source Quest",
                entity_type="quest",
                sha256="large-source",
                plain_text="P" * 50000,
                raw_html="<html>" + ("R" * 50000) + "</html>",
                source_name="Allakhazam",
                source_kind="local_mirror",
                source_key="quest/900002.html",
            )
            entity_id = db.upsert_entity(
                kind="quest",
                name="Large Source Quest",
                source_page_id=source_id,
                source_url="https://everquest.allakhazam.com/db/quest.html?quest=900002",
                external_id="900002",
                external_namespace="allakhazam:quest",
            )

            entity = db.entity(entity_id)
            self.assertIsNotNone(entity)
            self.assertEqual(entity["name"], "Large Source Quest")
            self.assertIsNone(entity["source_text"])
            self.assertIsNone(entity["source_html"])

            excerpt = db.primary_source_text(entity_id, limit=1234)
            self.assertEqual(len(excerpt), 1234)
            self.assertEqual(excerpt, "P" * 1234)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
