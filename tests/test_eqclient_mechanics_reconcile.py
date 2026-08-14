from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.mechanics_context import build_class_mechanics_context
from eqquest.mechanics_context_ui import ensure_builder_mechanics_catalog
from eqquest.sources import EQClientImporter
from eqquest.sources.eqclient import EQClientImporter as RawEQClientImporter


class EQClientMechanicsReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.eq = self.root / "EverQuest"
        resources = self.eq / "Resources"
        resources.mkdir(parents=True)

        # skillcaps.txt columns are class_id, skill_id, level, cap.
        # One explicit Warrior / 1H Blunt progression row.
        (resources / "skillcaps.txt").write_text("1^0^1^5\n", encoding="utf-8")
        # basedata.txt: level, class, HP, mana, endurance, unused x2, regen x3.
        (resources / "basedata.txt").write_text(
            "1^1^100^0^50^0^0^1^0^1\n",
            encoding="utf-8",
        )
        (resources / "ACMitigation.txt").write_text("1^1^350^0.35\n", encoding="utf-8")
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def test_public_client_importer_immediately_builds_canonical_mechanics(self):
        importer = EQClientImporter(self.db)
        result = importer.import_installation(self.eq)

        self.assertEqual(result.skill_caps, 1)
        self.assertIsNotNone(importer.last_mechanics_coverage)
        self.assertIsNotNone(self.db.entity_by_namespaced_external_id("eqclient:class", "1"))
        self.assertIsNotNone(self.db.entity_by_namespaced_external_id("eqclient:skill", "0"))

        context, status = build_class_mechanics_context(self.db, "Warrior", 1)
        self.assertEqual(status, "linked")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.identity.class_id, 1)
        self.assertIsNotNone(context.base_stats)
        self.assertIsNotNone(context.ac_mitigation)
        skill = next(item for item in context.skills if item.skill_id == 0)
        self.assertEqual(skill.name, "1H Blunt")
        self.assertEqual(skill.cap, 5)

    def test_reimport_is_idempotent_for_derived_class_skill_relationships(self):
        importer = EQClientImporter(self.db)
        importer.import_installation(self.eq)
        importer.import_installation(self.eq)

        rows = self.db.conn.execute(
            "SELECT * FROM entity_relationships WHERE relation='can_train_skill'"
        ).fetchall()
        matching = [
            row
            for row in rows
            if int(row["source_entity_id"])
            == int(self.db.entity_by_namespaced_external_id("eqclient:class", "1")["id"])
            and int(row["target_entity_id"])
            == int(self.db.entity_by_namespaced_external_id("eqclient:skill", "0")["id"])
        ]
        self.assertEqual(len(matching), 1)

    def test_existing_raw_builder_db_is_backfilled_without_reimporting_files(self):
        # Reproduce a pre-fix builder DB: support rows exist, but release finalization
        # has never written its canonical mechanics catalog back into the working DB.
        RawEQClientImporter(self.db).import_installation(self.eq)
        self.assertIsNone(self.db.entity_by_namespaced_external_id("eqclient:class", "1"))

        changed = ensure_builder_mechanics_catalog(self.db)

        self.assertTrue(changed)
        context, status = build_class_mechanics_context(self.db, "Warrior", 1)
        self.assertEqual(status, "linked")
        self.assertIsNotNone(context)
        self.assertEqual(self.db.get_meta("mechanics_catalog_version", ""), "1")

    def test_builder_compatibility_ensure_is_idempotent(self):
        RawEQClientImporter(self.db).import_installation(self.eq)
        self.assertTrue(ensure_builder_mechanics_catalog(self.db))
        relationship_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM entity_relationships WHERE relation='can_train_skill'"
        ).fetchone()[0]

        self.assertFalse(ensure_builder_mechanics_catalog(self.db))
        self.assertEqual(
            self.db.conn.execute(
                "SELECT COUNT(*) FROM entity_relationships WHERE relation='can_train_skill'"
            ).fetchone()[0],
            relationship_count,
        )

    def test_packaged_read_only_database_never_runs_builder_reconciliation(self):
        fake = SimpleNamespace(knowledge_writable=False)
        self.assertFalse(ensure_builder_mechanics_catalog(fake))


if __name__ == "__main__":
    unittest.main()
