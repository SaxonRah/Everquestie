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
                source = db.upsert_source_page(
                    url="test://allakhazam/lifecycle-fixture",
                    title="Lifecycle Fixture",
                    entity_type="npc",
                    sha256="lifecycle-fixture",
                    plain_text="",
                    raw_html="",
                    source_name="Allakhazam",
                    source_kind="local_mirror",
                    source_key="npc:lifecycle-fixture",
                )
                db.upsert_entity(
                    kind="npc",
                    name="Lifecycle Fixture",
                    external_id="npc:lifecycle-fixture",
                    source_page_id=source,
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
            self.assertEqual(payload["rejected_lifecycle_candidates"], 0)
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
        self.assertIn("Profile lifecycle  : $LifecycleReport", script)
        self.assertNotIn("Set-Content -Path $LifecycleReport", script)

    def test_full_build_audits_mirror_before_database_construction_and_persists_report(self):
        script = (
            Path(__file__).resolve().parents[1] / "tools" / "build_full_knowledge.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '$MirrorAuditReport = Join-Path $ProjectRoot "build\\allakhazam-mirror-audit.json"',
            script,
        )
        audit_call = "python .\\tools\\audit_allakhazam_mirror.py"
        build_call = "python .\\tools\\build_knowledge_db.py"
        self.assertIn(audit_call, script)
        self.assertIn("--httrack-project $AllakhazamProject", script)
        self.assertIn("--output $MirrorAuditReport", script)
        self.assertIn("--require-complete", script)
        self.assertLess(script.index(audit_call), script.index(build_call))
        self.assertIn("Mirror inventory   : $MirrorAuditReport", script)
        self.assertIn(
            "Allakhazam mirror  : confirmed HTTrack complete + audited + included",
            script,
        )
        self.assertNotIn("spell_pages -eq 0", script)
        self.assertNotIn("spell_pages_with_expansion -eq 0", script)


if __name__ == "__main__":
    unittest.main()
