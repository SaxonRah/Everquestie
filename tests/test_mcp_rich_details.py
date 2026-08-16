from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from eqquest.db import Database
from eqquest.mcp_client import MCPError
from eqquest.sources.mcp_snapshot import (
    MCPLocalSnapshotCompiler,
    MCPSnapshotCapture,
    _detail_search_text,
    _detail_storage_payload,
)


class _FakeDetailProcess:
    def __init__(self, messages: list[dict], *, return_code: int = 0, stderr: str = ""):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("\n".join(json.dumps(x) for x in messages) + "\n")
        self.stderr = io.StringIO(stderr)
        self._return_code = return_code

    def wait(self) -> int:
        return self._return_code


class MCPRichDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.eq = root / "EverQuest"
        self.mcp = root / "everquest1-mcp"
        self.eq.mkdir()
        self.mcp.mkdir()
        self.db = Database(root / "knowledge.sqlite3")

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def capture(self) -> MCPSnapshotCapture:
        snapshot = {
            "timestamp": "2026-08-15T18:00:00Z",
            "eqPath": str(self.eq),
            "systems": {
                "spells": {
                    "count": 1,
                    "names": {"42": "Test Fire"},
                }
            },
        }
        return MCPSnapshotCapture(
            eq_path=self.eq,
            mcp_path=self.mcp,
            snapshot=snapshot,
            raw_json=json.dumps(snapshot, sort_keys=True),
            mcp_version="1.2.1",
            mcp_commit="abcdef0123456789",
        )

    @staticmethod
    def fake_messages() -> list[dict]:
        return [
            {
                "type": "system_start",
                "system": "spells",
                "kind": "spell",
                "getter": "getLocalSpell",
                "total": 1,
            },
            {
                "type": "record",
                "system": "spells",
                "kind": "spell",
                "external_id": "42",
                "name": "Test Fire",
                "getter": "getLocalSpell",
                "record": {
                    "id": "42",
                    "name": "Test Fire",
                    "mana": 125,
                    "castTime": 3000,
                    "resistType": "Fire",
                    "classes": {"Wizard": 12},
                    "effects": [
                        {"slot": 1, "spa": 0, "description": "Decrease Hit Points by 250"}
                    ],
                    "description": "A test direct-damage spell.",
                },
            },
            {
                "type": "system_done",
                "system": "spells",
                "kind": "spell",
                "imported": 1,
                "errors": 0,
                "total": 1,
            },
        ]

    def test_structured_record_is_persisted_with_mcp_provenance(self) -> None:
        capture = self.capture()
        compiler = MCPLocalSnapshotCompiler(self.db)
        result = compiler.import_capture(capture)
        fake = _FakeDetailProcess(self.fake_messages())
        status = SimpleNamespace(ready=True, node="node", summary=lambda: "ready")

        with patch("eqquest.sources.mcp_detail_records.mcp_status", return_value=status), patch(
            "eqquest.sources.mcp_snapshot.subprocess.Popen", return_value=fake
        ):
            compiler.import_details(capture, result)

        entity = self.db.entity_by_namespaced_external_id("eqmcp:spells", "42")
        self.assertIsNotNone(entity)
        entity_id = int(entity["id"])
        detail = self.db.entity_detail(entity_id)
        self.assertIsNotNone(detail)
        self.assertEqual("mcp-json", detail["detail_format"])
        payload = json.loads(detail["detail_json"])
        self.assertEqual(125, payload["mana"])
        self.assertEqual("Fire", payload["resistType"])
        self.assertEqual({"Wizard": 12}, payload["classes"])
        self.assertIn("Decrease Hit Points", detail["detail_text"])
        self.assertEqual(1, result.detail_imported_by_kind["spell"])
        self.assertEqual("2026-08-15T18:00:00Z", self.db.get_meta("eq_mcp_detail_last_compile"))

        raw = self.db.conn.execute(
            "SELECT * FROM mcp_detail_records WHERE system='spells' AND external_id='42'"
        ).fetchone()
        self.assertIsNotNone(raw)
        self.assertEqual(entity_id, int(raw["entity_id"]))
        self.assertEqual(125, json.loads(raw["detail_json"])["mana"])

        source = self.db.conn.execute(
            "SELECT * FROM source_pages WHERE id=?", (result.detail_source_page_id,)
        ).fetchone()
        self.assertEqual("mcp_local_details", source["source_kind"])
        self.assertEqual("structured-local-details-v1", source["source_key"])

    def test_many_zone_source_ids_survive_one_canonical_entity(self) -> None:
        snapshot = {
            "timestamp": "2026-08-15T18:00:00Z",
            "eqPath": str(self.eq),
            "systems": {
                "zones": {
                    "count": 2,
                    "names": {"1": "Shared Zone", "2": "Shared Zone"},
                }
            },
        }
        capture = MCPSnapshotCapture(
            eq_path=self.eq,
            mcp_path=self.mcp,
            snapshot=snapshot,
            raw_json=json.dumps(snapshot, sort_keys=True),
            mcp_version="1.2.1",
            mcp_commit="abcdef0123456789",
        )
        compiler = MCPLocalSnapshotCompiler(self.db)
        result = compiler.import_capture(capture)
        fake = _FakeDetailProcess(
            [
                {"type": "system_start", "system": "zones", "kind": "zone", "total": 2},
                {
                    "type": "record",
                    "system": "zones",
                    "kind": "zone",
                    "external_id": "1",
                    "name": "Shared Zone",
                    "getter": "getLocalZone",
                    "record": {"id": "1", "name": "Shared Zone", "shortName": "shared_a"},
                },
                {
                    "type": "record",
                    "system": "zones",
                    "kind": "zone",
                    "external_id": "2",
                    "name": "Shared Zone",
                    "getter": "getLocalZone",
                    "record": {"id": "2", "name": "Shared Zone", "shortName": "shared_b"},
                },
                {"type": "system_done", "system": "zones", "kind": "zone", "imported": 2, "errors": 0, "total": 2},
            ]
        )
        status = SimpleNamespace(ready=True, node="node", summary=lambda: "ready")

        with patch("eqquest.sources.mcp_detail_records.mcp_status", return_value=status), patch(
            "eqquest.sources.mcp_snapshot.subprocess.Popen", return_value=fake
        ):
            compiler.import_details(capture, result)

        first = self.db.entity_by_namespaced_external_id("eqmcp:zones", "1")
        second = self.db.entity_by_namespaced_external_id("eqmcp:zones", "2")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(int(first["id"]), int(second["id"]))
        entity_id = int(first["id"])

        self.assertEqual(2, result.detail_imported_by_kind["zone"])
        self.assertEqual(
            2,
            self.db.conn.execute(
                "SELECT COUNT(*) FROM mcp_detail_records WHERE kind='zone'"
            ).fetchone()[0],
        )
        self.assertEqual(
            1,
            self.db.conn.execute(
                "SELECT COUNT(*) FROM entity_details WHERE entity_id=?",
                (entity_id,),
            ).fetchone()[0],
        )
        external_ids = {
            str(row["external_id"])
            for row in self.db.conn.execute(
                "SELECT external_id FROM mcp_detail_records WHERE entity_id=? ORDER BY external_id",
                (entity_id,),
            ).fetchall()
        }
        self.assertEqual({"1", "2"}, external_ids)

    def test_identical_detail_snapshot_reuses_compiled_rows(self) -> None:
        capture = self.capture()
        compiler = MCPLocalSnapshotCompiler(self.db)
        first = compiler.import_capture(capture)
        fake = _FakeDetailProcess(self.fake_messages())
        status = SimpleNamespace(ready=True, node="node", summary=lambda: "ready")
        with patch("eqquest.sources.mcp_detail_records.mcp_status", return_value=status), patch(
            "eqquest.sources.mcp_snapshot.subprocess.Popen", return_value=fake
        ):
            compiler.import_details(capture, first)

        second = compiler.import_capture(capture)
        with patch(
            "eqquest.sources.mcp_snapshot.subprocess.Popen",
            side_effect=AssertionError("unchanged detail pass should not launch Node"),
        ):
            compiler.import_details(capture, second)

        self.assertTrue(second.details_unchanged)
        self.assertEqual(1, second.detail_imported_by_kind["spell"])

    def test_populated_system_with_no_rich_records_fails(self) -> None:
        capture = self.capture()
        compiler = MCPLocalSnapshotCompiler(self.db)
        result = compiler.import_capture(capture)
        fake = _FakeDetailProcess(
            [
                {"type": "system_start", "system": "spells", "kind": "spell", "total": 1},
                {
                    "type": "record_error",
                    "system": "spells",
                    "kind": "spell",
                    "external_id": "42",
                    "reason": "not_found",
                },
                {
                    "type": "system_done",
                    "system": "spells",
                    "kind": "spell",
                    "imported": 0,
                    "errors": 1,
                    "total": 1,
                },
            ]
        )
        status = SimpleNamespace(ready=True, node="node", summary=lambda: "ready")

        with patch("eqquest.sources.mcp_detail_records.mcp_status", return_value=status), patch(
            "eqquest.sources.mcp_snapshot.subprocess.Popen", return_value=fake
        ):
            with self.assertRaisesRegex(MCPError, "zero records"):
                compiler.import_details(capture, result)

        self.assertIsNone(
            self.db.conn.execute(
                "SELECT 1 FROM source_pages WHERE source_kind='mcp_local_details'"
            ).fetchone()
        )

    def test_missing_upstream_getter_fails_full_detail_pass(self) -> None:
        capture = self.capture()
        compiler = MCPLocalSnapshotCompiler(self.db)
        result = compiler.import_capture(capture)
        fake = _FakeDetailProcess(
            [{"type": "system_missing", "system": "spells", "kind": "spell"}]
        )
        status = SimpleNamespace(ready=True, node="node", summary=lambda: "ready")

        with patch("eqquest.sources.mcp_detail_records.mcp_status", return_value=status), patch(
            "eqquest.sources.mcp_snapshot.subprocess.Popen", return_value=fake
        ):
            with self.assertRaisesRegex(MCPError, "missing required rich-detail getter"):
                compiler.import_details(capture, result)

    def test_string_detail_is_wrapped_as_valid_json(self) -> None:
        payload, text = _detail_storage_payload("A lore story")
        self.assertEqual({"text": "A lore story"}, payload)
        self.assertEqual("A lore story", text)
        self.assertEqual({"text": "A lore story"}, json.loads(json.dumps(payload)))

    def test_detail_search_text_keeps_structured_fields_but_is_bounded(self) -> None:
        text = _detail_search_text(
            {
                "name": "Test Fire",
                "effects": [{"description": "Burn target"}],
                "large": "x" * 20000,
            },
            max_chars=256,
        )
        self.assertIn("name: Test Fire", text)
        self.assertIn("effects[0].description: Burn target", text)
        self.assertLessEqual(len(text), 256)


if __name__ == "__main__":
    unittest.main()
