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
            source_name=("Allakhazam" if kind == "local_mirror" else "Audit Source"),
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
            name="Synthetic MCP Spell",
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
        self.db.upsert_entity(
            kind="zone",
            name="Taxonomy Zone",
            external_id="zone:taxonomy",
            source_page_id=npc_source,
            data={"expansion": "Antonica"},
        )

    def test_summary_counts_reviewed_evidence_and_rejected_candidates(self):
        self._build_fixture()

        summary = profile_lifecycle_audit(self.db)
        by_kind = {row.kind: row for row in summary.by_kind}

        self.assertEqual(summary.profile_id, "p99")
        self.assertEqual(summary.expansion_cap, "velious")
        self.assertEqual(summary.expansion_cap_label, "Velious")
        self.assertEqual(summary.total_entities, 5)
        self.assertEqual(summary.entities_with_expansion_evidence, 3)
        self.assertEqual(summary.evidence_rows, 3)
        self.assertEqual(summary.rejected_lifecycle_candidates, 1)
        self.assertEqual(summary.entities_with_rejected_lifecycle_candidates, 1)
        self.assertEqual(summary.available_direct, 1)
        self.assertEqual(summary.blocked_direct, 1)
        self.assertEqual(summary.conflict, 0)
        self.assertEqual(summary.undetermined_direct, 1)
        # Legacy P99 properties remain exact aliases for existing build/report callers.
        self.assertEqual(summary.p99_available_direct, summary.available_direct)
        self.assertEqual(summary.p99_blocked_direct, summary.blocked_direct)
        self.assertEqual(summary.p99_conflict, summary.conflict)
        self.assertEqual(summary.p99_undetermined_direct, summary.undetermined_direct)
        self.assertEqual(by_kind["npc"].with_expansion_evidence, 2)
        self.assertEqual(by_kind["spell"].with_expansion_evidence, 0)
        self.assertEqual(by_kind["item"].with_expansion_evidence, 0)
        self.assertEqual(by_kind["zone"].profile_undetermined, 1)
        self.assertEqual(by_kind["zone"].p99_undetermined, 1)
        self.assertIn(("local_mirror", 3), summary.by_source_kind)
        self.assertIn(("mcp_local_details", 1), summary.by_rejected_source_kind)
        self.assertTrue(
            any("MCP rich-detail" in reason and count == 1 for reason, count in summary.by_rejected_reason)
        )
        self.assertIn(("Antonica", 1), summary.by_unclassified_expansion)

        text = profile_lifecycle_audit_text(self.db)
        self.assertIn("Gameplay profile: Classic / P99-style (Velious cap) [p99]", text)
        self.assertIn("Expansion cap: Velious", text)
        self.assertIn("Entities with reviewed expansion/era evidence: 3", text)
        self.assertIn("Rejected lifecycle-looking candidates: 1 across 1 entities", text)
        self.assertIn(
            "P99 direct lifecycle decisions: available=1 blocked=1 conflict=0 undetermined=1",
            text,
        )
        self.assertIn("Rejected lifecycle-looking candidates by source kind:", text)
        self.assertIn("mcp_local_details: 1", text)
        self.assertIn("Unclassified reviewed expansion values:", text)
        self.assertIn("Antonica: 1", text)
        self.assertIn("field presence alone is not lifecycle evidence", text)
        self.assertIn("Locations, prose, names, dates, nested metadata, and fuzzy inference are excluded", text)

    def test_cli_json_is_read_only_machine_readable_and_backward_compatible(self):
        self._build_fixture()
        self.db.close()
        before = sha256(self.path.read_bytes()).hexdigest()
        tool = Path(__file__).resolve().parents[1] / "tools" / "audit_profile_lifecycle.py"

        completed = subprocess.run(
            [sys.executable, str(tool), str(self.path), "--profile", "p99", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["profile_id"], "p99")
        self.assertEqual(payload["expansion_cap"], "velious")
        self.assertEqual(payload["available_direct"], 1)
        self.assertEqual(payload["blocked_direct"], 1)
        self.assertEqual(payload["undetermined_direct"], 1)
        self.assertEqual(payload["p99_blocked_direct"], payload["blocked_direct"])
        self.assertEqual(payload["p99_undetermined_direct"], payload["undetermined_direct"])
        self.assertEqual(payload["rejected_lifecycle_candidates"], 1)
        self.assertEqual(payload["by_rejected_source_kind"][0]["source_kind"], "mcp_local_details")
        self.assertEqual(payload["by_unclassified_expansion"][0]["expansion"], "Antonica")
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertFalse(Path(str(self.path) + "-wal").exists())
        self.assertFalse(Path(str(self.path) + "-shm").exists())

        # tearDown tolerates an already closed handle.
        self.db = type("ClosedDB", (), {"close": lambda self: None})()

    def test_cli_rejects_non_expansion_capped_profile_read_only(self):
        self._build_fixture()
        self.db.close()
        before = sha256(self.path.read_bytes()).hexdigest()
        tool = Path(__file__).resolve().parents[1] / "tools" / "audit_profile_lifecycle.py"

        completed = subprocess.run(
            [sys.executable, str(tool), str(self.path), "--profile", "live", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("not an expansion-capped profile", completed.stderr)
        self.assertEqual(sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertFalse(Path(str(self.path) + "-wal").exists())
        self.assertFalse(Path(str(self.path) + "-shm").exists())

        self.db = type("ClosedDB", (), {"close": lambda self: None})()


if __name__ == "__main__":
    unittest.main()
