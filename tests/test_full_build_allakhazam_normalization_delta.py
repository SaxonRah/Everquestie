from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
FULL_BUILD = REPO_ROOT / "tools" / "build_full_knowledge.ps1"


class FullBuildAllakhazamNormalizationDeltaTests(unittest.TestCase):
    def test_full_build_reuses_prebuild_mirror_report_after_snapshot_finalization(self) -> None:
        text = FULL_BUILD.read_text(encoding="utf-8")
        mirror_audit = text.index("audit_allakhazam_mirror.py")
        require_complete = text.index("--require-complete", mirror_audit)
        build = text.index("build_knowledge_db.py", require_complete)
        delta = text.index("audit_allakhazam_normalization_delta.py", build)
        map_audit = text.index("audit_map_catalog.py", delta)

        self.assertLess(mirror_audit, require_complete)
        self.assertLess(require_complete, build)
        self.assertLess(build, delta)
        self.assertLess(delta, map_audit)

        delta_end = text.index(
            'Assert-LastExitCode "Allakhazam capture-to-normalization audit"',
            delta,
        )
        delta_block = text[delta:delta_end]
        self.assertIn("$MirrorAuditReport", delta_block)
        self.assertIn("$SnapshotDb", delta_block)
        self.assertIn("--output $AllakhazamNormalizationReport", delta_block)
        self.assertNotIn("$AllakhazamMirror", delta_block)

    def test_normalization_delta_remains_diagnostic_not_a_count_threshold(self) -> None:
        text = FULL_BUILD.read_text(encoding="utf-8")
        delta = text.index("audit_allakhazam_normalization_delta.py")
        next_section = text.index("# Map catalog completeness + portability gate", delta)
        delta_section = text[delta:next_section]

        self.assertNotIn("--require", delta_section)
        self.assertNotIn("captured_not_persisted -eq", delta_section)
        self.assertNotIn("persisted_not_normalized -eq", delta_section)
        self.assertIn("diagnostic coverage", text)


if __name__ == "__main__":
    unittest.main()
