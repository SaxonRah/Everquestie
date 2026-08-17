from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.map_catalog import MapCatalog
from eqquest.route_guidance import build_route_guidance, route_guidance_text
from eqquest.travel_requirements import travel_requirements_for_hop
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


class GatedRouteGuidanceTests(unittest.TestCase):
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

    def _edge(
        self,
        source: int,
        target: int,
        index: int,
        *,
        kind: str = "zone_connection",
        bidirectional: bool = False,
        requirements=None,
        source_name: str = "Gated-route regression topology",
        source_kind: str = "test_confirmed_topology",
    ) -> None:
        payload = {}
        if requirements is not None:
            payload["travel_requirements"] = requirements
        ZoneTravelCatalog(self.db).add_provider_connection(
            source,
            target,
            connection_kind=kind,
            bidirectional=bidirectional,
            source_name=source_name,
            source_kind=source_kind,
            source_key=f"gated-route:{index}",
            source_version="test-v1",
            evidence=f"confirmed gated regression edge {index}",
            data=payload,
        )

    def test_the_hole_to_labyrinth_of_spite_can_cross_very_long_gated_route(self):
        """Stress the route architecture with the user's longest-path endpoint pair.

        Intermediate zones are intentionally synthetic. This proves that distance and
        gate metadata do not prevent graph traversal; it does not claim these are the
        live game's real intervening zones.
        """
        hole = self._zone("The Hole", 39)
        transit = [
            self._zone(f"Shattering Transit {index:03d}", 8000 + index)
            for index in range(1, 96)
        ]
        spite = self._zone("Labyrinth of Spite", 9999)
        path = [hole, *transit, spite]

        gates = {
            5: [{"kind": "level", "minimum_level": 55}],
            30: [
                {
                    "kind": "npc_interaction",
                    "text": "Speak to the gatekeeper and choose the transit dialogue option",
                }
            ],
            60: [
                {
                    "kind": "item",
                    "item_name": "Transit Seal",
                }
            ],
            90: [
                {
                    "kind": "barrier_interaction",
                    "text": "Activate the barrier object before crossing",
                }
            ],
        }
        for index, (source, target) in enumerate(zip(path, path[1:]), start=1):
            self._edge(source, target, index, requirements=gates.get(index))

        shortest = ZoneTravelCatalog(self.db).shortest_path(hole, spite)
        self.assertEqual(shortest, path)
        self.assertEqual(len(shortest) - 1, 96)

        guidance = build_route_guidance(self.db, "The Hole", "Labyrinth of Spite")
        self.assertTrue(guidance.ok)
        self.assertEqual(len(guidance.hops), 96)
        self.assertEqual(guidance.gated_hop_count, 4)
        self.assertEqual(guidance.requirement_count, 4)

        text = route_guidance_text(self.db, guidance)
        self.assertIn("Route: The Hole → Labyrinth of Spite", text)
        self.assertIn("Confirmed hops: 96", text)
        self.assertIn("Transitions with requirements: 4", text)
        self.assertIn("Minimum level 55", text)
        self.assertIn("gatekeeper", text)
        self.assertIn("Transit Seal", text)
        self.assertIn("Activate the barrier object", text)

    def test_faydwer_to_deep_odus_can_mix_boat_portal_npc_and_barrier_transitions(self):
        faydwer = self._zone("Greater Faydark", 54)
        dock = self._zone("Faydwer Departure", 8101)
        ocean = self._zone("Ocean Transit", 8102)
        odus = self._zone("Odus Landing", 8103)
        transfer = self._zone("Odus Transfer", 8104)
        paineel = self._zone("Paineel", 75)
        hole = self._zone("The Hole", 39)

        self._edge(faydwer, dock, 1, kind="zone_line")
        self._edge(
            dock,
            ocean,
            2,
            kind="boat",
            requirements=[{"kind": "interaction", "text": "Board the intercontinental boat"}],
        )
        self._edge(ocean, odus, 3, kind="zone_line")
        self._edge(
            odus,
            transfer,
            4,
            kind="npc_teleport",
            requirements=[
                {
                    "kind": "npc_interaction",
                    "npc_name": "Odus Transit NPC",
                    "action": "Speak to",
                }
            ],
        )
        self._edge(
            transfer,
            paineel,
            5,
            kind="portal",
            requirements=[{"kind": "interaction", "text": "Use the destination portal"}],
        )
        self._edge(
            paineel,
            hole,
            6,
            kind="barrier",
            requirements=[{"kind": "item", "item_name": "Entrance Key"}],
        )

        guidance = build_route_guidance(self.db, "Greater Faydark", "The Hole")
        self.assertTrue(guidance.ok)
        self.assertEqual(
            [hop.connection_kind for hop in guidance.hops],
            ["zone_line", "boat", "zone_line", "npc_teleport", "portal", "barrier"],
        )
        self.assertEqual(guidance.gated_hop_count, 4)
        text = route_guidance_text(self.db, guidance)
        self.assertIn("Board the intercontinental boat", text)
        self.assertIn("Speak to — Odus Transit NPC", text)
        self.assertIn("Use the destination portal", text)
        self.assertIn("Requires item: Entrance Key", text)

    def test_feldax_hive_to_paineel_and_hole_keeps_directional_gate_semantics(self):
        feldax = self._zone("Feldax Hive", 8200)
        crossroads = self._zone("Long-Distance Crossroads", 8201)
        paineel = self._zone("Paineel", 75)
        hole = self._zone("The Hole", 39)

        self._edge(feldax, crossroads, 1)
        self._edge(crossroads, paineel, 2)
        self._edge(
            paineel,
            hole,
            3,
            kind="sealed_barrier",
            bidirectional=True,
            requirements=[
                {
                    "kind": "barrier_interaction",
                    "direction": "forward",
                    "text": "Open the sealed barrier from the Paineel side",
                }
            ],
        )

        to_paineel = build_route_guidance(self.db, "Feldax Hive", "Paineel")
        self.assertTrue(to_paineel.ok)
        self.assertEqual(len(to_paineel.hops), 2)

        to_hole = build_route_guidance(self.db, "Feldax Hive", "The Hole")
        self.assertTrue(to_hole.ok)
        self.assertEqual(len(to_hole.hops), 3)
        self.assertEqual(to_hole.gated_hop_count, 1)
        self.assertIn("Open the sealed barrier", route_guidance_text(self.db, to_hole))

        reverse = build_route_guidance(self.db, "The Hole", "Paineel")
        self.assertTrue(reverse.ok)
        self.assertEqual(len(reverse.hops), 1)
        self.assertEqual(reverse.requirement_count, 0)
        self.assertNotIn("Open the sealed barrier", route_guidance_text(self.db, reverse))

    def test_requirement_evidence_is_not_hidden_by_coordinate_rich_map_edge(self):
        source = self._zone("Requirement Source", 8300)
        target = self._zone("Requirement Target", 8301)

        maps_root = self.root / "maps"
        maps_root.mkdir(exist_ok=True)
        (maps_root / "requirementsource.txt").write_text(
            "P -123,-456,7,255,0,0,2,Portal_to_Requirement_Target\n",
            encoding="utf-8",
        )
        maps = MapCatalog(self.db)
        maps.index_root(maps_root, source_name="Map pack", source_version="test-v1")
        ZoneMapCatalog(self.db).reconcile(source_name="Map pack")
        maps.reconcile_all(force=True)
        map_stats = ZoneTravelCatalog(self.db).reconcile_from_maps(source_name="Map pack")
        self.assertEqual(map_stats.linked, 1)
        map_edge = self.db.conn.execute(
            """
            SELECT label_id FROM zone_travel_edges
            WHERE source_kind='map_label' AND source_zone_entity_id=? AND target_zone_entity_id=?
            """,
            (source, target),
        ).fetchone()
        self.assertIsNotNone(map_edge)
        self.assertIsNotNone(map_edge["label_id"])

        self._edge(
            source,
            target,
            2,
            kind="portal",
            source_name="Allakhazam",
            source_kind="provider_zone_relationship",
            requirements=[
                {
                    "kind": "npc_interaction",
                    "text": "Tell the portal NPC you are ready",
                }
            ],
        )

        guidance = build_route_guidance(self.db, "Requirement Source", "Requirement Target")
        self.assertTrue(guidance.ok)
        self.assertEqual(len(guidance.hops), 1)
        hop = guidance.hops[0]
        self.assertEqual(hop.evidence_source, "Map pack")
        self.assertEqual(hop.source_coordinate, (123.0, 456.0, 7.0))
        self.assertIsNotNone(hop.coordinate_source_record_id)
        self.assertEqual(len(hop.requirements), 1)
        self.assertEqual(hop.requirements[0].source_names, ("Allakhazam",))

        direct_requirements = travel_requirements_for_hop(self.db, source, target)
        self.assertEqual(len(direct_requirements), 1)
        text = route_guidance_text(self.db, guidance)
        self.assertIn("Tell the portal NPC you are ready", text)
        self.assertIn("source: Allakhazam", text)
        self.assertIn("source-zone /loc: 456.0, 123.0, 7.0", text)


if __name__ == "__main__":
    unittest.main()
