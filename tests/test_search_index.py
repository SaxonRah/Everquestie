from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.search_index import rebuild_compact_search_index


class CompactSearchIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "knowledge.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _entity(self, name: str) -> int:
        return self.db.upsert_entity(kind="spell", name=name, external_id=name)

    def test_database_owns_the_compact_rebuild_policy_natively(self) -> None:
        self.assertEqual("eqquest.db", Database.rebuild_search_index.__module__)
        self.assertEqual("rebuild_search_index", Database.rebuild_search_index.__name__)
        self.assertIsNot(Database.rebuild_search_index, rebuild_compact_search_index)

    def test_rich_json_is_retained_but_not_duplicated_into_fts(self) -> None:
        entity_id = self._entity("Projected Spell")
        payload = {
            "name": "Projected Spell",
            "mana": 100,
            "jsonOnlySecretToken": "should-not-be-in-fts",
        }
        self.db.upsert_entity_detail(
            entity_id,
            detail_format="mcp-json",
            detail_text="mana: 100 searchable-projection-token",
            detail_json=payload,
        )

        self.assertEqual(1, self.db.rebuild_search_index())

        detail = self.db.entity_detail(entity_id)
        self.assertEqual(payload, json.loads(detail["detail_json"]))
        fts = self.db.conn.execute(
            "SELECT body FROM entity_fts WHERE entity_id=?", (entity_id,)
        ).fetchone()
        self.assertIn("searchable-projection-token", fts["body"])
        self.assertNotIn("should-not-be-in-fts", fts["body"])

        hits = self.db.search_entities_fts("searchable projection token")
        self.assertEqual([entity_id], [int(row["id"]) for row in hits])

    def test_legacy_detail_without_text_falls_back_to_json(self) -> None:
        entity_id = self._entity("Legacy Detail")
        self.db.upsert_entity_detail(
            entity_id,
            detail_format="json",
            detail_text="",
            detail_json={"legacySearchToken": "legacy-fallback-visible"},
        )

        rebuild_compact_search_index(self.db)
        fts = self.db.conn.execute(
            "SELECT body FROM entity_fts WHERE entity_id=?", (entity_id,)
        ).fetchone()
        self.assertIn("legacy-fallback-visible", fts["body"])


if __name__ == "__main__":
    unittest.main()
