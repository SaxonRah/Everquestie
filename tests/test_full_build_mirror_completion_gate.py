from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
FULL_BUILD = REPO_ROOT / "tools" / "build_full_knowledge.ps1"


class FullBuildMirrorCompletionGateTests(unittest.TestCase):
    def test_full_build_audits_temporary_pages_before_confirmed_httrack_completion(self) -> None:
        text = FULL_BUILD.read_text(encoding="utf-8")
        temporary_audit = text.index("audit_allakhazam_temporary_pages.py")
        mirror_audit = text.index("audit_allakhazam_mirror.py")
        httrack_project = text.index("--httrack-project $AllakhazamProject", mirror_audit)
        require_complete = text.index("--require-complete", httrack_project)
        build = text.index("build_knowledge_db.py")

        self.assertLess(temporary_audit, mirror_audit)
        self.assertLess(mirror_audit, httrack_project)
        self.assertLess(httrack_project, require_complete)
        self.assertLess(require_complete, build)
        self.assertIn('$AllakhazamProject = "C:\\AllakhazamEverquest\\EQ_Allakhazam_DB"', text)
        self.assertIn('$AllakhazamMirror = Join-Path $AllakhazamProject "everquest.allakhazam.com"', text)
        self.assertIn('"Allakhazam HTTrack project"   = $AllakhazamProject', text)
        self.assertIn("allakhazam-temporary-page-audit.json", text)
        self.assertIn('$TemporaryAuditJson | Set-Content -Path $TemporaryPageAuditReport -Encoding utf8', text)
        self.assertIn('Assert-LastExitCode "Allakhazam temporary-page audit"', text)
        self.assertIn('Assert-LastExitCode "Allakhazam completed-mirror inventory audit"', text)

    def test_completion_gate_is_not_an_arbitrary_spell_count_or_recovery_gate(self) -> None:
        text = FULL_BUILD.read_text(encoding="utf-8")
        self.assertNotIn("spell_pages -eq 0", text)
        self.assertNotIn("spell_pages_with_expansion -eq 0", text)
        self.assertNotIn("recover_allakhazam_temporary_pages.py", text)
        self.assertIn("clean WinHTTrack cancellation", text)
        self.assertIn("hts-in_progress.lock", text)
        self.assertIn("hts-log.txt", text)
        self.assertIn("recovery is a", text)
        self.assertIn("separate explicit builder action", text)


if __name__ == "__main__":
    unittest.main()
