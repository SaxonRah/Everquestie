from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.loot_relevance import recent_loot_relevance


class LootRelevanceIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
        self.source = self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/quest.html?quest=identity",
            title="Identity Quest",
            entity_type="quest",
            sha256="sha-identity",
            plain_text="structured quest source",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key="quest:identity",
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tempdir.cleanup()

    def _quest_use(self, item_id: int, suffix: str = "1") -> int:
        quest_id = self.db.upsert_entity(
            kind="quest",
            name=f"Token Quest {suffix}",
            external_id=f"quest:{suffix}",
            source_page_id=self.source,
        )
        self.db.upsert_relationship(
            quest_id,
            int(item_id),
            "objective_turn_in_item",
            source_page_id=self.source,
            evidence="Give the exact token to the quest contact.",
        )
        return quest_id

    def _loot(self, name: str) -> None:
        self.db.add_event(Event(kind="loot", raw=f"You have looted {name}.", item=name))

    def test_exact_canonical_name_takes_precedence_over_other_item_alias(self):
        canonical = self.db.upsert_entity(
            kind="item", name="Ancient Token", external_id="item:canonical"
        )
        alias_owner = self.db.upsert_entity(
            kind="item", name="Misnamed Relic", external_id="item:alias-owner"
        )
        self.db.add_alias(alias_owner, "Ancient Token", alias_type="source")
        self._quest_use(canonical)
        self._loot("Ancient Token")

        rows = recent_loot_relevance(self.db, 0)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].item_id, canonical)
        self.assertEqual(rows[0].item_name, "Ancient Token")

    def test_unique_alias_is_used_only_when_no_canonical_name_exists(self):
        item = self.db.upsert_entity(
            kind="item", name="Pristine Ancient Token", external_id="item:pristine"
        )
        self.db.add_alias(item, "Old Token", alias_type="source")
        self._quest_use(item)
        self._loot("Old Token")

        rows = recent_loot_relevance(self.db, 0)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].item_id, item)
        self.assertEqual(rows[0].item_name, "Pristine Ancient Token")

    def test_duplicate_canonical_names_remain_ambiguous(self):
        first = self.db.upsert_entity(
            kind="item", name="Duplicate Token", external_id="item:duplicate:a"
        )
        self.db.upsert_entity(
            kind="item", name="Duplicate Token", external_id="item:duplicate:b"
        )
        self._quest_use(first)
        self._loot("Duplicate Token")

        self.assertEqual(recent_loot_relevance(self.db, 0), ())

    def test_duplicate_aliases_remain_ambiguous_without_canonical_match(self):
        first = self.db.upsert_entity(
            kind="item", name="First Relic", external_id="item:first"
        )
        second = self.db.upsert_entity(
            kind="item", name="Second Relic", external_id="item:second"
        )
        self.db.add_alias(first, "Shared Token", alias_type="source")
        self.db.add_alias(second, "Shared Token", alias_type="source")
        self._quest_use(first)
        self._loot("Shared Token")

        self.assertEqual(recent_loot_relevance(self.db, 0), ())


if __name__ == "__main__":
    unittest.main()
