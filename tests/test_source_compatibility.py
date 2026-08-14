import tempfile
import unittest
from pathlib import Path

from eqquest.db import Database


class FutureSourceCompatibilityTests(unittest.TestCase):
    def test_future_allakhazam_identity_can_enrich_existing_entity(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "knowledge.sqlite3")
            try:
                client_source = db.upsert_source_page(
                    url="eqclient://Resources/ZoneNames.txt",
                    title="ZoneNames",
                    entity_type="zone",
                    sha256="client",
                    plain_text="Stone Hive",
                    raw_html="",
                    source_name="EverQuest Client",
                    source_kind="builder_input",
                    source_key="Resources/ZoneNames.txt",
                )
                entity_id = db.upsert_entity(
                    kind="zone",
                    name="Stone Hive",
                    source_page_id=client_source,
                    source_url="eqclient://Resources/ZoneNames.txt",
                    external_id="123",
                    external_namespace="eqclient:zone",
                    merge_by_name=True,
                )

                future_source = db.upsert_source_page(
                    url="https://everquest.allakhazam.com/db/zone.html?zstrat=456",
                    title="Stone Hive",
                    entity_type="zone",
                    sha256="future",
                    plain_text="future mirror evidence",
                    raw_html="<html></html>",
                    source_name="Allakhazam",
                    source_kind="builder_mirror",
                    source_key="zone:456",
                )
                db.link_entity_source(entity_id, future_source, role="evidence")
                db.add_external_id(
                    entity_id,
                    "allakhazam:zone",
                    "zone:456",
                    source_page_id=future_source,
                )

                self.assertEqual(
                    int(db.entity_by_namespaced_external_id("eqclient:zone", "123")["id"]),
                    entity_id,
                )
                self.assertEqual(
                    int(db.entity_by_namespaced_external_id("allakhazam:zone", "zone:456")["id"]),
                    entity_id,
                )
                self.assertEqual(
                    {row["source_name"] for row in db.sources_for_entity(entity_id)},
                    {"EverQuest Client", "Allakhazam"},
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
