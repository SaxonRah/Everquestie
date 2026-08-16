import unittest
from pathlib import Path
from types import SimpleNamespace

from eqquest.runtime_mode_ui import database_mode_text


class RuntimeModeUiTests(unittest.TestCase):
    def test_packaged_mode_names_both_databases_and_profile(self):
        db = SimpleNamespace(
            knowledge_writable=False,
            knowledge_path=Path(r"C:\Everquestie\dist\everquestie-knowledge.sqlite3"),
            state_path=Path(r"C:\Users\Player\.eqquest\everquestie-user.sqlite3"),
            get_meta=lambda key, default="": "p99" if key == "world_profile" else default,
        )
        text = database_mode_text(db)
        self.assertIn("PACKAGED / IMMUTABLE", text)
        self.assertIn("Server: Classic / P99-style (Velious cap)", text)
        self.assertIn("everquestie-knowledge.sqlite3", text)
        self.assertIn("everquestie-user.sqlite3", text)

    def test_builder_mode_names_mutable_database_and_default_profile(self):
        db = SimpleNamespace(
            knowledge_writable=True,
            path=Path(r"C:\Users\Player\.eqquest\eqquest.sqlite3"),
            get_meta=lambda key, default="": default,
        )
        text = database_mode_text(db)
        self.assertIn("BUILDER / MUTABLE", text)
        self.assertIn("Server: Live (default)", text)
        self.assertIn("eqquest.sqlite3", text)

    def test_diagnostics_degrade_cleanly_when_profile_storage_is_unavailable(self):
        db = SimpleNamespace(
            knowledge_writable=True,
            path=Path(r"C:\temp\working.sqlite3"),
        )
        text = database_mode_text(db)
        self.assertIn("Server: not reported", text)
        self.assertIn("working.sqlite3", text)


if __name__ == "__main__":
    unittest.main()
