from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


class MCPBuilderToolingTests(unittest.TestCase):
    def test_runtime_source_launcher_never_bootstraps_mcp(self):
        source_launcher = (TOOLS / "run_source_app.cmd").read_text(encoding="utf-8").casefold()
        legacy_launcher = (TOOLS / "run_with_submodule.cmd").read_text(encoding="utf-8").casefold()

        self.assertIn("everquestie.py", source_launcher)
        self.assertNotIn("setup_mcp", source_launcher)
        self.assertNotIn("npm", source_launcher)
        self.assertNotIn("everquest1-mcp", source_launcher)

        self.assertIn("run_source_app.cmd", legacy_launcher)
        self.assertNotIn("setup_mcp", legacy_launcher)
        self.assertNotIn("npm", legacy_launcher)
        self.assertNotIn("package.json", legacy_launcher)

    def test_legacy_setup_name_only_forwards_to_builder_source_setup(self):
        legacy = (TOOLS / "setup_mcp_submodule.ps1").read_text(encoding="utf-8").casefold()
        canonical = (TOOLS / "setup_mcp_builder_source.ps1").read_text(encoding="utf-8").casefold()

        self.assertIn("setup_mcp_builder_source.ps1", legacy)
        self.assertNotIn("git clone", legacy)
        self.assertNotIn("npm install", legacy)

        self.assertIn("everquest1-mcp.lock.json", canonical)
        self.assertIn("git clone", canonical)
        self.assertIn("npm install", canonical)
        self.assertIn("repository-locked builder source", canonical)
        self.assertNotIn("git submodule", canonical)

    def test_legacy_verifier_uses_repository_lock_verifier(self):
        legacy = (TOOLS / "verify_submodule.ps1").read_text(encoding="utf-8").casefold()
        self.assertIn("verify_mcp_builder_source.py", legacy)
        self.assertNotIn("rev-parse head", legacy)

    def test_lock_verifier_fails_read_only_when_builder_source_is_missing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            project = Path(tempdir)
            lock = project / "third_party" / "everquest1-mcp.lock.json"
            lock.parent.mkdir(parents=True)
            lock.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "name": "everquest1-mcp",
                        "repository": "https://github.com/ArtSabintsev/everquest1-mcp.git",
                        "commit": "bd8a423a255d866b23df6cecaa1d79bc67232154",
                        "package_version": "1.2.1",
                    }
                ),
                encoding="utf-8",
            )
            before = sorted(path.relative_to(project).as_posix() for path in project.rglob("*"))

            completed = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS / "verify_mcp_builder_source.py"),
                    "--project-root",
                    str(project),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            after = sorted(path.relative_to(project).as_posix() for path in project.rglob("*"))
            self.assertEqual(completed.returncode, 2)
            self.assertIn("Locked builder source: FAIL", completed.stdout)
            self.assertIn("checkout is missing", completed.stdout)
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
