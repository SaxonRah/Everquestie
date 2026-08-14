from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.spell_stacking_context import build_spell_stacking_context, spell_stacking_text


class SpellStackingContextTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.source = self.db.upsert_source_page(
            url="eqclient://Resources/SpellStackingGroups.txt",
            title="EverQuest Resources/SpellStackingGroups.txt",
            entity_type="spell_stacking",
            sha256="stacking-context",
            plain_text="fixture",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/SpellStackingGroups.txt",
            source_version="live-client",
        )
        self.provider_source = self.db.upsert_source_page(
            url="https://example.invalid/provider/spell/100",
            title="Provider spell 100",
            entity_type="spell",
            sha256="provider-spell-100",
            plain_text="fixture",
            raw_html="",
            source_name="Fixture Provider",
            source_kind="fixture",
            source_key="spell:100",
            source_version="1",
        )
        self.fire = self.db.upsert_entity(
            kind="spell",
            name="Fire Shield",
            external_id="100",
            external_namespace="eqclient:spell",
            merge_by_name=True,
        )
        self.greater = self.db.upsert_entity(
            kind="spell",
            name="Greater Fire Shield",
            external_id="101",
            external_namespace="eqclient:spell",
            merge_by_name=True,
        )
        self.unlisted = self.db.upsert_entity(
            kind="spell",
            name="Unlisted Client Spell",
            external_id="102",
            external_namespace="eqclient:spell",
            merge_by_name=True,
        )
        # Model a genuinely separate provider namespace that happens to use the same
        # numeric external ID. This is the collision spell_id_for_entity must reject.
        self.provider_only = self.db.upsert_entity(
            kind="spell",
            name="Provider Only Spell",
            source_page_id=self.provider_source,
            source_url="https://example.invalid/provider/spell/100",
            external_id="100",
            external_namespace="fixture:spell",
        )
        self.db.replace_spell_stacking(
            self.source,
            [
                (100, 7, 1, 2),
                (101, 7, 2, 2),
                (999, 7, 3, 9),
            ],
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_context_projects_exact_numeric_row_and_provenance(self):
        context, status = build_spell_stacking_context(self.db, self.fire)
        self.assertEqual(status, "linked")
        self.assertEqual(context.name, "Fire Shield")
        self.assertEqual(context.spell_id, 100)
        self.assertEqual((context.stacking_group, context.rank, context.stacking_type), (7, 1, 2))
        self.assertEqual(context.source.source_key, "Resources/SpellStackingGroups.txt")
        self.assertEqual(context.source.source_version, "live-client")

    def test_same_group_peers_use_canonical_client_identity(self):
        context, _ = build_spell_stacking_context(self.db, self.fire)
        by_id = {peer.spell_id: peer for peer in context.peers}
        self.assertEqual(by_id[100].entity_id, self.fire)
        self.assertEqual(by_id[100].name, "Fire Shield")
        self.assertEqual(by_id[101].entity_id, self.greater)
        self.assertEqual(by_id[101].name, "Greater Fire Shield")
        self.assertIsNone(by_id[999].entity_id)
        self.assertEqual(by_id[999].name, "spell ID 999")

    def test_provider_numeric_collision_is_not_client_identity(self):
        context, status = build_spell_stacking_context(self.db, self.provider_only)
        self.assertIsNone(context)
        self.assertEqual(status, "client_identity_missing")

    def test_client_identity_without_stacking_row_is_distinct_missing_state(self):
        context, status = build_spell_stacking_context(self.db, self.unlisted)
        self.assertEqual(status, "stacking_missing")
        self.assertIsNotNone(context)
        self.assertEqual(context.spell_id, 102)
        self.assertFalse(context.has_stacking_row)
        self.assertEqual(context.peers, ())

    def test_non_spell_entity_is_rejected(self):
        npc = self.db.upsert_entity(kind="npc", name="Not A Spell", merge_by_name=True)
        context, status = build_spell_stacking_context(self.db, npc)
        self.assertIsNone(context)
        self.assertEqual(status, "entity_missing")

    def test_text_exposes_raw_fields_without_claiming_stacking_verdict(self):
        text = spell_stacking_text(self.db, self.fire)
        self.assertIn("Stacking group: 7", text)
        self.assertIn("Rank: 1", text)
        self.assertIn("Stacking type: 2", text)
        self.assertIn("shown exactly as stored", text)
        self.assertIn("does not infer a stacking verdict", text)
        self.assertIn("Greater Fire Shield", text)
        self.assertIn("spell ID 999", text)
        self.assertIn("EverQuest Client live-client", text)

    def test_finalized_runtime_exposes_same_stacking_context_read_only(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="spell-stacking-context-test",
        )
        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            context, status = build_spell_stacking_context(runtime, self.fire)
            self.assertEqual(status, "linked")
            self.assertEqual(context.spell_id, 100)
            self.assertEqual([peer.spell_id for peer in context.peers], [100, 101, 999])
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE spell_stacking SET rank=999 WHERE spell_id=100")
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
