from __future__ import annotations

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
MANIFEST = (
    REPO_ROOT
    / "builder-data"
    / "travel-supplements"
    / "shattering-of-ro.json"
)


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
        west_freeport = self._zone("West Freeport", 9)
        arcstone = self._zone("Arcstone, Shattered Isles", 881)
        ruined_relic = self._zone("Ruined Relic", 882)
        vortex = self._zone("The Vortex", 883)
        labyrinth = self._zone("Labyrinth of Spite", 884)

        stats = TravelSupplementImporter(self.db).import_manifest(MANIFEST)
        self.assertEqual(stats.source_name, "EverQuestie approved Shattering of Ro travel evidence")
        self.assertEqual(stats.source_version, "2026-08-15")
        self.assertEqual(stats.edges, 4)
        self.assertEqual(stats.bidirectional_edges, 0)
        self.assertEqual(stats.requirements, 1)

        catalog = ZoneTravelCatalog(self.db)
        self.assertEqual(
            catalog.shortest_path(west_freeport, labyrinth),
            [west_freeport, arcstone, ruined_relic, vortex, labyrinth],
        )

        # The reviewed evidence is intentionally directional. Do not turn zone-line
        # observations into reciprocal travel without independent reverse evidence.
        self.assertEqual(catalog.shortest_path(labyrinth, vortex), [])
        self.assertEqual(catalog.shortest_path(vortex, ruined_relic), [])

        requirements = travel_requirements_for_hop(self.db, west_freeport, arcstone)
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
        self.assertTrue(all(row["source_version"] == "2026-08-15" for row in rows))


if __name__ == "__main__":
    unittest.main()
