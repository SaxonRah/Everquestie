from __future__ import annotations

from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest

from eqquest.runtime_map_diagnostics import release_map_catalog_text
from eqquest.runtime_mode_ui import install_runtime_mode_ui


class RuntimeMapDiagnosticsTests(unittest.TestCase):
    @staticmethod
    def _packaged_db():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE map_sources(
                id INTEGER PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_version TEXT NOT NULL
            );
            CREATE TABLE map_labels(
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL
            );
            """
        )
        goods_one = conn.execute(
            "INSERT INTO map_sources(source_name,source_version) VALUES('Goods','2026-08-17')"
        ).lastrowid
        goods_two = conn.execute(
            "INSERT INTO map_sources(source_name,source_version) VALUES('Goods','2026-08-17')"
        ).lastrowid
        brewall = conn.execute(
            "INSERT INTO map_sources(source_name,source_version) VALUES('Brewall','2026-08-16')"
        ).lastrowid
        for source_id in (goods_one, goods_one, goods_two, brewall, brewall):
            conn.execute("INSERT INTO map_labels(source_id) VALUES(?)", (source_id,))
        conn.commit()
        return SimpleNamespace(
            knowledge_writable=False,
            knowledge_path=Path("everquestie-knowledge.sqlite3"),
            state_path=Path("everquestie-user.sqlite3"),
            conn=conn,
            get_meta=lambda key, default="": "live" if key == "world_profile" else default,
        )

    def test_packaged_catalog_reports_sources_versions_and_label_counts(self):
        db = self._packaged_db()
        try:
            text = release_map_catalog_text(db)
            self.assertIn("Release map catalog:", text)
            self.assertIn("Goods 2026-08-17: 2 indexed map file(s), 3 indexed label(s)", text)
            self.assertIn("Brewall 2026-08-16: 1 indexed map file(s), 2 indexed label(s)", text)
            self.assertIn("Total indexed labels: 5", text)
        finally:
            db.conn.close()

    def test_builder_mode_hides_release_catalog_diagnostic(self):
        db = self._packaged_db()
        db.knowledge_writable = True
        try:
            self.assertEqual(release_map_catalog_text(db), "")
        finally:
            db.conn.close()

    def test_packaged_snapshot_without_catalog_schema_stays_quiet(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db = SimpleNamespace(knowledge_writable=False, conn=conn)
        try:
            self.assertEqual(release_map_catalog_text(db), "")
        finally:
            conn.close()

    def test_database_diagnostics_layer_appends_shipped_catalog_summary(self):
        from eqquest import app as app_module

        original = app_module.EverQuestieApp

        class FakeApp:
            def _build_ui(self):
                pass

            def _database_diagnostic_text(self):
                return "BASE DATABASE DIAGNOSTICS"

            def _world_profile_changed(self, event=None):
                pass

        db = self._packaged_db()
        try:
            app_module.EverQuestieApp = FakeApp
            install_runtime_mode_ui()
            fake = SimpleNamespace(db=db)
            text = app_module.EverQuestieApp._database_diagnostic_text(fake)
            self.assertIn("BASE DATABASE DIAGNOSTICS", text)
            self.assertIn("Release map catalog:", text)
            self.assertIn("Goods 2026-08-17", text)
            self.assertIn("Brewall 2026-08-16", text)
            self.assertIn("Total indexed labels: 5", text)
        finally:
            db.conn.close()
            app_module.EverQuestieApp = original


if __name__ == "__main__":
    unittest.main()
