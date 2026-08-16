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


def _write_lock(project: Path, *, commit: str, version: str = "9.9.9") -> None:
    lock = project / "third_party" / "everquest1-mcp.lock.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "everquest1-mcp",
                "repository": "https://github.com/ArtSabintsev/everquest1-mcp.git",
                "commit": commit,
                "package_version": version,
            }
        ),
        encoding="utf-8",
    )


class MCPSourceProvenanceTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path, str]:
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
        _git(
            mcp,
            "remote",
            "add",
            "origin",
            "https://github.com/ArtSabintsev/everquest1-mcp.git",
        )
        mcp_commit = _git(mcp, "rev-parse", "HEAD")

        snapshot = root / "knowledge.sqlite3"
        db = Database(snapshot)
        try:
            db.set_meta("eq_mcp_commit", mcp_commit)
            db.set_meta("eq_mcp_version", "9.9.9")
        finally:
            db.close()
        return project, mcp, snapshot, mcp_commit

    def test_repository_lock_makes_nested_checkout_reproducible_without_gitlink(self):
        with tempfile.TemporaryDirectory() as tempdir:
            project, _mcp, snapshot, mcp_commit = self._fixture(Path(tempdir))
            _write_lock(project, commit=mcp_commit)

            report = audit_mcp_source_provenance(snapshot, project_root=project)

            self.assertEqual(report.snapshot_mcp_commit, mcp_commit)
            self.assertEqual(report.local_mcp_commit, mcp_commit)
            self.assertTrue(report.repository_lock_present)
            self.assertTrue(report.repository_lock_valid)
            self.assertTrue(report.snapshot_matches_repository_lock)
            self.assertTrue(report.local_matches_repository_lock)
            self.assertTrue(report.local_version_matches_repository_lock)
            self.assertTrue(report.repository_lock_remote_is_approved)
            self.assertTrue(report.local_matches_snapshot)
            self.assertFalse(report.parent_gitlink_present)
            self.assertIsNone(report.gitlink_matches_snapshot)
            self.assertTrue(report.expected_remote_matches_local)
            self.assertEqual(report.reproducible_lock_state, "reproducibly_locked")

    def test_snapshot_mismatch_is_reported_before_local_match(self):
        with tempfile.TemporaryDirectory() as tempdir:
            project, _mcp, snapshot, mcp_commit = self._fixture(Path(tempdir))
            other_commit = "0" * 40
            self.assertNotEqual(other_commit, mcp_commit)
            _write_lock(project, commit=other_commit)

            report = audit_mcp_source_provenance(snapshot, project_root=project)

            self.assertTrue(report.repository_lock_valid)
            self.assertFalse(report.snapshot_matches_repository_lock)
            self.assertFalse(report.local_matches_repository_lock)
            self.assertEqual(
                report.reproducible_lock_state,
                "repository_lock_differs_from_snapshot",
            )


if __name__ == "__main__":
    unittest.main()
