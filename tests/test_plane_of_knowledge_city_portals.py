from __future__ import annotations

import json
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

    def test_official_city_portals_pin_current_client_identities(self):
        pok = self._zone("The Plane of Knowledge", 202)
        greater_faydark = self._zone("The Greater Faydark", 54)
        legacy_west_freeport = self._zone("West Freeport", 9)
        current_west_freeport = self._zone("West Freeport", 383)
        legacy_toxxulia = self._zone("Toxxulia Forest", 38)
        current_toxxulia = self._zone("Toxxulia Forest", 414)

        stats = TravelSupplementImporter(self.db).import_manifest(MANIFEST)
        self.assertEqual(
            stats.source_name,
            "EverQuest official Plane of Knowledge city portal evidence",
        )
        self.assertEqual(stats.edges, 3)
        self.assertEqual(stats.bidirectional_edges, 3)
        self.assertEqual(stats.requirements, 0)

        catalog = ZoneTravelCatalog(self.db)
        self.assertEqual(
            catalog.shortest_path(pok, greater_faydark),
            [pok, greater_faydark],
        )
        self.assertEqual(
            catalog.shortest_path(greater_faydark, pok),
            [greater_faydark, pok],
        )
        self.assertEqual(
            catalog.shortest_path(pok, current_west_freeport),
            [pok, current_west_freeport],
        )
        self.assertEqual(
            catalog.shortest_path(current_west_freeport, pok),
            [current_west_freeport, pok],
        )
        self.assertEqual(
            catalog.shortest_path(pok, current_toxxulia),
            [pok, current_toxxulia],
        )
        self.assertEqual(
            catalog.shortest_path(current_toxxulia, pok),
            [current_toxxulia, pok],
        )
        self.assertEqual(catalog.shortest_path(pok, legacy_west_freeport), [])
        self.assertEqual(catalog.shortest_path(pok, legacy_toxxulia), [])

        rows = self.db.conn.execute(
            """
            SELECT source_zone_entity_id,target_zone_entity_id,bidirectional,
                   source_key,source_name,source_version,evidence,data_json
            FROM zone_travel_edges
            WHERE source_name='EverQuest official Plane of Knowledge city portal evidence'
            ORDER BY source_key
            """
        ).fetchall()
        self.assertEqual(len(rows), 3)
        by_key = {str(row["source_key"]): row for row in rows}

        faydark = by_key["pok-greater-faydark-city-book"]
        self.assertEqual(int(faydark["source_zone_entity_id"]), pok)
        self.assertEqual(int(faydark["target_zone_entity_id"]), greater_faydark)
        self.assertEqual(int(faydark["bidirectional"]), 1)
        self.assertIn("Greater Faydark (2)", faydark["evidence"])
        faydark_data = json.loads(faydark["data_json"])
        self.assertEqual(faydark_data["source_eq_zone_id"], "202")
        self.assertEqual(faydark_data["target_eq_zone_id"], "54")

        freeport = by_key["pok-west-freeport-city-book"]
        self.assertEqual(int(freeport["source_zone_entity_id"]), pok)
        self.assertEqual(int(freeport["target_zone_entity_id"]), current_west_freeport)
        self.assertEqual(int(freeport["bidirectional"]), 1)
        self.assertIn("West Freeport", freeport["evidence"])
        freeport_data = json.loads(freeport["data_json"])
        self.assertEqual(freeport_data["source_eq_zone_id"], "202")
        self.assertEqual(freeport_data["target_eq_zone_id"], "383")

        toxxulia = by_key["pok-toxxulia-city-book"]
        self.assertEqual(int(toxxulia["source_zone_entity_id"]), pok)
        self.assertEqual(int(toxxulia["target_zone_entity_id"]), current_toxxulia)
        self.assertEqual(int(toxxulia["bidirectional"]), 1)
        self.assertIn("Toxxula Forest", toxxulia["evidence"])
        toxxulia_data = json.loads(toxxulia["data_json"])
        self.assertEqual(toxxulia_data["source_eq_zone_id"], "202")
        self.assertEqual(toxxulia_data["target_eq_zone_id"], "414")


if __name__ == "__main__":
    unittest.main()
