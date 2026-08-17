from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.approved_travel_supplements import approved_travel_manifest_paths
from eqquest.approved_zone_aliases import approved_zone_alias_manifest_paths
from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.route_acceptance import (
    DEFAULT_ROUTE_ACCEPTANCE_CASES,
    evaluate_route_acceptance,
)
from eqquest.travel_supplement import TravelSupplementImporter
from eqquest.zone_alias_supplement import ZoneAliasSupplementImporter
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


REPO_ROOT = Path(__file__).resolve().parents[1]
TRAVEL_DIR = REPO_ROOT / "builder-data" / "travel-supplements"
ZONE_ALIAS_DIR = REPO_ROOT / "builder-data" / "zone-aliases"


class ReleaseRouteAcceptanceContractTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _client_zone(
        self,
        name: str,
        eq_zone_id: int,
        *,
        map_short_name: str = "",
    ) -> int:
        data = {"map_short_name": map_short_name} if map_short_name else None
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=str(eq_zone_id),
            external_namespace="eqclient:zone",
            merge_by_name=False,
            data=data,
        )

    def _plain_zone(self, name: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            merge_by_name=True,
        )

    def _seed_current_live_zone_identities(self) -> None:
        self._client_zone("The Hole", 39, map_short_name="hole")
        self._client_zone("Paineel", 75, map_short_name="paineel")
        self._client_zone("The Stonebrunt Mountains", 100, map_short_name="stonebrunt")
        self._client_zone("The Warrens", 101, map_short_name="warrens")
        self._client_zone("The Plane of Knowledge", 202, map_short_name="poknowledge")
        self._client_zone("West Freeport", 383)
        self._client_zone("Blightfire Moors", 395, map_short_name="moors")
        self._client_zone("Stone Hive", 396, map_short_name="stonehive")
        self._client_zone("Toxxulia Forest", 414, map_short_name="toxxulia")
        self._client_zone("The Greater Faydark", 54)
        self._client_zone("Labyrinth of Spite", 549)

        # These current-Live Shattering of Ro intermediates are consumed by exact
        # reviewed manifest names. Their numeric client IDs are not part of that
        # manifest's identity contract, so this release-shaped fixture does not invent
        # IDs merely to make the graph look more authoritative than its source data.
        self._plain_zone("Arcstone, Shattered Isles")
        self._plain_zone("Ruined Relic")
        self._plain_zone("The Vortex")

    def _write_brewall_source_shape(self) -> Path:
        maps = self.root / "Brewall's Maps"
        maps.mkdir()
        source_layers = {
            "paineel": [
                "P -698.0000,-937.0000,12.0000,255,0,0,3,to_The_Ruins_of_Old_Paineel",
            ],
            "stonebrunt": [
                "P -2919.0000,3724.0000,-39.0000,255,0,0,3,to_The_Warrens",
            ],
            "warrens": [
                "P 908.5728,-747.9071,-36.9988,255,0,0,3,to_Paineel",
            ],
            "toxxulia": [
                "P 202.1961,1996.6201,46.7359,255,0,0,3,to_Paineel",
            ],
            "stonehive": [
                "P 1183.0000,1648.0000,37.0000,255,0,0,3,to_Blightfire_Moors",
            ],
            "moors": [
                "P 3725.0000,518.0000,162.0000,255,0,0,3,to_Stone_Hive",
                "P -3341.0000,1211.0000,-23.1250,255,0,0,3,to_The_Plane_of_Knowledge_(Click_Book)",
            ],
        }
        for stem, lines in source_layers.items():
            (maps / f"{stem}.txt").write_text("\n", encoding="utf-8")
            (maps / f"{stem}_1.txt").write_text(
                "\n".join(lines) + "\n",
                encoding="utf-8",
            )
        return maps

    def test_repository_owned_evidence_satisfies_all_five_current_live_defaults(self):
        self._seed_current_live_zone_identities()

        alias_manifests = approved_zone_alias_manifest_paths(ZONE_ALIAS_DIR)
        self.assertGreaterEqual(len(alias_manifests), 1)
        alias_importer = ZoneAliasSupplementImporter(self.db)
        for manifest in alias_manifests:
            alias_importer.import_manifest(manifest)

        maps = self._write_brewall_source_shape()
        indexed = MapCatalog(self.db).index_root(
            maps,
            source_name="Brewall's Maps",
            source_version="release-contract-source-shape",
        )
        self.assertEqual(indexed.base_maps, 6)
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall's Maps")
        map_travel = ZoneTravelCatalog(self.db).reconcile_from_maps(
            source_name="Brewall's Maps"
        )
        self.assertEqual(map_travel.candidates, 7)
        self.assertEqual(map_travel.linked, 7)
        self.assertEqual(map_travel.ambiguous, 0)
        self.assertEqual(map_travel.unresolved, 0)

        travel_manifests = approved_travel_manifest_paths(TRAVEL_DIR)
        self.assertEqual(
            [path.name for path in travel_manifests],
            [
                "odus-hole-pok.json",
                "plane-of-knowledge-city-portals.json",
                "shattering-of-ro.json",
            ],
        )
        travel_importer = TravelSupplementImporter(self.db)
        for manifest in travel_manifests:
            travel_importer.import_manifest(manifest)

        summary = evaluate_route_acceptance(self.db, DEFAULT_ROUTE_ACCEPTANCE_CASES)
        self.assertEqual(summary.total, 5)
        self.assertEqual(summary.accepted, 5)
        self.assertEqual(summary.failed, 0)
        self.assertTrue(all(result.status == "reachable" for result in summary.results))

        paths = {
            (result.source.query, result.target.query): result.path_zone_names
            for result in summary.results
        }
        self.assertEqual(
            paths[("The Hole", "Labyrinth of Spite")],
            (
                "The Hole",
                "Paineel",
                "Toxxulia Forest",
                "The Plane of Knowledge",
                "West Freeport",
                "Arcstone, Shattered Isles",
                "Ruined Relic",
                "The Vortex",
                "Labyrinth of Spite",
            ),
        )
        self.assertEqual(
            paths[("Paineel", "The Hole")],
            ("Paineel", "The Hole"),
        )
        self.assertEqual(
            paths[("Stonebrunt Mountains", "Paineel")],
            ("The Stonebrunt Mountains", "The Warrens", "Paineel"),
        )
        self.assertEqual(
            paths[("Greater Faydark", "The Hole")],
            (
                "The Greater Faydark",
                "The Plane of Knowledge",
                "Toxxulia Forest",
                "Paineel",
                "The Hole",
            ),
        )
        self.assertEqual(
            paths[("Stone Hive", "West Freeport")],
            (
                "Stone Hive",
                "Blightfire Moors",
                "The Plane of Knowledge",
                "West Freeport",
            ),
        )


if __name__ == "__main__":
    unittest.main()
