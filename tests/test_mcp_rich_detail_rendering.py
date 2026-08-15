from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge import entity_detail_text


class MCPRichDetailRenderingTests(unittest.TestCase):
    def test_spell_rich_json_renders_gameplay_fields_in_normal_knowledge_detail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "knowledge.sqlite3")
            source_id = db.upsert_source_page(
                url="eqclient+mcp://structured-local-details",
                title="EverQuest structured local records via everquest1-mcp",
                entity_type="multi",
                sha256="detail-test",
                plain_text="{}",
                raw_html="",
                source_name="EverQuest Client via everquest1-mcp",
                source_kind="mcp_local_details",
                source_key="structured-local-details-v1",
            )
            spell_id = db.upsert_entity(
                kind="spell",
                name="Test Fire",
                source_page_id=source_id,
                source_url="eqclient+mcp://save_data_snapshot",
                external_id="42",
                external_namespace="eqclient:spell",
            )
            db.add_external_id(spell_id, "eqmcp:spells", "42", source_page_id=source_id)
            db.upsert_entity_detail(
                spell_id,
                source_page_id=source_id,
                detail_format="mcp-json",
                detail_text="mana: 125",
                detail_json={
                    "id": "42",
                    "name": "Test Fire",
                    "mana": 125,
                    "castTime": 3000,
                    "recastTime": 1500,
                    "resistType": "Fire",
                    "targetType": "Single",
                    "classes": {"Wizard": 12},
                    "effects": [
                        {"description": "Decrease Hit Points by 250"},
                    ],
                    "description": "A test direct-damage spell.",
                },
            )

            text = entity_detail_text(db, spell_id)
            db.close()

        self.assertIn("Spell mechanics (installed EverQuest client):", text)
        self.assertIn("Mana: 125", text)
        self.assertIn("Cast time: 3 s", text)
        self.assertIn("Recast: 1.5 s", text)
        self.assertIn("Target: Single", text)
        self.assertIn("Resist: Fire", text)
        self.assertIn("Wizard: 12", text)
        self.assertIn("Decrease Hit Points by 250", text)
        self.assertIn("A test direct-damage spell.", text)


if __name__ == "__main__":
    unittest.main()
