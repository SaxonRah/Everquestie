from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eqquest.db import Database
from eqquest.profile_lifecycle_audit import profile_lifecycle_audit, profile_lifecycle_audit_text


class ProfileLifecycleAuditTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.path = self.root / "knowledge.sqlite3"
        self.db = Database(self.path)

    def tearDown(self):
        try:
            self.db.close()
        except Exception:
            pass
        self.tempdir.cleanup()

    def _source(self, key: str, kind: str) -> int:
        return self.db.upsert_source_page(
            url=f"test://{key}",
            title=key,
            entity_type="multi",
            sha256=key,
            plain_text="",
            raw_html="",
            source_name="Audit Source",
            source_kind=kind,
            source_key=key,
        )

    def _build_fixture(self) -> None:
        npc_source = self._source("npc", "local_mirror")
        detail_source = self._source("spell", "mcp_local_details")
        self.db.upsert_entity(
            kind="npc",
            name="Classic NPC",
            external_id="npc:classic",
            source_page_id=npc_source,
            data={"expansion": "Classic"},
        )
        self.db.upsert_entity(
            kind="npc",
            name="Modern NPC",
            external_id="npc:modern",
            source_page_id=npc_source,
            data={"expansion": "The Serpent's Spine"},
        )
        spell = self.db.upsert_entity(
            kind="spell",
            name="PoP Spell",
            external_id="200",
            external_namespace="eqclient:spell",
        )
        self.db.upsert_entity_detail(
            spell,
            source_page_id=detail_source,
            detail_format="mcp-json",
            detail_json={"expansion": "Planes of Power"},
        )
        self.db.upsert_entity(
            kind="item",
            name="Unknown Item",
            external_id="item:unknown",
            data={"description": "mentions Velious but has no lifecycle field"},
        )

    def test_summary_counts_direct_evidence_by_kind_and_source(self):
        self._build_fixture()

        summary = profile_lifecycle_audit(self.db)
        by_kind = {row.kind: row for row in summary.by_kind}

        self.assertEqual(summary.total_entities, 4)
        self.assertEqual(summary.entities_with_expansion_evidence, 3)
        self.assertEqual(summary.evidence_rows, 3)
        self.assertEqual(summary.p99_available_direct, 1)
        self.assertEqual(summary.p99_blocked_direct, 2)
        self.assertEqual(summary.p99_conflict, 0)
        self.assertEqual(by_kind["npc"].with_expansion_evidence, 2)
        self.assertEqual(by_kind["spell"].with_expansion_evidence, 1)
        self.assertEqual(by_kind["item"].with_expansion_evidence, 0)
        self.assertIn(("local_mirror", 2), summary.by_source_kind)
        self.assertIn(("mcp_local_details", 1), summary.by_source_kind)

        text = profile_lifecycle_audit_text(self.db)
        self.assertIn("Entities with explicit expansion/era evidence: 3", text)
        self.assertIn("P99 direct lifecycle decisions: available=1 blocked=2 conflict=0", text)
        self.assertIn("Locations, prose, names, dates, and fuzzy inference are excluded", text)

    def test_cli_json_is_read_only_and_machine_readable(self):
        self._build_fixture()
        self.db.close()
        before = sha256(self.path.read_bytes()).hexdigest()
        tool = Path(__file__).resolve().parents[1] / "tools" / "audit_profile_lifecycle.py"

        completed = subprocess.run(
            [sys.executable, str(tool), str(self.path), "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["entities_with_expansion_evidence"], 3)
        self.assertEqual(payload["p99_blocked_direct"], 2)
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertFalse(Path(str(self.path) + "-wal").exists())
        self.assertFalse(Path(str(self.path) + "-shm").exists())

        # tearDown tolerates an already closed handle.
        self.db = type("ClosedDB", (), {"close": lambda self: None})()


if __name__ == "__main__":
    unittest.main()
