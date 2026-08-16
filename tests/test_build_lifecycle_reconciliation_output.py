from pathlib import Path
import unittest


class BuildLifecycleReconciliationOutputTests(unittest.TestCase):
    def test_build_cli_surfaces_existing_spell_lifecycle_reconciliation_counters(self):
        source = (
            Path(__file__).resolve().parents[1] / "tools" / "build_knowledge_db.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"spell lifecycle reconciliation: "', source)
        self.assertIn("report.snapshot.lifecycle_reconciliation.items()", source)
        self.assertIn('"provider zone reconciliation: "', source)
        self.assertLess(
            source.index('"spell lifecycle reconciliation: "'),
            source.index('"provider zone reconciliation: "'),
        )


if __name__ == "__main__":
    unittest.main()
