from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.travel_requirements import travel_requirements_for_hop
from eqquest.travel_supplement import (
    TRAVEL_SUPPLEMENT_SOURCE_KIND,
    TravelSupplementImporter,
)
from eqquest.zone_travel import ZoneTravelCatalog


REPO_ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENT_ROOT = REPO_ROOT / "builder-data" / "travel-supplements"
MANIFEST = SUPPLEMENT_ROOT / "shattering-of-ro.json"
ODUS_MANIFEST = SUPPLEMENT_ROOT / "odus-hole-pok.json"
POK_MANIFEST = SUPPLEMENT_ROOT / "plane-of-knowledge-city-portals.json"


class ShatteringOfRoTravelManifestTests(unittest.TestCase):
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

    def test_manifest_compiles_reviewed_forward_only_sor_chain(self):
        legacy_west_freeport = self._zone("West Freeport", 9)
        current_west_freeport = self._zone("West Freeport", 383)
        arcstone = self._zone("Arcstone, Shattered Isles", 881)
        ruined_relic = self._zone("Ruined Relic", 882)
        vortex = self._zone("The Vortex", 883)
        labyrinth = self._zone("Labyrinth of Spite", 884)

        stats = TravelSupplementImporter(self.db).import_manifest(MANIFEST)
        self.assertEqual(stats.source_name, "EverQuestie approved Shattering of Ro travel evidence")
        self.assertEqual(stats.source_version, "2026-08-17")
        self.assertEqual(stats.edges, 4)
        self.assertEqual(stats.bidirectional_edges, 0)
        self.assertEqual(stats.requirements, 1)

        catalog = ZoneTravelCatalog(self.db)
        self.assertEqual(
            catalog.shortest_path(current_west_freeport, labyrinth),
            [current_west_freeport, arcstone, ruined_relic, vortex, labyrinth],
        )
        self.assertEqual(catalog.shortest_path(legacy_west_freeport, labyrinth), [])

        # The reviewed evidence is intentionally directional. Do not turn zone-line
        # observations into reciprocal travel without independent reverse evidence.
        self.assertEqual(catalog.shortest_path(labyrinth, vortex), [])
        self.assertEqual(catalog.shortest_path(vortex, ruined_relic), [])

        requirements = travel_requirements_for_hop(self.db, current_west_freeport, arcstone)
        self.assertEqual(len(requirements), 1)
        self.assertIn("Partisan of Candlemaker's Workshop", requirements[0].text)

        rows = self.db.conn.execute(
            """
            SELECT source_key,source_kind,source_version,data_json
            FROM zone_travel_edges
            WHERE source_kind=?
            ORDER BY source_key
            """,
            (TRAVEL_SUPPLEMENT_SOURCE_KIND,),
        ).fetchall()
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            {row["source_key"] for row in rows},
            {
                "sor-west-freeport-to-arcstone",
                "sor-arcstone-to-ruined-relic",
                "sor-ruined-relic-to-vortex",
                "sor-vortex-to-labyrinth-of-spite",
            },
        )
        self.assertTrue(all(row["source_version"] == "2026-08-17" for row in rows))
        start_row = next(row for row in rows if row["source_key"] == "sor-west-freeport-to-arcstone")
        self.assertEqual(json.loads(start_row["data_json"])["source_eq_zone_id"], "383")

    def test_reviewed_odus_and_pok_supplements_close_hole_to_labyrinth_chain(self):
        hole = self._zone("The Hole", 539)
        paineel = self._zone("Paineel", 75)
        legacy_toxxulia = self._zone("Toxxulia Forest", 38)
        current_toxxulia = self._zone("Toxxulia Forest", 414)
        pok = self._zone("The Plane of Knowledge", 202)
        self._zone("The Greater Faydark", 54)
        legacy_west_freeport = self._zone("West Freeport", 9)
        current_west_freeport = self._zone("West Freeport", 383)
        arcstone = self._zone("Arcstone, Shattered Isles", 881)
        ruined_relic = self._zone("Ruined Relic", 882)
        vortex = self._zone("The Vortex", 883)
        labyrinth = self._zone("Labyrinth of Spite", 884)

        importer = TravelSupplementImporter(self.db)
        odus = importer.import_manifest(ODUS_MANIFEST)
        pok_stats = importer.import_manifest(POK_MANIFEST)
        sor = importer.import_manifest(MANIFEST)
        self.assertEqual((odus.edges, pok_stats.edges, sor.edges), (2, 3, 4))

        catalog = ZoneTravelCatalog(self.db)
        expected = [
            hole,
            paineel,
            current_toxxulia,
            pok,
            current_west_freeport,
            arcstone,
            ruined_relic,
            vortex,
            labyrinth,
        ]
        self.assertEqual(catalog.shortest_path(hole, labyrinth), expected)
        self.assertEqual(len(expected) - 1, 8)

        # Current-live client anchors must not leak the route into retired duplicate
        # identities merely because the display names are identical.
        self.assertEqual(catalog.shortest_path(hole, legacy_toxxulia), [])
        self.assertEqual(catalog.shortest_path(pok, legacy_west_freeport), [])

        # Only the official PoK portal is explicitly reciprocal in this bridge.
        self.assertEqual(catalog.shortest_path(current_toxxulia, pok), [current_toxxulia, pok])
        self.assertEqual(catalog.shortest_path(paineel, hole), [])
        self.assertEqual(catalog.shortest_path(current_toxxulia, paineel), [])


if __name__ == "__main__":
    unittest.main()
