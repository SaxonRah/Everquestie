from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.target_quest_connections import (
    target_quest_connection_text,
    target_quest_connections,
)


class TargetQuestConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
        self.npc = self.db.upsert_entity(
            kind="npc",
            name="Brewer Brolin",
            external_id="npc:target",
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _source(self, key: str) -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/db/quest.html?quest={key}",
            title=f"Quest {key}",
            entity_type="quest",
            sha256=f"sha-{key}",
            plain_text="structured quest source",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=f"quest:{key}",
        )

    def _quest(
        self,
        key: str,
        name: str,
        *,
        data: dict | None = None,
        source: int | None = None,
    ) -> tuple[int, int]:
        page = source or self._source(key)
        quest = self.db.upsert_entity(
            kind="quest",
            name=name,
            external_id=f"quest:{key}",
            source_page_id=page,
            source_url=f"https://everquest.allakhazam.com/db/quest.html?quest={key}",
            data=data or {},
        )
        return quest, page

    def test_reviewed_quest_relations_project_exact_quest_ids(self):
        expected = {
            "started_by": "quest starter",
            "objective_turn_in_to": "turn-in NPC",
            "objective_speak": "speak objective",
            "objective_kill": "kill objective",
        }
        quest_ids: dict[str, int] = {}
        for index, (relation, _label) in enumerate(expected.items(), start=1):
            quest, page = self._quest(str(index), f"Quest {index}")
            quest_ids[relation] = quest
            self.db.upsert_relationship(
                quest,
                self.npc,
                relation,
                source_page_id=page,
                evidence=f"Evidence for {relation}",
            )

        rows = target_quest_connections(self.db, self.npc)

        self.assertEqual(len(rows), 4)
        self.assertEqual({row.quest_id for row in rows}, set(quest_ids.values()))
        self.assertEqual(
            {row.relation: row.relation_label for row in rows},
            expected,
        )
        self.assertTrue(all(row.evidence.startswith("Evidence for") for row in rows))
        self.assertTrue(all(row.source_url.startswith("https://everquest.allakhazam.com/") for row in rows))

    def test_duplicate_provenance_rows_do_not_duplicate_semantic_connection(self):
        quest, page_a = self._quest("10", "One Quest")
        page_b = self._source("10-b")
        self.db.upsert_relationship(
            quest,
            self.npc,
            "objective_speak",
            source_page_id=page_a,
            evidence="Primary evidence",
        )
        self.db.upsert_relationship(
            quest,
            self.npc,
            "objective_speak",
            source_page_id=page_b,
            evidence="Corroborating evidence",
        )

        rows = target_quest_connections(self.db, self.npc)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].quest_id, quest)
        self.assertEqual(rows[0].relation, "objective_speak")

    def test_source_less_relationship_is_not_actionable_target_quest(self):
        quest, _page = self._quest("20", "Unproven Quest")
        self.db.upsert_relationship(
            quest,
            self.npc,
            "started_by",
            evidence="synthetic edge without retained provenance",
        )

        self.assertEqual(target_quest_connections(self.db, self.npc), ())

    def test_tracked_connection_ranks_before_untracked_relation_priority(self):
        starter, starter_page = self._quest("30", "Untracked Starter")
        tracked, tracked_page = self._quest("31", "Tracked Kill Quest")
        self.db.upsert_relationship(
            starter,
            self.npc,
            "started_by",
            source_page_id=starter_page,
            evidence="Quest Started By: Brewer Brolin",
        )
        self.db.upsert_relationship(
            tracked,
            self.npc,
            "objective_kill",
            source_page_id=tracked_page,
            evidence="Kill Brewer Brolin",
        )
        self.db.track_quest(tracked)

        rows = target_quest_connections(self.db, self.npc)

        self.assertEqual(rows[0].quest_id, tracked)
        self.assertTrue(rows[0].tracked)
        self.assertEqual(rows[1].quest_id, starter)
        self.assertFalse(rows[1].tracked)

    def test_profile_blocked_quest_is_omitted_but_unknown_is_retained(self):
        modern, modern_page = self._quest(
            "40",
            "Modern Brewer Quest",
            data={"era": "The Serpent's Spine"},
        )
        unknown, unknown_page = self._quest("41", "Unknown Era Brewer Quest")
        for quest, page in ((modern, modern_page), (unknown, unknown_page)):
            self.db.upsert_relationship(
                quest,
                self.npc,
                "objective_speak",
                source_page_id=page,
                evidence="Speak to Brewer Brolin",
            )

        rows = target_quest_connections(self.db, self.npc, profile_id="p99")

        self.assertEqual([row.quest_id for row in rows], [unknown])
        self.assertEqual(rows[0].profile_status, "unknown")

    def test_non_npc_input_returns_no_connections(self):
        item = self.db.upsert_entity(kind="item", name="Bog Bark", external_id="item:1")
        self.assertEqual(target_quest_connections(self.db, item), ())

    def test_explanation_names_exact_relation_and_does_not_claim_ownership(self):
        quest, page = self._quest("50", "Bark for the Brewer")
        self.db.upsert_relationship(
            quest,
            self.npc,
            "objective_turn_in_to",
            source_page_id=page,
            evidence="Give the bark to Brewer Brolin.",
        )
        row = target_quest_connections(self.db, self.npc)[0]

        text = target_quest_connection_text(row)

        self.assertIn("Target connection: turn-in NPC", text)
        self.assertIn("Give the bark to Brewer Brolin", text)
        self.assertIn("does not mean the quest is owned", text)
        self.assertIn("Track quest", text)


if __name__ == "__main__":
    unittest.main()
