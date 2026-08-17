from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.locations import where_text
from eqquest.world_entity_detail import knowledge_world_detail_lines


class LocationActionabilityLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")
        self.zone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.npc = self.db.upsert_entity(
            kind="npc",
            name="A Label Worker",
            external_id="npc:label-worker",
        )

    def tearDown(self) -> None:
        self.db.close()
        self.tempdir.cleanup()

    def _page(self) -> int:
        return self.db.upsert_source_page(
            url="https://everquest.allakhazam.com/db/npc.html?id=label-worker",
            title="A Label Worker",
            entity_type="npc",
            sha256="sha-label-worker",
            plain_text="A Label Worker",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key="npc:label-worker",
            source_version="label-test",
        )

    def _location(self, *, sourced: bool) -> None:
        self.db.add_location(
            self.npc,
            zone_entity_id=self.zone,
            y=12.0,
            x=34.0,
            z=5.0,
            label="known coordinate",
            source_page_id=self._page() if sourced else None,
            evidence="coordinate evidence",
        )

    def test_where_marks_unsourced_canonical_coordinate_evidence_only(self):
        self._location(sourced=False)

        text = where_text(self.db, self.npc, "The Stone Hive")

        self.assertIn("Y=12 X=34 Z=5", text)
        self.assertIn("evidence only: missing reviewed provenance", text)
        self.assertIn("not map-targetable", text)

    def test_where_does_not_warn_for_reviewed_coordinate(self):
        self._location(sourced=True)

        text = where_text(self.db, self.npc, "The Stone Hive")

        self.assertIn("Y=12 X=34 Z=5", text)
        self.assertNotIn("missing reviewed provenance", text)
        self.assertNotIn("evidence only", text)

    def test_knowledge_detail_marks_unsourced_canonical_coordinate_evidence_only(self):
        self._location(sourced=False)

        text = "\n".join(knowledge_world_detail_lines(self.db, self.npc))

        self.assertIn("/loc Y=12 X=34 Z=5", text)
        self.assertIn("evidence only: missing reviewed provenance", text)
        self.assertIn("not map-targetable", text)

    def test_knowledge_detail_does_not_warn_for_reviewed_coordinate(self):
        self._location(sourced=True)

        text = "\n".join(knowledge_world_detail_lines(self.db, self.npc))

        self.assertIn("/loc Y=12 X=34 Z=5", text)
        self.assertNotIn("missing reviewed provenance", text)
        self.assertNotIn("evidence only", text)


if __name__ == "__main__":
    unittest.main()
