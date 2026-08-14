from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.mechanics_catalog import MechanicsCatalog
from eqquest.mechanics_context import (
    build_class_mechanics_context,
    class_mechanics_text,
    resolve_class_identity,
)
from eqquest.runtime import RuntimeDatabase


class ClassMechanicsContextTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.skill_source = self.db.upsert_source_page(
            url="eqclient://Resources/skillcaps.txt",
            title="EverQuest Resources/skillcaps.txt",
            entity_type="skill_cap",
            sha256="context-skillcaps",
            plain_text="fixture",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/skillcaps.txt",
            source_version="live-client",
        )
        self.base_source = self.db.upsert_source_page(
            url="eqclient://Resources/basedata.txt",
            title="EverQuest Resources/basedata.txt",
            entity_type="base_stats",
            sha256="context-basedata",
            plain_text="fixture",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/basedata.txt",
            source_version="live-client",
        )
        self.ac_source = self.db.upsert_source_page(
            url="eqclient://Resources/ACMitigation.txt",
            title="EverQuest Resources/ACMitigation.txt",
            entity_type="ac_mitigation",
            sha256="context-ac",
            plain_text="fixture",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/ACMitigation.txt",
            source_version="live-client",
        )
        self.db.replace_skill_caps(
            self.skill_source,
            [
                (1, 0, 1, 10),
                (1, 0, 2, 15),
                (1, 76, 60, 1),
                (1, 76, 61, 25),
                (5, 1, 1, 5),
            ],
        )
        self.db.replace_base_stats(
            self.base_source,
            [
                (1, 1, 25.0, 0.0, 20.0, 1.0, 0.0, 1.0),
                (3, 1, 35.0, 0.0, 28.0, 2.0, 0.0, 2.0),
                (1, 5, 25.0, 20.0, 20.0, 1.0, 1.0, 1.0),
            ],
        )
        self.db.replace_ac_mitigation(
            self.ac_source,
            [
                (1, 1, 100.0, 0.35),
                (1, 3, 110.0, 0.36),
                (5, 1, 100.0, 0.35),
            ],
        )
        MechanicsCatalog(self.db).reconcile()

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_class_identity_accepts_client_id_name_and_exact_alias_only(self):
        for token, expected_kind in (("1", "client_id"), ("Warrior", "name"), ("WAR", "alias")):
            identity, status = resolve_class_identity(self.db, token)
            self.assertEqual(status, "linked")
            self.assertIsNotNone(identity)
            self.assertEqual(identity.name, "Warrior")
            self.assertEqual(identity.class_id, 1)
            self.assertEqual(identity.matched_by, expected_kind)

        sk, status = resolve_class_identity(self.db, "SK")
        self.assertEqual(status, "linked")
        self.assertEqual(sk.name, "Shadow Knight")

        missing, status = resolve_class_identity(self.db, "Warr")
        self.assertIsNone(missing)
        self.assertEqual(status, "missing")

    def test_base_and_ac_require_exact_requested_level(self):
        context, status = build_class_mechanics_context(self.db, "WAR", 2)
        self.assertEqual(status, "linked")
        self.assertIsNone(context.base_stats)
        self.assertIsNone(context.ac_mitigation)

        exact, _ = build_class_mechanics_context(self.db, "Warrior", 3)
        self.assertEqual(exact.base_stats.level, 3)
        self.assertEqual(exact.base_stats.hp, 35.0)
        self.assertEqual(exact.ac_mitigation.level, 3)
        self.assertEqual(exact.ac_mitigation.ac_cap, 110.0)
        self.assertEqual(exact.base_stats.source.source_key, "Resources/basedata.txt")
        self.assertEqual(exact.ac_mitigation.source.source_key, "Resources/ACMitigation.txt")

    def test_skill_caps_carry_forward_without_inventing_interpolation(self):
        at_one, _ = build_class_mechanics_context(self.db, "Warrior", 1)
        blunt = {skill.name: skill for skill in at_one.skills}["1H Blunt"]
        self.assertEqual(blunt.cap, 10)
        self.assertEqual(blunt.row_level, 1)
        self.assertTrue(blunt.new_this_level)
        self.assertFalse(blunt.changed_this_level)

        at_two, _ = build_class_mechanics_context(self.db, "Warrior", 2)
        blunt = {skill.name: skill for skill in at_two.skills}["1H Blunt"]
        self.assertEqual(blunt.cap, 15)
        self.assertEqual(blunt.row_level, 2)
        self.assertFalse(blunt.new_this_level)
        self.assertTrue(blunt.changed_this_level)

        at_three, _ = build_class_mechanics_context(self.db, "Warrior", 3)
        blunt = {skill.name: skill for skill in at_three.skills}["1H Blunt"]
        self.assertEqual(blunt.cap, 15)
        self.assertEqual(blunt.row_level, 2)
        self.assertFalse(blunt.new_this_level)
        self.assertFalse(blunt.changed_this_level)
        self.assertEqual(blunt.source.source_key, "Resources/skillcaps.txt")

    def test_new_and_changed_skill_progression_are_distinct(self):
        at_sixty, _ = build_class_mechanics_context(self.db, 1, 60)
        triple = {skill.name: skill for skill in at_sixty.skills}["Triple Attack"]
        self.assertEqual(triple.cap, 1)
        self.assertTrue(triple.new_this_level)
        self.assertFalse(triple.changed_this_level)
        self.assertIn(triple, at_sixty.new_skills)

        at_sixty_one, _ = build_class_mechanics_context(self.db, 1, 61)
        triple = {skill.name: skill for skill in at_sixty_one.skills}["Triple Attack"]
        self.assertEqual(triple.cap, 25)
        self.assertFalse(triple.new_this_level)
        self.assertTrue(triple.changed_this_level)
        self.assertIn(triple, at_sixty_one.changed_skills)

    def test_text_states_missing_exact_rows_and_provenance(self):
        text = class_mechanics_text(self.db, "WAR", 2)
        self.assertIn("Warrior | level 2", text)
        self.assertIn("missing base/AC levels are not interpolated", text)
        self.assertIn("Base resources: no exact-level row", text)
        self.assertIn("AC mitigation: no exact-level row", text)
        self.assertIn("1H Blunt: 15", text)
        self.assertIn("cap changed this level", text)
        self.assertIn("EverQuest Client live-client", text)

    def test_finalized_runtime_exposes_same_context_read_only(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="mechanics-context-test",
        )
        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            context, status = build_class_mechanics_context(runtime, "WAR", 61)
            self.assertEqual(status, "linked")
            self.assertEqual(context.identity.name, "Warrior")
            triple = {skill.name: skill for skill in context.skills}["Triple Attack"]
            self.assertEqual((triple.cap, triple.row_level), (25, 61))
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE skill_caps SET cap=999 WHERE class_id=1")
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
