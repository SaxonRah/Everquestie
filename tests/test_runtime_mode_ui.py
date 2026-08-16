import unittest
from pathlib import Path
from types import SimpleNamespace

from eqquest.runtime_mode_ui import database_mode_text


class RuntimeModeUiTests(unittest.TestCase):
    def test_packaged_mode_names_both_databases(self):
        db = SimpleNamespace(
            knowledge_writable=False,
            knowledge_path=Path(r"C:\Everquestie\dist\everquestie-knowledge.sqlite3"),
            state_path=Path(r"C:\Users\Player\.eqquest\everquestie-user.sqlite3"),
        )
        text = database_mode_text(db)
        self.assertIn("PACKAGED / IMMUTABLE", text)
        self.assertIn("everquestie-knowledge.sqlite3", text)
        self.assertIn("everquestie-user.sqlite3", text)

    def test_builder_mode_names_mutable_database(self):
        db = SimpleNamespace(
            knowledge_writable=True,
            path=Path(r"C:\Users\Player\.eqquest\eqquest.sqlite3"),
        )
        text = database_mode_text(db)
        self.assertIn("BUILDER / MUTABLE", text)
        self.assertIn("eqquest.sqlite3", text)


if __name__ == "__main__":
    unittest.main()
