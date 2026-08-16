from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.target_known_drops import target_known_drop_text, target_known_drops


class TargetKnownDropsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _page(self, key: str, title: str, entity_type: str) -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/{key}",
            title=title,
            entity_type=entity_type,
            sha256=f"sha-{key}",
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="target-drop-test",
        )

    def _npc(self, name: str = "a cave rat") -> int:
        return self.db.upsert_entity(kind="npc", name=name, external_id=f"npc:{name}")

    def _item(self, name: str) -> int:
        return self.db.upsert_entity(kind="item", name=name, external_id=f"item:{name}")

    def _quest(self, name: str) -> int:
        return self.db.upsert_entity(kind="quest", name=name, external_id=f"quest:{name}")

    def test_source_backed_drop_is_grouped_by_exact_item_identity(self):
        npc = self._npc()
        item = self._item("Cave Rat Tail")
        page_a = self._page("npc/drop-a", "Cave Rat drops", "npc")
        page_b = self._page("item/drop-b", "Cave Rat Tail", "item")
        self.db.upsert_relationship(
            item, npc, "drops_from", source_page_id=page_a,
            evidence="Cave Rat Tail appears in the NPC drop list.",
        )
        self.db.upsert_relationship(
            item, npc, "drops_from", source_page_id=page_b,
            evidence="Cave Rat Tail lists a cave rat as a source.",
        )

        drops = target_known_drops(self.db, npc)

        self.assertEqual(len(drops), 1)
        self.assertEqual(drops[0].item_id, item)
        self.assertEqual(drops[0].item_name, "Cave Rat Tail")
        self.assertEqual(drops[0].evidence_count, 2)
        self.assertEqual(drops[0].source_labels, ("Allakhazam",))
        self.assertEqual(len(drops[0].evidence), 2)

    def test_unprovenanced_drop_relationship_is_not_player_facing_drop_evidence(self):
        npc = self._npc()
        item = self._item("Rumored Tail")
        self.db.upsert_relationship(
            item, npc, "drops_from", source_page_id=None,
            evidence="Unreviewed rumor.",
        )

        self.assertEqual(target_known_drops(self.db, npc), ())

    def test_reviewed_quest_use_is_attached_and_tracked_use_ranks_first(self):
        npc = self._npc()
        tracked_item = self._item("Tracked Pelt")
        other_item = self._item("Ordinary Fang")
        tracked_quest = self._quest("Tracked Pelt Quest")
        other_quest = self._quest("Fang Quest")
        drop_page = self._page("npc/uses", "NPC drop list", "npc")
        quest_page = self._page("quest/uses", "Quest uses", "quest")
        for item in (tracked_item, other_item):
            self.db.upsert_relationship(
                item, npc, "drops_from", source_page_id=drop_page,
                evidence="Reviewed exact drop.",
            )
        self.db.upsert_relationship(
            tracked_quest, tracked_item, "objective_turn_in_item",
            source_page_id=quest_page, evidence="Turn in one Tracked Pelt.",
        )
        self.db.upsert_relationship(
            other_quest, other_item, "quest_item",
            source_page_id=quest_page, evidence="Ordinary Fang is listed for the quest.",
        )
        self.db.track_quest(tracked_quest)

        drops = target_known_drops(self.db, npc)

        self.assertEqual([drop.item_id for drop in drops], [tracked_item, other_item])
        self.assertTrue(drops[0].quest_uses[0].tracked)
        self.assertEqual(drops[0].quest_use_label, "turn-in item: Tracked Pelt Quest [tracked]")
        self.assertEqual(drops[1].quest_use_label, "quest item: Fang Quest")

    def test_unprovenanced_quest_relation_does_not_become_drop_quest_use(self):
        npc = self._npc()
        item = self._item("Known Drop")
        quest = self._quest("Unreviewed Use")
        page = self._page("npc/known", "Known drop", "npc")
        self.db.upsert_relationship(
            item, npc, "drops_from", source_page_id=page, evidence="Reviewed drop."
        )
        self.db.upsert_relationship(
            quest, item, "objective_loot", source_page_id=None,
            evidence="Unreviewed quest relation.",
        )

        drop = target_known_drops(self.db, npc)[0]

        self.assertEqual(drop.quest_uses, ())
        self.assertEqual(drop.quest_use_label, "no reviewed quest use")

    def test_detail_text_refuses_drop_rate_and_completeness_claims(self):
        npc = self._npc()
        item = self._item("Cave Rat Tail")
        page = self._page("npc/text", "Cave Rat drops", "npc")
        self.db.upsert_relationship(
            item, npc, "drops_from", source_page_id=page,
            evidence="Cave Rat Tail is a reviewed drop.",
        )
        drop = target_known_drops(self.db, npc)[0]

        text = target_known_drop_text("a cave rat", drop)

        self.assertIn("Known source-backed drop from exact target", text)
        self.assertIn("does not imply a drop rate", text)
        self.assertIn("complete loot table", text)

    def test_non_npc_input_is_rejected(self):
        item = self._item("Not an NPC")
        self.assertEqual(target_known_drops(self.db, item), ())


if __name__ == "__main__":
    unittest.main()
