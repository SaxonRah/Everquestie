from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from eqquest.db import Database
from eqquest.mcp_source_provenance import audit_mcp_source_provenance


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


class MCPSourceProvenanceTests(unittest.TestCase):
    def test_snapshot_commit_and_local_head_are_compared_without_gitlink(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            project = root / "project"
            mcp = project / "third_party" / "everquest1-mcp"
            mcp.mkdir(parents=True)

            _git(project, "init")
            _git(project, "config", "user.email", "test@example.com")
            _git(project, "config", "user.name", "Test")
            (project / "README.md").write_text("fixture\n", encoding="utf-8")
            _git(project, "add", "README.md")
            _git(project, "commit", "-m", "fixture")

            _git(mcp, "init")
            _git(mcp, "config", "user.email", "test@example.com")
            _git(mcp, "config", "user.name", "Test")
            (mcp / "package.json").write_text(
                json.dumps({"name": "everquest1-mcp", "version": "9.9.9"}),
                encoding="utf-8",
            )
            _git(mcp, "add", "package.json")
            _git(mcp, "commit", "-m", "mcp fixture")
            _git(mcp, "remote", "add", "origin", "https://github.com/ArtSabintsev/everquest1-mcp.git")
            mcp_commit = _git(mcp, "rev-parse", "HEAD")

            snapshot = root / "knowledge.sqlite3"
            db = Database(snapshot)
            try:
                db.set_meta("eq_mcp_commit", mcp_commit)
                db.set_meta("eq_mcp_version", "9.9.9")
            finally:
                db.close()

            report = audit_mcp_source_provenance(snapshot, project_root=project)

            self.assertEqual(report.snapshot_mcp_commit, mcp_commit)
            self.assertEqual(report.local_mcp_commit, mcp_commit)
            self.assertTrue(report.local_matches_snapshot)
            self.assertFalse(report.parent_gitlink_present)
            self.assertIsNone(report.gitlink_matches_snapshot)
            self.assertTrue(report.expected_remote_matches_local)
            self.assertEqual(
                report.reproducible_lock_state,
                "snapshot_records_commit_but_parent_has_no_gitlink",
            )


if __name__ == "__main__":
    unittest.main()
