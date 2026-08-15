from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.route_guidance import build_route_guidance, route_guidance_text
from eqquest.travel_connectivity import travel_connectivity_diagnostic, travel_connectivity_text
from eqquest.zone_travel import ZoneTravelCatalog


class LongRouteGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, number: int) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=str(number),
            external_namespace="eqclient:zone",
        )

    def _edge(self, source: int, target: int, index: int, *, bidirectional: bool = False) -> None:
        ZoneTravelCatalog(self.db).add_provider_connection(
            source,
            target,
            connection_kind="zone_connection",
            bidirectional=bidirectional,
            source_name="Long-route regression topology",
            source_kind="test_confirmed_topology",
            source_key=f"long-route:{index}",
            source_version="test-v1",
            evidence=f"confirmed regression edge {index}",
        )

    def test_stone_hive_to_north_freeport_can_span_many_confirmed_hops(self):
        stone = self._zone("The Stone Hive", 351)
        transit = [self._zone(f"Transit Zone {index:02d}", 1000 + index) for index in range(1, 25)]
        freeport = self._zone("North Freeport", 8)
        path = [stone, *transit, freeport]
        for index, (source, target) in enumerate(zip(path, path[1:]), start=1):
            self._edge(source, target, index)

        shortest = ZoneTravelCatalog(self.db).shortest_path(stone, freeport)
        self.assertEqual(shortest, path)
        self.assertEqual(len(shortest) - 1, 25)

        guidance = build_route_guidance(self.db, "The Stone Hive", "North Freeport")
        self.assertTrue(guidance.ok)
        self.assertEqual(len(guidance.hops), 25)
        self.assertEqual(guidance.route.path, tuple(path))
        text = route_guidance_text(self.db, guidance)
        self.assertIn("Route: The Stone Hive → North Freeport", text)
        self.assertIn("Confirmed hops: 25", text)
        self.assertIn("25. Transit Zone 24 → North Freeport", text)

    def test_long_route_uses_shortest_confirmed_chain_not_first_discovered_chain(self):
        stone = self._zone("The Stone Hive", 351)
        freeport = self._zone("North Freeport", 8)
        long_nodes = [self._zone(f"Long Detour {index:02d}", 2000 + index) for index in range(12)]
        short_a = self._zone("Short Connector A", 3001)
        short_b = self._zone("Short Connector B", 3002)

        long_path = [stone, *long_nodes, freeport]
        for index, (source, target) in enumerate(zip(long_path, long_path[1:]), start=1):
            self._edge(source, target, index)
        self._edge(stone, short_a, 100)
        self._edge(short_a, short_b, 101)
        self._edge(short_b, freeport, 102)

        shortest = ZoneTravelCatalog(self.db).shortest_path(stone, freeport)
        self.assertEqual(shortest, [stone, short_a, short_b, freeport])
        guidance = build_route_guidance(self.db, "The Stone Hive", "North Freeport")
        self.assertEqual(len(guidance.hops), 3)

    def test_disconnected_far_destination_reports_topology_coverage_gap(self):
        stone = self._zone("The Stone Hive", 351)
        local_a = self._zone("Stone Neighbor A", 4001)
        local_b = self._zone("Stone Neighbor B", 4002)
        freeport = self._zone("North Freeport", 8)
        freeport_neighbor = self._zone("Freeport Neighbor", 4003)
        self._edge(stone, local_a, 1)
        self._edge(local_a, local_b, 2)
        self._edge(freeport_neighbor, freeport, 3)

        guidance = build_route_guidance(self.db, "The Stone Hive", "North Freeport")
        self.assertFalse(guidance.ok)
        text = route_guidance_text(self.db, guidance)
        self.assertIn("Travel graph diagnostic:", text)
        self.assertIn("outside The Stone Hive's confirmed travel-graph component", text)
        self.assertIn("missing canonical zone binding", text)

        diagnostic = travel_connectivity_diagnostic(self.db, stone, freeport)
        self.assertFalse(diagnostic.target_in_weak_component)
        self.assertEqual(diagnostic.directed_reachable_count, 2)
        self.assertEqual(diagnostic.source_outgoing_count, 1)
        self.assertEqual(diagnostic.target_incoming_count, 1)

    def test_same_component_wrong_direction_is_not_silently_reversed(self):
        stone = self._zone("The Stone Hive", 351)
        middle = self._zone("One-way Middle", 5001)
        freeport = self._zone("North Freeport", 8)
        self._edge(stone, middle, 1)
        self._edge(middle, freeport, 2)

        reverse = build_route_guidance(self.db, "North Freeport", "The Stone Hive")
        self.assertFalse(reverse.ok)
        text = route_guidance_text(self.db, reverse)
        self.assertIn("same connected evidence component", text)
        self.assertIn("directionality currently blocks travel", text)
        self.assertIn("will not assume a reverse zone connection", text)

        diagnostic = travel_connectivity_diagnostic(self.db, freeport, stone)
        self.assertTrue(diagnostic.target_in_weak_component)
        self.assertFalse(diagnostic.target_in_directed_reachable_set)

    def test_explicit_two_way_evidence_allows_reverse_long_route(self):
        stone = self._zone("The Stone Hive", 351)
        a = self._zone("Two-way A", 6001)
        b = self._zone("Two-way B", 6002)
        freeport = self._zone("North Freeport", 8)
        nodes = [stone, a, b, freeport]
        for index, (source, target) in enumerate(zip(nodes, nodes[1:]), start=1):
            self._edge(source, target, index, bidirectional=True)

        reverse = ZoneTravelCatalog(self.db).shortest_path(freeport, stone)
        self.assertEqual(reverse, [freeport, b, a, stone])
        guidance = build_route_guidance(self.db, "North Freeport", "The Stone Hive")
        self.assertTrue(guidance.ok)
        self.assertEqual(len(guidance.hops), 3)
        self.assertTrue(all(hop.uses_reverse_evidence for hop in guidance.hops))


if __name__ == "__main__":
    unittest.main()
