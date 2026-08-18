from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
FULL_BUILD = REPO_ROOT / "tools" / "build_full_knowledge.ps1"


class FullBuildMirrorCompletionGateTests(unittest.TestCase):
    def test_full_build_requires_completed_mirror_before_database_construction(self) -> None:
        text = FULL_BUILD.read_text(encoding="utf-8")
        audit = text.index("audit_allakhazam_mirror.py")
        require_complete = text.index("--require-complete", audit)
        build = text.index("build_knowledge_db.py")

        self.assertLess(audit, require_complete)
        self.assertLess(require_complete, build)
        self.assertIn('Assert-LastExitCode "Allakhazam completed-mirror inventory audit"', text)

    def test_completion_gate_is_not_an_arbitrary_spell_count_gate(self) -> None:
        text = FULL_BUILD.read_text(encoding="utf-8")
        self.assertNotIn("spell_pages -eq 0", text)
        self.assertNotIn("spell_pages_with_expansion -eq 0", text)
        self.assertIn(".tmp files are crawler-owned in-progress state", text)


if __name__ == "__main__":
    unittest.main()
