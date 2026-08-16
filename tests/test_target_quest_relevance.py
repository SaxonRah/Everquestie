from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.target_quest_relevance import target_quest_relevance, target_quest_relevance_text


class TargetQuestRelevanceTests(unittest.TestCase):
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
            source_version="target-quest-test",
        )

    def _npc(self, name: str = "a cave rat") -> int:
        return self.db.upsert_entity(kind="npc", name=name, external_id=f"npc:{name}")

    def _quest(self, name: str) -> int:
        return self.db.upsert_entity(kind="quest", name=name, external_id=f"quest:{name}")

    def _item(self, name: str) -> int:
        return self.db.upsert_entity(kind="item", name=name, external_id=f"item:{name}")

    def test_direct_source_backed_quest_relationship_is_relevance(self):
        npc = self._npc()
        quest = self._quest("Rat Catching")
        page = self._page("quest/1", "Rat Catching", "quest")
        self.db.upsert_relationship(
            quest, npc, "objective_kill", source_page_id=page, evidence="Kill a cave rat."
        )

        rows = target_quest_relevance(self.db, npc)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].quest_id, quest)
        self.assertEqual(rows[0].primary_reason, "Kill objective")
        self.assertEqual(rows[0].reasons[0].path_kind, "direct")
        self.assertIn("Kill a cave rat", rows[0].reasons[0].evidence)

    def test_unprovenanced_direct_relationship_is_rejected(self):
        npc = self._npc()
        quest = self._quest("Rumored Rat Quest")
        self.db.upsert_relationship(
            quest, npc, "objective_kill", source_page_id=None, evidence="Unreviewed relationship."
        )
        self.assertEqual(target_quest_relevance(self.db, npc), ())

    def test_drop_chain_requires_both_source_backed_edges(self):
        npc = self._npc()
        item = self._item("Cave Rat Tail")
        quest = self._quest("Tails for the Tanner")
        drop_page = self._page("npc/2", "a cave rat", "npc")
        quest_page = self._page("quest/2", "Tails for the Tanner", "quest")
        self.db.upsert_relationship(
            item, npc, "drops_from", source_page_id=drop_page,
            evidence="Cave Rat Tail is listed as a drop.",
        )
        self.db.upsert_relationship(
            quest, item, "objective_turn_in_item", source_page_id=quest_page,
            evidence="Turn in a Cave Rat Tail.",
        )

        rows = target_quest_relevance(self.db, npc)

        self.assertEqual(len(rows), 1)
        reason = rows[0].reasons[0]
        self.assertEqual(reason.path_kind, "drop_chain")
        self.assertEqual(reason.via_item_id, item)
        self.assertEqual(reason.display_label, "Drops turn-in item: Cave Rat Tail")
        self.assertIn("drop:", reason.evidence)
        self.assertIn("quest use:", reason.evidence)

        other_npc = self._npc("an unproven rat")
        unproven_item = self._item("Unproven Tail")
        other_quest = self._quest("Unproven Tails")
        self.db.upsert_relationship(
            unproven_item, other_npc, "drops_from", source_page_id=None, evidence="No source."
        )
        self.db.upsert_relationship(
            other_quest, unproven_item, "objective_turn_in_item", source_page_id=quest_page,
            evidence="Quest edge is sourced but drop edge is not.",
        )
        self.assertEqual(target_quest_relevance(self.db, other_npc), ())

    def test_duplicate_provenance_rows_do_not_duplicate_one_reason(self):
        npc = self._npc()
        quest = self._quest("Two Sources One Quest")
        page_a = self._page("quest/3a", "Two Sources One Quest A", "quest")
        page_b = self._page("quest/3b", "Two Sources One Quest B", "quest")
        self.db.upsert_relationship(
            quest, npc, "started_by", source_page_id=page_a, evidence="Starter evidence A."
        )
        self.db.upsert_relationship(
            quest, npc, "started_by", source_page_id=page_b, evidence="Starter evidence B."
        )

        rows = target_quest_relevance(self.db, npc)

        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0].reasons), 1)
        self.assertEqual(rows[0].primary_reason, "Starts quest")

    def test_tracked_quest_ranks_before_other_equally_direct_quest(self):
        npc = self._npc()
        page = self._page("npc/4", "a cave rat", "npc")
        alpha = self._quest("Alpha Quest")
        zulu = self._quest("Zulu Quest")
        for quest in (alpha, zulu):
            self.db.upsert_relationship(
                quest, npc, "objective_kill", source_page_id=page,
                evidence="Exact kill objective.",
            )
        self.db.track_quest(zulu)

        rows = target_quest_relevance(self.db, npc)

        self.assertEqual([row.quest_id for row in rows], [zulu, alpha])
        self.assertTrue(rows[0].tracked)
        self.assertFalse(rows[1].tracked)

    def test_active_tracked_exact_npc_step_surfaces_live_progress_without_graph_edge(self):
        npc = self._npc("a gnoll pup")
        quest = self._quest("Cull the Pups")
        page = self._page("quest/tracked-kill", "Cull the Pups", "quest")
        self.db.add_quest_step(
            quest,
            1,
            "Defeat five gnoll pups",
            match={"event": "kill", "npc_entity_id": npc, "count": 5},
            source_page_id=page,
        )
        self.db.track_quest(quest)
        self.db.set_step_progress(quest, 1, 2, False)

        rows = target_quest_relevance(self.db, npc)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row.tracked)
        self.assertEqual(row.tracked_progress_label, "active 2/5")
        reason = row.reasons[0]
        self.assertEqual(reason.path_kind, "tracked_step")
        self.assertEqual(reason.step_order, 1)
        self.assertTrue(reason.active_step)
        self.assertEqual(reason.display_label, "Active tracked kill objective [2/5]")
        self.assertIn("Defeat five gnoll pups", reason.evidence)

    def test_tracked_step_without_source_page_cannot_claim_target_progress(self):
        npc = self._npc("an unsourced gnoll")
        quest = self._quest("Unsourced Objective")
        self.db.add_quest_step(
            quest,
            1,
            "Defeat the unsourced gnoll",
            match={"event": "kill", "npc_entity_id": npc, "count": 2},
            source_page_id=None,
        )
        self.db.track_quest(quest)

        self.assertEqual(target_quest_relevance(self.db, npc), ())

    def test_tracked_item_step_requires_reviewed_drop_before_target_is_source(self):
        npc = self._npc("a diseased rat")
        item = self._item("Diseased Rat Pelt")
        quest = self._quest("Pelt Collection")
        quest_page = self._page("quest/pelts", "Pelt Collection", "quest")
        drop_page = self._page("npc/diseased-rat", "a diseased rat", "npc")
        self.db.add_quest_step(
            quest,
            1,
            "Loot three Diseased Rat Pelts",
            match={"event": "loot", "item_entity_id": item, "count": 3},
            source_page_id=quest_page,
        )
        self.db.track_quest(quest)

        self.assertEqual(target_quest_relevance(self.db, npc), ())

        self.db.upsert_relationship(
            item,
            npc,
            "drops_from",
            source_page_id=drop_page,
            evidence="Diseased Rat Pelt is a reviewed drop from a diseased rat.",
        )
        rows = target_quest_relevance(self.db, npc)

        self.assertEqual(len(rows), 1)
        reason = rows[0].reasons[0]
        self.assertEqual(reason.path_kind, "tracked_step")
        self.assertEqual(reason.via_item_id, item)
        self.assertEqual(
            reason.display_label,
            "Active tracked loot objective: Diseased Rat Pelt [0/3]",
        )

    def test_parallel_count_step_is_visible_but_future_sequential_contact_is_not(self):
        active_npc = self._npc("Quest Giver")
        target = self._npc("a roaming wolf")
        quest = self._quest("Parallel Work")
        page = self._page("quest/parallel", "Parallel Work", "quest")
        self.db.add_quest_step(
            quest,
            1,
            "Speak to Quest Giver",
            match={"event": "say", "npc_entity_id": active_npc},
            source_page_id=page,
        )
        self.db.add_quest_step(
            quest,
            2,
            "Defeat four roaming wolves",
            match={"event": "kill", "npc_entity_id": target, "count": 4},
            source_page_id=page,
        )
        self.db.add_quest_step(
            quest,
            3,
            "Speak to a roaming wolf after the hunt",
            match={"event": "say", "npc_entity_id": target},
            source_page_id=page,
        )
        self.db.track_quest(quest)
        self.db.set_step_progress(quest, 2, 1, False)

        rows = target_quest_relevance(self.db, target)

        self.assertEqual(len(rows), 1)
        step_reasons = [r for r in rows[0].reasons if r.path_kind == "tracked_step"]
        self.assertEqual(len(step_reasons), 1)
        self.assertEqual(step_reasons[0].step_order, 2)
        self.assertFalse(step_reasons[0].active_step)
        self.assertEqual(step_reasons[0].progress_label, "parallel 1/4")
        self.assertEqual(step_reasons[0].display_label, "Parallel tracked kill objective [1/4]")

    def test_detail_text_explains_non_inference_boundary(self):
        npc = self._npc()
        quest = self._quest("Talk to the Rat")
        page = self._page("quest/5", "Talk to the Rat", "quest")
        self.db.upsert_relationship(
            quest, npc, "objective_speak", source_page_id=page,
            evidence="Speak with a cave rat.",
        )
        row = target_quest_relevance(self.db, npc)[0]

        text = target_quest_relevance_text(row)

        self.assertIn("Conversation target", text)
        self.assertIn("normalized source-backed relationships", text)
        self.assertIn("does not infer quest relevance", text)

    def test_tracked_detail_text_names_step_progress_and_identity_boundary(self):
        npc = self._npc("a named target")
        quest = self._quest("Tracked Detail")
        page = self._page("quest/tracked-detail", "Tracked Detail", "quest")
        self.db.add_quest_step(
            quest,
            1,
            "Defeat the named target",
            match={"event": "kill", "npc_entity_id": npc, "count": 2},
            source_page_id=page,
        )
        self.db.track_quest(quest)
        row = target_quest_relevance(self.db, npc)[0]

        text = target_quest_relevance_text(row)

        self.assertIn("Structured step 1; active now", text)
        self.assertIn("exact canonical ID", text)
        self.assertIn("player state", text)

    def test_non_npc_entity_is_not_accepted_as_target(self):
        item = self._item("Not an NPC")
        self.assertEqual(target_quest_relevance(self.db, item), ())


if __name__ == "__main__":
    unittest.main()
