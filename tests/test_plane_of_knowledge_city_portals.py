from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.travel_supplement import TravelSupplementImporter
from eqquest.zone_travel import ZoneTravelCatalog


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    REPO_ROOT
    / "builder-data"
    / "travel-supplements"
    / "plane-of-knowledge-city-portals.json"
)


class PlaneOfKnowledgeCityPortalManifestTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, number: int) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=str(number),
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )

    def test_official_west_freeport_portal_is_explicitly_bidirectional(self):
        pok = self._zone("The Plane of Knowledge", 202)
        west_freeport = self._zone("West Freeport", 9)

        stats = TravelSupplementImporter(self.db).import_manifest(MANIFEST)
        self.assertEqual(
            stats.source_name,
            "EverQuest official Plane of Knowledge city portal evidence",
        )
        self.assertEqual(stats.edges, 1)
        self.assertEqual(stats.bidirectional_edges, 1)
        self.assertEqual(stats.requirements, 0)

        catalog = ZoneTravelCatalog(self.db)
        self.assertEqual(catalog.shortest_path(pok, west_freeport), [pok, west_freeport])
        self.assertEqual(catalog.shortest_path(west_freeport, pok), [west_freeport, pok])

        rows = self.db.conn.execute(
            """
            SELECT source_key,source_name,source_version,evidence
            FROM zone_travel_edges
            WHERE source_name='EverQuest official Plane of Knowledge city portal evidence'
            ORDER BY source_entity_id,target_entity_id
            """
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["source_key"] == "pok-west-freeport-city-book" for row in rows))
        self.assertTrue(all("West Freeport" in row["evidence"] for row in rows))


if __name__ == "__main__":
    unittest.main()
