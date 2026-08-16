from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.target_personal_loot import target_personal_loot, target_personal_loot_text


class TargetPersonalLootTests(unittest.TestCase):
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
            source_version="personal-loot-test",
        )

    def _npc(self, name: str = "a cave rat", external_id: str = "npc:rat") -> int:
        return self.db.upsert_entity(kind="npc", name=name, external_id=external_id)

    def _item(self, name: str, external_id: str) -> int:
        return self.db.upsert_entity(kind="item", name=name, external_id=external_id)

    def _loot(self, actor: str, item: str) -> None:
        self.db.conn.execute(
            """
            INSERT INTO observed_events(kind,actor,item,fields_json,raw)
            VALUES('loot',?,?,?,?)
            """,
            (actor or None, item or None, "{}", f"loot {item} from {actor}"),
        )
        self.db.conn.commit()

    def test_exact_corpse_loot_resolves_exact_canonical_item_and_count(self):
        npc = self._npc()
        item = self._item("Cave Rat Tail", "item:tail")
        self._loot("a cave rat", "Cave Rat Tail")
        self._loot("a cave rat", "Cave Rat Tail")

        rows = target_personal_loot(self.db, npc)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.observed_item_name, "Cave Rat Tail")
        self.assertEqual(row.observed_count, 2)
        self.assertEqual(row.resolution_status, "exact")
        self.assertEqual(row.item_id, item)
        self.assertEqual(row.canonical_item_name, "Cave Rat Tail")
        self.assertFalse(row.reviewed_drop_known)
        self.assertEqual(row.evidence_label, "personal observation only")

    def test_exact_unique_item_alias_resolves_without_guessing(self):
        npc = self._npc()
        item = self._item("Pristine Cave Rat Tail", "item:pristine")
        self.db.add_alias(item, "Pristine Rat Tail", alias_type="source")
        self._loot("a cave rat", "Pristine Rat Tail")

        row = target_personal_loot(self.db, npc)[0]

        self.assertEqual(row.resolution_status, "alias")
        self.assertEqual(row.item_id, item)
        self.assertEqual(row.canonical_item_name, "Pristine Cave Rat Tail")
        self.assertIn("exact alias", row.identity_label)

    def test_ambiguous_item_name_stays_visible_but_non_actionable(self):
        npc = self._npc()
        self._item("Ancient Token", "item:token:a")
        self._item("Ancient Token", "item:token:b")
        self._loot("a cave rat", "Ancient Token")

        row = target_personal_loot(self.db, npc)[0]

        self.assertEqual(row.resolution_status, "ambiguous")
        self.assertIsNone(row.item_id)
        self.assertFalse(row.resolved)
        self.assertEqual(row.identity_label, "ambiguous canonical item")

    def test_missing_item_name_stays_personal_history(self):
        npc = self._npc()
        self._loot("a cave rat", "Mystery Rat Thing")

        row = target_personal_loot(self.db, npc)[0]

        self.assertEqual(row.resolution_status, "missing")
        self.assertIsNone(row.item_id)
        self.assertEqual(row.observed_item_name, "Mystery Rat Thing")
        self.assertEqual(row.evidence_label, "personal observation only")

    def test_generic_loot_without_explicit_corpse_source_is_not_assigned_to_target(self):
        npc = self._npc()
        self._item("Cave Rat Tail", "item:tail")
        self._loot("", "Cave Rat Tail")

        self.assertEqual(target_personal_loot(self.db, npc), ())

    def test_reviewed_drop_graph_independently_corroborates_personal_observation(self):
        npc = self._npc()
        item = self._item("Cave Rat Tail", "item:tail")
        page = self._page("npc/rat-drop", "a cave rat", "npc")
        self.db.upsert_relationship(
            item,
            npc,
            "drops_from",
            source_page_id=page,
            evidence="Cave Rat Tail is a reviewed drop from a cave rat.",
        )
        self._loot("a cave rat", "Cave Rat Tail")

        row = target_personal_loot(self.db, npc)[0]

        self.assertTrue(row.reviewed_drop_known)
        self.assertEqual(row.evidence_label, "personal observation + reviewed drop graph")

    def test_unprovenanced_drop_edge_does_not_corroborate_personal_history(self):
        npc = self._npc()
        item = self._item("Rumored Tail", "item:rumor")
        self.db.upsert_relationship(
            item,
            npc,
            "drops_from",
            source_page_id=None,
            evidence="Unreviewed drop rumor.",
        )
        self._loot("a cave rat", "Rumored Tail")

        row = target_personal_loot(self.db, npc)[0]

        self.assertFalse(row.reviewed_drop_known)
        self.assertEqual(row.evidence_label, "personal observation only")

    def test_duplicate_npc_identity_does_not_attach_shared_name_history(self):
        npc_a = self._npc("a duplicated rat", "npc:dup:a")
        self._npc("a duplicated rat", "npc:dup:b")
        self._item("Duplicate Tail", "item:dup")
        self._loot("a duplicated rat", "Duplicate Tail")

        self.assertEqual(target_personal_loot(self.db, npc_a), ())

    def test_detail_text_preserves_personal_vs_canonical_boundary(self):
        npc = self._npc()
        self._item("Personal Tail", "item:personal")
        self._loot("a cave rat", "Personal Tail")
        row = target_personal_loot(self.db, npc)[0]

        text = target_personal_loot_text("a cave rat", row)

        self.assertIn("explicit personal log history", text)
        self.assertIn("No reviewed canonical drop edge", text)
        self.assertIn("not a calculated drop rate", text)
        self.assertIn("Generic loot lines", text)

    def test_non_npc_input_is_rejected(self):
        item = self._item("Not an NPC", "item:not-npc")
        self.assertEqual(target_personal_loot(self.db, item), ())


if __name__ == "__main__":
    unittest.main()
