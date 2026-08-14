from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.mechanics import skill_name_for_client_id
from eqquest.mechanics_catalog import MechanicsCatalog, mechanics_audit_text
from eqquest.runtime import RuntimeDatabase


class MechanicsCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.skill_source = self.db.upsert_source_page(
            url="eqclient://Resources/skillcaps.txt",
            title="EverQuest Resources/skillcaps.txt",
            entity_type="skill_cap",
            sha256="skillcaps",
            plain_text="fixture",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/skillcaps.txt",
        )
        self.base_source = self.db.upsert_source_page(
            url="eqclient://Resources/basedata.txt",
            title="EverQuest Resources/basedata.txt",
            entity_type="base_stats",
            sha256="basedata",
            plain_text="fixture",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/basedata.txt",
        )
        self.ac_source = self.db.upsert_source_page(
            url="eqclient://Resources/ACMitigation.txt",
            title="EverQuest Resources/ACMitigation.txt",
            entity_type="ac_mitigation",
            sha256="ac",
            plain_text="fixture",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="Resources/ACMitigation.txt",
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _seed_support_rows(self) -> None:
        self.db.replace_skill_caps(
            self.skill_source,
            [
                (1, 0, 1, 10),
                (1, 0, 2, 15),
                (1, 76, 60, 1),
                (1, 76, 61, 25),
                (5, 1, 1, 5),
                (5, 999, 1, 7),
            ],
        )
        self.db.replace_base_stats(
            self.base_source,
            [
                (1, 1, 25.0, 0.0, 20.0, 1.0, 0.0, 1.0),
                (1, 5, 25.0, 20.0, 20.0, 1.0, 1.0, 1.0),
            ],
        )
        self.db.replace_ac_mitigation(
            self.ac_source,
            [
                (1, 1, 100.0, 0.35),
                (5, 1, 100.0, 0.35),
            ],
        )

    def test_reconcile_creates_namespaced_class_and_skill_entities(self):
        self._seed_support_rows()
        coverage = MechanicsCatalog(self.db).reconcile()

        warrior = self.db.entity_by_namespaced_external_id("eqclient:class", "1")
        shadow_knight = self.db.entity_by_namespaced_external_id("eqclient:class", "5")
        blunt = self.db.entity_by_namespaced_external_id("eqclient:skill", "0")
        triple = self.db.entity_by_namespaced_external_id("eqclient:skill", "76")

        self.assertEqual(warrior["name"], "Warrior")
        self.assertEqual(shadow_knight["name"], "Shadow Knight")
        self.assertEqual(blunt["name"], "1H Blunt")
        self.assertEqual(triple["name"], "Triple Attack")
        self.assertTrue(self.db.name_matches_entity(int(warrior["id"]), "WAR"))
        self.assertTrue(self.db.name_matches_entity(int(shadow_knight["id"]), "Shadowknight"))
        self.assertEqual(skill_name_for_client_id(self.db, 76), "Triple Attack")

        self.assertEqual(coverage.class_ids_unresolved, ())
        self.assertEqual(coverage.skill_ids_unresolved, (999,))
        self.assertEqual(coverage.class_ids_named, 2)
        self.assertEqual(coverage.skill_ids_named, 3)

    def test_client_support_sources_are_attached_as_evidence(self):
        self._seed_support_rows()
        MechanicsCatalog(self.db).reconcile()

        warrior = self.db.entity_by_namespaced_external_id("eqclient:class", "1")
        blunt = self.db.entity_by_namespaced_external_id("eqclient:skill", "0")
        warrior_sources = {
            (row["source_key"], row["role"])
            for row in self.db.sources_for_entity(int(warrior["id"]))
        }
        blunt_sources = {
            (row["source_key"], row["role"])
            for row in self.db.sources_for_entity(int(blunt["id"]))
        }

        self.assertIn(("Resources/skillcaps.txt", "client_mechanics_evidence"), warrior_sources)
        self.assertIn(("Resources/basedata.txt", "client_mechanics_evidence"), warrior_sources)
        self.assertIn(("Resources/ACMitigation.txt", "client_mechanics_evidence"), warrior_sources)
        self.assertIn(("Resources/skillcaps.txt", "client_mechanics_evidence"), blunt_sources)
        self.assertTrue(any(role == "vocabulary" for _key, role in blunt_sources))

    def test_class_skill_relationship_contains_progression_summary(self):
        self._seed_support_rows()
        MechanicsCatalog(self.db).reconcile()

        warrior = self.db.entity_by_namespaced_external_id("eqclient:class", "1")
        rows = self.db.relationship_targets(int(warrior["id"]), "can_train_skill")
        by_name = {row["name"]: row for row in rows}

        self.assertEqual(int(by_name["1H Blunt"]["quantity"]), 15)
        blunt_data = json.loads(by_name["1H Blunt"]["relationship_data_json"])
        self.assertEqual(blunt_data["first_level"], 1)
        self.assertEqual(blunt_data["max_cap"], 15)
        self.assertEqual(blunt_data["levels_observed"], 2)

        triple_data = json.loads(by_name["Triple Attack"]["relationship_data_json"])
        self.assertEqual(triple_data["first_level"], 60)
        self.assertEqual(triple_data["max_cap"], 25)

    def test_reconcile_is_idempotent_and_rebuilds_derived_relationships(self):
        self._seed_support_rows()
        catalog = MechanicsCatalog(self.db)
        first = catalog.reconcile()
        second = catalog.reconcile()
        self.assertEqual(first.class_skill_relationships, second.class_skill_relationships)

        count = int(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE relation='can_train_skill'"
            ).fetchone()[0]
        )
        self.assertEqual(count, first.class_skill_relationships)

    def test_audit_reports_unresolved_support_ids_explicitly(self):
        self._seed_support_rows()
        MechanicsCatalog(self.db).reconcile()
        text = mechanics_audit_text(self.db)
        self.assertIn("Skill IDs observed: 4", text)
        self.assertIn("Unresolved skill IDs: 999", text)

    def test_finalized_snapshot_compiles_mechanics_without_runtime_mcp(self):
        self.db.replace_skill_caps(
            self.skill_source,
            [(2, 31, 1, 5), (2, 31, 2, 10)],
        )
        self.db.close()

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="mechanics-catalog-test",
        )
        runtime = RuntimeDatabase(snapshot, state)
        try:
            cleric = runtime.entity_by_namespaced_external_id("eqclient:class", "2")
            meditate = runtime.entity_by_namespaced_external_id("eqclient:skill", "31")
            self.assertEqual(cleric["name"], "Cleric")
            self.assertEqual(meditate["name"], "Meditate")
            self.assertEqual(skill_name_for_client_id(runtime, 31), "Meditate")
            with self.assertRaisesRegex(RuntimeError, "builder-only"):
                MechanicsCatalog(runtime).reconcile()
        finally:
            runtime.close()

        # tearDown should not close this instance a second time.
        self.db = Database(self.root / "throwaway.sqlite3")


if __name__ == "__main__":
    unittest.main()
