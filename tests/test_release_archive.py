from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from eqquest.release_archive import audit_release_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_TOOL = REPO_ROOT / "tools" / "verify_release_archive.py"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReleaseArchiveAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = self.root / "EverQuestie-0.99-windows.zip"
        self.source_knowledge = self.root / "everquestie-knowledge.sqlite3"
        self.knowledge_bytes = b"SQLite format 3\x00reviewed-release-knowledge"
        self.exe_bytes = b"MZ\x90\x00EverQuestie synthetic executable"
        self.source_knowledge.write_bytes(self.knowledge_bytes)

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest(self, layout: str) -> dict:
        one_file = layout == "one-file"
        return {
            "product": "EverQuestie",
            "release_version": "0.99",
            "built_at_utc": "2026-08-17T10:00:00Z",
            "layout": layout,
            "executable": {
                "path": "EverQuestie.exe" if one_file else "EverQuestie/EverQuestie.exe",
                "sha256": _sha(self.exe_bytes),
                "bytes": len(self.exe_bytes),
            },
            "knowledge": {
                "path": (
                    "embedded:everquestie-knowledge.sqlite3"
                    if one_file
                    else "EverQuestie/everquestie-knowledge.sqlite3"
                ),
                "filename": "everquestie-knowledge.sqlite3",
                "snapshot_version": "0.99",
                "sha256": _sha(self.knowledge_bytes),
                "bytes": len(self.knowledge_bytes),
                "embedded": one_file,
                "immutable_runtime": True,
                "approved_zone_aliases_compiled": True,
                "approved_travel_supplements_compiled": True,
                "reviewed_release_inputs_verified": True,
                "packaging_integrity": (
                    "source-hash-stable-during-embed"
                    if one_file
                    else "byte-identical-copy"
                ),
                "route_acceptance_verified": True,
            },
            "user_state_included": False,
            "builder_database_included": False,
        }

    def _write_archive(
        self,
        *,
        layout: str = "one-folder",
        manifest: dict | None = None,
        knowledge_bytes: bytes | None = None,
        extra_members: dict[str, bytes] | None = None,
    ) -> None:
        payload = manifest or self._manifest(layout)
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if layout == "one-file":
                zf.writestr("EverQuestie.exe", self.exe_bytes)
                zf.writestr("release-manifest.json", json.dumps(payload))
            else:
                zf.writestr("EverQuestie/EverQuestie.exe", self.exe_bytes)
                zf.writestr(
                    "EverQuestie/everquestie-knowledge.sqlite3",
                    self.knowledge_bytes if knowledge_bytes is None else knowledge_bytes,
                )
                zf.writestr("EverQuestie/release-manifest.json", json.dumps(payload))
            for name, data in (extra_members or {}).items():
                zf.writestr(name, data)

    def test_one_folder_archive_matches_manifest_and_audited_source_read_only(self):
        self._write_archive()
        archive_before = self.archive.read_bytes()
        source_before = self.source_knowledge.read_bytes()

        audit = audit_release_archive(
            self.archive,
            source_knowledge=self.source_knowledge,
            expected_version="0.99",
            require_source_knowledge=True,
        )
        self.assertTrue(audit.ok, audit.errors)
        self.assertEqual(audit.status, "ok")
        self.assertEqual(audit.layout, "one-folder")
        self.assertEqual(audit.archive_files, 3)
        self.assertEqual(audit.knowledge_member, "EverQuestie/everquestie-knowledge.sqlite3")
        self.assertTrue(audit.source_knowledge_verified)
        self.assertEqual(self.archive.read_bytes(), archive_before)
        self.assertEqual(self.source_knowledge.read_bytes(), source_before)

    def test_one_file_archive_uses_narrow_embedded_integrity_claim(self):
        self._write_archive(layout="one-file")
        audit = audit_release_archive(
            self.archive,
            source_knowledge=self.source_knowledge,
            expected_version="0.99",
            require_source_knowledge=True,
        )
        self.assertTrue(audit.ok, audit.errors)
        self.assertEqual(audit.layout, "one-file")
        self.assertEqual(audit.archive_files, 2)
        self.assertEqual(audit.knowledge_member, "")
        self.assertTrue(audit.source_knowledge_verified)

    def test_tampered_archived_knowledge_fails_manifest_hash(self):
        self._write_archive(knowledge_bytes=b"tampered knowledge")
        audit = audit_release_archive(
            self.archive,
            source_knowledge=self.source_knowledge,
            require_source_knowledge=True,
        )
        self.assertFalse(audit.ok)
        self.assertTrue(
            any("archived knowledge sha256 does not match manifest" in error for error in audit.errors)
        )

    def test_source_snapshot_mismatch_fails_even_when_archive_is_internally_consistent(self):
        self._write_archive()
        self.source_knowledge.write_bytes(b"different source snapshot")
        audit = audit_release_archive(
            self.archive,
            source_knowledge=self.source_knowledge,
            require_source_knowledge=True,
        )
        self.assertFalse(audit.ok)
        self.assertTrue(
            any("source knowledge snapshot sha256" in error for error in audit.errors)
        )

    def test_extra_builder_or_user_sqlite_is_rejected(self):
        self._write_archive(
            extra_members={"EverQuestie/working-with-approved-data.sqlite3": b"builder state"}
        )
        audit = audit_release_archive(self.archive)
        self.assertFalse(audit.ok)
        self.assertTrue(
            any("exactly the declared knowledge SQLite DB" in error for error in audit.errors)
        )

    def test_case_colliding_archive_member_is_rejected(self):
        self._write_archive(
            extra_members={"everquestie/EVERQUESTIE.EXE": self.exe_bytes}
        )
        audit = audit_release_archive(self.archive)
        self.assertFalse(audit.ok)
        self.assertTrue(
            any("duplicate/case-colliding ZIP members" in error for error in audit.errors)
        )

    def test_one_file_cannot_claim_byte_identical_external_copy(self):
        manifest = self._manifest("one-file")
        manifest["knowledge"]["packaging_integrity"] = "byte-identical-copy"
        self._write_archive(layout="one-file", manifest=manifest)
        audit = audit_release_archive(self.archive)
        self.assertFalse(audit.ok)
        self.assertTrue(
            any("source-hash-stable-during-embed" in error for error in audit.errors)
        )

    def test_cli_json_publish_gate_requires_matching_source_and_version(self):
        self._write_archive()
        completed = subprocess.run(
            [
                sys.executable,
                str(VERIFY_TOOL),
                str(self.archive),
                "--source-knowledge",
                str(self.source_knowledge),
                "--require-source-knowledge",
                "--expected-version",
                "0.99",
                "--json",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["source_knowledge_verified"])

        wrong = subprocess.run(
            [
                sys.executable,
                str(VERIFY_TOOL),
                str(self.archive),
                "--source-knowledge",
                str(self.source_knowledge),
                "--require-source-knowledge",
                "--expected-version",
                "1.00",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(wrong.returncode, 2)
        self.assertIn("release version mismatch", wrong.stdout)


if __name__ == "__main__":
    unittest.main()
