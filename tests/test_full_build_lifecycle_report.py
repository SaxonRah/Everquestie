from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eqquest.db import Database


class FullBuildLifecycleReportTests(unittest.TestCase):
    def test_audit_cli_writes_plain_utf8_json_without_mutating_database(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            database = root / "knowledge.sqlite3"
            report = root / "nested" / "profile-lifecycle-audit.json"

            db = Database(database)
            try:
                db.upsert_entity(
                    kind="npc",
                    name="Lifecycle Fixture",
                    external_id="npc:lifecycle-fixture",
                    data={"expansion": "Original"},
                )
            finally:
                db.close()

            before = sha256(database.read_bytes()).hexdigest()
            tool = Path(__file__).resolve().parents[1] / "tools" / "audit_profile_lifecycle.py"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(tool),
                    str(database),
                    "--json",
                    "--output",
                    str(report),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.stdout, "")
            raw = report.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["entities_with_expansion_evidence"], 1)
            self.assertEqual(payload["p99_available_direct"], 1)
            self.assertEqual(sha256(database.read_bytes()).hexdigest(), before)
            self.assertFalse(Path(str(database) + "-wal").exists())
            self.assertFalse(Path(str(database) + "-shm").exists())

    def test_full_build_declares_and_writes_standard_lifecycle_report(self):
        script = (
            Path(__file__).resolve().parents[1] / "tools" / "build_full_knowledge.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '$LifecycleReport = Join-Path $ProjectRoot "build\\profile-lifecycle-audit.json"',
            script,
        )
        self.assertIn("python .\\tools\\audit_profile_lifecycle.py $SnapshotDb", script)
        self.assertIn("--output $LifecycleReport", script)
        self.assertIn("Profile lifecycle : $LifecycleReport", script)
        self.assertNotIn("Set-Content -Path $LifecycleReport", script)


if __name__ == "__main__":
    unittest.main()
