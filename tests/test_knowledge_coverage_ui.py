import tempfile
import unittest
from pathlib import Path

from eqquest import app as app_module
from eqquest.db import Database
from eqquest.knowledge_coverage_ui import (
    _append_source_summary_coverage,
    diagnostic_text_with_coverage,
    install_knowledge_coverage_ui,
)


class _FakeText:
    def __init__(self, text: str = ""):
        self.text = text
        self.state = "disabled"

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]

    def get(self, _start, _end):
        return self.text

    def insert(self, _where, text):
        self.text += str(text)


class KnowledgeCoverageUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "coverage.sqlite3"
        self.db = Database(self.path)
        source_id = self.db.upsert_source_page(
            url="eqclient://coverage-ui",
            title="Coverage UI source",
            entity_type="skill_cap",
            sha256="coverage-ui",
            plain_text="",
            raw_html="",
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key="coverage-ui",
        )
        self.db.replace_skill_caps(source_id, [(1, 0, 1, 5)])

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_diagnostic_text_appends_read_only_coverage(self):
        text = diagnostic_text_with_coverage(self.db, "Base diagnostics")
        self.assertTrue(text.startswith("Base diagnostics\n\n"))
        self.assertIn("EverQuestie source normalization coverage", text)
        self.assertIn("EverQuest Client [local_game_files]", text)
        self.assertIn("rich details / support rows: 0 / 1", text)

    def test_source_summary_append_preserves_existing_text_and_disables_widget(self):
        widget = _FakeText("Existing source summary")
        app = type("FakeApp", (), {})()
        app.db = self.db
        app.source_summary_text = widget

        _append_source_summary_coverage(app)

        self.assertTrue(widget.text.startswith("Existing source summary\n\n"))
        self.assertIn("pages with normalized DB derivatives: 1 (100.0%)", widget.text)
        self.assertEqual(widget.state, "disabled")

    def test_installer_subclasses_current_app_without_replacing_base_behavior(self):
        original = app_module.EverQuestieApp

        class FakeBase:
            def _database_diagnostic_text(self):
                return "base"

            def _refresh_source_summary(self):
                self.base_refresh_called = True

        try:
            app_module.EverQuestieApp = FakeBase
            install_knowledge_coverage_ui()
            installed = app_module.EverQuestieApp
            self.assertTrue(issubclass(installed, FakeBase))
            instance = object.__new__(installed)
            instance.db = self.db
            instance.source_summary_text = _FakeText("base summary")
            self.assertIn(
                "EverQuestie source normalization coverage",
                instance._database_diagnostic_text(),
            )
            instance._refresh_source_summary()
            self.assertTrue(instance.base_refresh_called)
            self.assertIn(
                "EverQuestie source normalization coverage",
                instance.source_summary_text.text,
            )
        finally:
            app_module.EverQuestieApp = original


if __name__ == "__main__":
    unittest.main()
