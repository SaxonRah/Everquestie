import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database
from eqquest.vendor import REL_SELLS, REL_TEACHES_SPELL, link_vendor_fact, vendor_section_lines


class VendorRelationshipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "vendor.sqlite3")
        self.npc = self.db.upsert_entity(kind="npc", name="A Spell Merchant", merge_by_name=True)
        self.spell = self.db.upsert_entity(kind="spell", name="Test Spell", merge_by_name=True)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_vendor_fact_is_forward_graph_edge_and_reverse_renders(self):
        link_vendor_fact(
            self.db,
            npc_entity_id=self.npc,
            target_entity_id=self.spell,
            relation=REL_SELLS,
            price="1 pp",
        )
        npc_text = "\n".join(vendor_section_lines(self.db, self.npc))
        spell_text = "\n".join(vendor_section_lines(self.db, self.spell))
        self.assertIn("Sells: [spell] Test Spell", npc_text)
        self.assertIn("price 1 pp", npc_text)
        self.assertIn("Sold by: [npc] A Spell Merchant", spell_text)

    def test_trainer_relation_is_supported(self):
        link_vendor_fact(
            self.db,
            npc_entity_id=self.npc,
            target_entity_id=self.spell,
            relation=REL_TEACHES_SPELL,
        )
        text = "\n".join(vendor_section_lines(self.db, self.npc))
        self.assertIn("Teaches spell", text)


if __name__ == "__main__":
    unittest.main()
