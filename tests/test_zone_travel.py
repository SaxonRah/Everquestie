from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


class ZoneTravelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.maps = self.root / "maps"
        self.maps.mkdir()
        self.db = Database(self.root / "knowledge.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, stem: str | None = None) -> int:
        data = {"map_short_name": stem} if stem else None
        return self.db.upsert_entity(kind="zone", name=name, merge_by_name=True, data=data)

    def _map(self, stem: str, *labels: str) -> None:
        lines = []
        for index, label in enumerate(labels, start=1):
            lines.append(f"P {index * 10},{index * 20},3,255,0,0,2,{label}")
        (self.maps / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _compile_maps(self, source_name: str = "Brewall") -> None:
        MapCatalog(self.db).index_root(self.maps, source_name=source_name)
        ZoneMapCatalog(self.db).reconcile(source_name=source_name)

    def test_explicit_to_label_compiles_directed_canonical_edge(self):
        source = self._zone("Stone Hive", "stonehive")
        target = self._zone("Blightfire Moors", "blightfire")
        self._map("stonehive", "To_Blightfire_Moors", "Bank")
        self._compile_maps()

        stats = ZoneTravelCatalog(self.db).reconcile_from_maps(source_name="Brewall")
        self.assertEqual(stats.candidates, 1)
        self.assertEqual(stats.linked, 1)
        edge = ZoneTravelCatalog(self.db).edges_from(source)[0]
        self.assertEqual(edge.target_zone_entity_id, target)
        self.assertEqual(edge.connection_kind, "travel")
        self.assertFalse(edge.bidirectional)
        self.assertEqual(edge.evidence, "To Blightfire Moors")
        self.assertEqual(edge.x, -10.0)
        self.assertEqual(edge.y, -20.0)
        self.assertEqual(edge.z, 3.0)

    def test_ambiguous_destination_is_preserved_not_guessed(self):
        source = self._zone("West Freeport", "freportw")
        north = self._zone("North Qeynos")
        south = self._zone("South Qeynos")
        self.db.add_alias(north, "Qeynos", alias_type="provider_short_name")
        self.db.add_alias(south, "Qeynos", alias_type="provider_short_name")
        self._map("freportw", "Zone_to_Qeynos")
        self._compile_maps(source_name="Good")

        stats = ZoneTravelCatalog(self.db).reconcile_from_maps(source_name="Good")
        self.assertEqual(stats.candidates, 1)
        self.assertEqual(stats.ambiguous, 1)
        edges = ZoneTravelCatalog(self.db).edges_from(source, linked_only=False)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].status, "ambiguous")
        self.assertIsNone(edges[0].target_zone_entity_id)
        self.assertIn("2 canonical zones", edges[0].reason)

    def test_non_travel_zone_name_label_does_not_create_edge(self):
        self._zone("Stone Hive", "stonehive")
        self._zone("Blightfire Moors")
        self._map("stonehive", "Blightfire_Moors", "A_Guard")
        self._compile_maps()

        stats = ZoneTravelCatalog(self.db).reconcile_from_maps()
        self.assertEqual(stats.candidates, 0)
        self.assertEqual(stats.linked, 0)

    def test_later_provider_alias_resolves_existing_map_candidate(self):
        source = self._zone("The Nexus", "nexus")
        target = self._zone("The Plane of Knowledge")
        self._map("nexus", "Portal_To_PoK")
        self._compile_maps()
        catalog = ZoneTravelCatalog(self.db)

        first = catalog.reconcile_from_maps()
        self.assertEqual(first.unresolved, 1)
        self.db.add_alias(target, "PoK", alias_type="provider_short_name")
        second = catalog.reconcile_from_maps()
        self.assertEqual(second.linked, 1)
        edge = catalog.edges_from(source)[0]
        self.assertEqual(edge.target_zone_entity_id, target)
        self.assertEqual(edge.connection_kind, "portal")

    def test_provider_connections_share_route_graph_and_support_bidirectional_edges(self):
        a = self._zone("Zone A")
        b = self._zone("Zone B")
        c = self._zone("Zone C")
        catalog = ZoneTravelCatalog(self.db)
        catalog.add_provider_connection(
            a,
            b,
            connection_kind="zone_line",
            bidirectional=True,
            source_name="EQ Client Builder",
            source_kind="client_topology",
            source_key="A-B",
        )
        catalog.add_provider_connection(
            b,
            c,
            connection_kind="portal",
            source_name="Future Mirror",
            source_kind="provider",
            source_key="B-C",
        )

        self.assertEqual(catalog.shortest_path(a, c), [a, b, c])
        self.assertEqual(catalog.shortest_path(b, a), [b, a])
        self.assertEqual(catalog.shortest_path(c, a), [])

    def test_finalized_snapshot_exposes_read_only_topology(self):
        source = self._zone("Stone Hive", "stonehive")
        target = self._zone("Blightfire Moors", "blightfire")
        self._map("stonehive", "To_Blightfire_Moors")
        self._compile_maps()
        ZoneTravelCatalog(self.db).reconcile_from_maps()
        self.db.close()

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "knowledge.sqlite3",
            snapshot,
            snapshot_version="zone-travel-runtime-test",
        )
        runtime = RuntimeDatabase(snapshot, self.root / "everquestie-user.sqlite3")
        try:
            catalog = ZoneTravelCatalog(runtime)
            edges = catalog.edges_from(source)
            self.assertEqual(len(edges), 1)
            self.assertEqual(edges[0].target_zone_entity_id, target)
            self.assertEqual(catalog.shortest_path(source, target), [source, target])
            with self.assertRaisesRegex(RuntimeError, "builder-only"):
                catalog.reconcile_from_maps()
        finally:
            runtime.close()

        # Reopen a builder DB for tearDown after the explicit close above.
        self.db = Database(self.root / "knowledge.sqlite3")


if __name__ == "__main__":
    unittest.main()
