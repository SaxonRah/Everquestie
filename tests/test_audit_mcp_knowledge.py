from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.sources.mcp_detail_records import (
    _ensure_detail_record_schema,
    _persist_detail_record,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_mcp_knowledge", ROOT / "tools" / "audit_mcp_knowledge.py"
)
assert SPEC is not None and SPEC.loader is not None
audit_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_module)


class MCPKnowledgeAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "knowledge.sqlite3"
        self.db = Database(self.path)

    def tearDown(self) -> None:
        self.db.close()
        self.tmp.cleanup()

    def _inventory_source(self) -> int:
        return self.db.upsert_source_page(
            url="eqclient+mcp://save_data_snapshot",
            title="inventory",
            entity_type="multi",
            sha256="inventory",
            plain_text="{}",
            raw_html="",
            source_name="EverQuest Client via everquest1-mcp",
            source_kind="mcp_local_snapshot",
            source_key="save_data_snapshot",
        )

    def _detail_source(self) -> int:
        return self.db.upsert_source_page(
            url="eqclient+mcp://structured-local-details",
            title="details",
            entity_type="multi",
            sha256="details",
            plain_text="{}",
            raw_html="",
            source_name="EverQuest Client via everquest1-mcp",
            source_kind="mcp_local_details",
            source_key="structured-local-details-v1",
        )

    def _persist_source_detail(
        self,
        *,
        details: int,
        entity_id: int,
        system: str,
        kind: str,
        external_id: str,
        payload: dict,
    ) -> None:
        _ensure_detail_record_schema(self.db)
        _persist_detail_record(
            self.db,
            source_page_id=details,
            system=system,
            kind=kind,
            external_id=external_id,
            entity_id=entity_id,
            name=str(payload.get("name") or ""),
            getter="test",
            detail_text=json.dumps(payload, sort_keys=True),
            detail_json=payload,
        )

    def test_require_details_passes_for_persisted_spell_detail(self) -> None:
        inventory = self._inventory_source()
        details = self._detail_source()
        entity_id = self.db.upsert_entity(
            kind="spell",
            name="Test Fire",
            source_page_id=inventory,
            source_url="eqclient+mcp://save_data_snapshot",
            external_id="42",
            external_namespace="eqclient:spell",
        )
        self.db.add_external_id(entity_id, "eqmcp:spells", "42", source_page_id=inventory)
        payload = {"id": 42, "name": "Test Fire", "mana": 100}
        self._persist_source_detail(
            details=details,
            entity_id=entity_id,
            system="spells",
            kind="spell",
            external_id="42",
            payload=payload,
        )
        self.db.upsert_entity_detail(
            entity_id,
            source_page_id=details,
            detail_format="mcp-json",
            detail_text="mana: 100",
            detail_json=payload,
        )
        self.db.set_meta("eq_mcp_detail_missing_systems", "[]")
        self.db.set_meta("eq_mcp_detail_errors", "{}")
        self.db.set_meta("eq_mcp_detail_counts", json.dumps({"spell": 1}))
        self.db.close()

        lines, errors = audit_module.audit(self.path, require_details=True)
        self.assertEqual([], errors)
        self.assertTrue(any("rich spell records: 1" in line for line in lines))
        self.assertTrue(any("inventory identities: 1" in line for line in lines))
        self.assertTrue(any("rich source records: 1" in line for line in lines))

        self.db = Database(self.path)

    def test_many_source_zone_ids_can_share_one_canonical_detail_entity(self) -> None:
        inventory = self._inventory_source()
        details = self._detail_source()
        entity_id = self.db.upsert_entity(
            kind="zone",
            name="Shared Zone",
            source_page_id=inventory,
            source_url="eqclient+mcp://save_data_snapshot",
            external_id="1",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self.db.add_external_id(entity_id, "eqmcp:zones", "1", source_page_id=inventory)
        self.db.add_external_id(entity_id, "eqmcp:zones", "2", source_page_id=inventory)

        first = {"id": "1", "name": "Shared Zone", "shortName": "shared_a"}
        second = {"id": "2", "name": "Shared Zone", "shortName": "shared_b"}
        self._persist_source_detail(
            details=details,
            entity_id=entity_id,
            system="zones",
            kind="zone",
            external_id="1",
            payload=first,
        )
        self._persist_source_detail(
            details=details,
            entity_id=entity_id,
            system="zones",
            kind="zone",
            external_id="2",
            payload=second,
        )
        self.db.upsert_entity_detail(
            entity_id,
            source_page_id=details,
            detail_format="mcp-json",
            detail_text="Shared Zone",
            detail_json=first,
        )
        self.db.set_meta("eq_mcp_detail_missing_systems", "[]")
        self.db.set_meta("eq_mcp_detail_errors", "{}")
        self.db.set_meta("eq_mcp_detail_counts", json.dumps({"zone": 2}))
        self.db.close()

        lines, errors = audit_module.audit(self.path, require_details=True)
        self.assertEqual([], errors)
        self.assertTrue(any("inventory identities: 2" in line for line in lines))
        self.assertTrue(any("canonical inventory entities: 1" in line for line in lines))
        self.assertTrue(any("rich source records: 2" in line for line in lines))
        self.assertTrue(any("canonical rich-detail entities: 1" in line for line in lines))
        self.assertTrue(any("canonical UI detail rows: 1" in line for line in lines))
        self.assertTrue(any("zone=+1" in line for line in lines))

        self.db = Database(self.path)

    def test_require_details_fails_for_inventory_only_database(self) -> None:
        inventory = self._inventory_source()
        entity_id = self.db.upsert_entity(
            kind="spell",
            name="Test Fire",
            source_page_id=inventory,
            source_url="eqclient+mcp://save_data_snapshot",
            external_id="42",
            external_namespace="eqclient:spell",
        )
        self.db.add_external_id(entity_id, "eqmcp:spells", "42", source_page_id=inventory)
        self.db.close()

        _lines, errors = audit_module.audit(self.path, require_details=True)
        self.assertIn("MCP rich-detail source is missing", errors)
        self.assertIn("MCP source-granular rich-detail record table is missing", errors)
        self.assertIn("spell inventory is populated but rich spell details are missing", errors)

        self.db = Database(self.path)


if __name__ == "__main__":
    unittest.main()
