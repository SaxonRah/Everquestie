from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_SCRIPT = REPO_ROOT / "tools" / "build_release.ps1"


class ReleasePackagingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.script = RELEASE_SCRIPT.read_text(encoding="utf-8")

    def test_release_stages_source_db_before_finalization(self):
        self.assertIn('stage_release_working_db.py', self.script)
        self.assertIn('$StagedWorkingDb = Join-Path $StagingRoot', self.script)
        self.assertIn('--input $WorkingDb', self.script)
        self.assertIn('--output $StagedWorkingDb', self.script)
        self.assertIn(
            '& $PythonCommand $FinalizeTool --input $StagedWorkingDb',
            self.script,
        )
        self.assertNotIn(
            '& $PythonCommand $FinalizeTool --input $WorkingDb',
            self.script,
        )

    def test_release_defaults_to_builder_workspace_not_legacy_runtime_db(self):
        self.assertIn('Join-Path (Join-Path $ProjectRoot "build") "working.sqlite3"', self.script)
        self.assertNotIn('Join-Path (Join-Path $HOME ".eqquest") "eqquest.sqlite3"', self.script)

    def test_publishable_release_has_route_acceptance_gate(self):
        self.assertIn('audit_route_acceptance.py', self.script)
        self.assertIn('--fail-unreachable', self.script)
        self.assertIn('Route acceptance failed', self.script)
        self.assertIn('approved_travel_supplements_compiled = $true', self.script)
        self.assertIn('approved_zone_aliases_compiled = $true', self.script)

    def test_publishable_release_audits_finalized_reviewed_inputs_before_other_gates(self):
        self.assertIn('audit_release_inputs.py', self.script)
        self.assertIn('$ReleaseInputAuditTool $Snapshot --require-release-inputs', self.script)
        self.assertIn('Reviewed release-input audit failed', self.script)
        self.assertIn('reviewed_release_inputs_verified = $true', self.script)
        self.assertNotIn('SkipReleaseInputAudit', self.script)

        finalize = self.script.index('$FinalizeTool --input $StagedWorkingDb')
        reviewed = self.script.index('$ReleaseInputAuditTool $Snapshot --require-release-inputs')
        route = self.script.index('$RouteAuditTool $Snapshot --full-paths --fail-unreachable')
        tests = self.script.index('-m unittest discover -s tests -v')
        windows = self.script.index('$WindowsBuilder @BuilderParams')
        self.assertLess(finalize, reviewed)
        self.assertLess(reviewed, route)
        self.assertLess(reviewed, tests)
        self.assertLess(reviewed, windows)

    def test_release_compiles_reviewed_zone_aliases_before_finalization(self):
        self.assertIn('builder-data\\zone-aliases', self.script)
        self.assertIn('--zone-alias-dir $ApprovedZoneAliasDir', self.script)
        self.assertIn('approved zone aliases + travel supplements', self.script)


if __name__ == "__main__":
    unittest.main()
