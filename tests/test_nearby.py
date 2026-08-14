from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.nearby import nearby_points, nearby_text
from eqquest.runtime import RuntimeDatabase
from eqquest.state import SessionState
from eqquest.travel import TravelFrame
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_travel import ZoneTravelCatalog


class NearbyNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.maps = self.root / "maps"
        self.maps.mkdir()
        self.working = self.root / "working.sqlite3"
        self.db = Database(self.working)

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _fixture(self) -> tuple[int, int, int, int]:
        zone = self.db.upsert_entity(
            kind="zone",
            name="Stone Hive",
            external_id="400",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "stonehive"},
        )
        target = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="401",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        incoming = self.db.upsert_entity(
            kind="zone",
            name="The Nexus",
            external_id="152",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        npc = self.db.upsert_entity(
            kind="npc",
            name="A Stone Worker",
            zone="Stone Hive",
            merge_by_name=True,
        )

        # Native map points become game (-X,-Y,Z). The worker is ~22.36 horizontal
        # units from /loc 0,0, while the travel point is exactly 50.
        (self.maps / "stonehive.txt").write_text(
            "\n".join(
                (
                    "P 10,20,3,255,0,0,2,A_Stone_Worker",
                    "P 30,40,5,255,0,0,2,To_Blightfire_Moors",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        maps = MapCatalog(self.db)
        maps.index_root(self.maps, source_name="Brewall", source_version="2026-08")
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        maps.reconcile_all(force=True)
        travel = ZoneTravelCatalog(self.db)
        stats = travel.reconcile_from_maps(source_name="Brewall")
        self.assertEqual(stats.linked, 1)

        # Provider coordinate for the same NPC: distinct evidence / possible spawn,
        # deliberately closer in X/Y but much higher Z.
        page = self.db.upsert_source_page(
            url="test://nearby-worker",
            title="Nearby worker",
            entity_type="npc",
            sha256="nearby-worker",
            plain_text="worker spawn",
            raw_html="",
            source_name="Fixture Provider",
            source_kind="fixture",
            source_key="npc:a-stone-worker",
            source_version="1",
        )
        self.db.add_location(
            npc,
            zone_entity_id=zone,
            x=3.0,
            y=4.0,
            z=120.0,
            label="upper spawn",
            source_page_id=page,
            evidence="provider coordinate",
        )

        # An incoming one-way portal is known topology. Give it an artificial source
        # coordinate to prove the nearby view does not project that coordinate into
        # Stone Hive where the edge cannot be used.
        travel.add_provider_connection(
            incoming,
            zone,
            connection_kind="portal",
            bidirectional=False,
            source_name="Topology Provider",
            source_kind="provider",
            source_key="nexus-to-stone-hive",
            evidence="one-way incoming portal",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=1,y=1,z=0 "
            "WHERE source_name='Topology Provider' AND source_key='nexus-to-stone-hive'"
        )
        self.db.conn.commit()
        return zone, target, incoming, npc

    def test_nearby_ranks_horizontal_distance_and_keeps_delta_z_separate(self):
        zone, target, incoming, npc = self._fixture()
        points, status = nearby_points(self.db, "400", (0.0, 0.0, 0.0), limit=20)
        self.assertEqual(status, "linked")
        self.assertEqual(len(points), 3)

        # Horizontal distance wins even though the closest provider point is 120 Z
        # above the player. We report that vertical separation rather than pretending
        # the 3D or walkable distance is known.
        self.assertEqual(points[0].point_type, "entity")
        self.assertEqual(points[0].entity_id, npc)
        self.assertEqual(points[0].source_name, "Fixture Provider")
        self.assertAlmostEqual(points[0].horizontal_distance, 5.0)
        self.assertAlmostEqual(points[0].vertical_delta or 0.0, 120.0)
        self.assertEqual((points[0].delta_x, points[0].delta_y), (3.0, 4.0))

        self.assertEqual(points[1].point_type, "entity")
        self.assertEqual(points[1].entity_id, npc)
        self.assertEqual(points[1].source_name, "Brewall")
        self.assertAlmostEqual(points[1].horizontal_distance, math.hypot(10, 20))
        self.assertEqual((points[1].x, points[1].y, points[1].z), (-10.0, -20.0, 3.0))

        self.assertEqual(points[2].point_type, "travel")
        self.assertEqual(points[2].neighbor_zone_entity_id, target)
        self.assertEqual(points[2].name, "Blightfire Moors")
        self.assertAlmostEqual(points[2].horizontal_distance, 50.0)
        self.assertEqual((points[2].x, points[2].y, points[2].z), (-30.0, -40.0, 5.0))

        # The Nexus edge has a coordinate, but it is incoming and one-way from the
        # current zone. Its source coordinate must never appear as a nearby exit here.
        self.assertNotIn(incoming, {point.neighbor_zone_entity_id for point in points})

    def test_radius_filters_by_horizontal_distance_only(self):
        self._fixture()
        points, status = nearby_points(
            self.db,
            "stonehive",
            (0.0, 0.0, 0.0),
            max_horizontal=25.0,
        )
        self.assertEqual(status, "linked")
        self.assertEqual(len(points), 2)
        self.assertEqual({point.point_type for point in points}, {"entity"})
        self.assertTrue(all(point.horizontal_distance <= 25.0 for point in points))

    def test_missing_player_location_does_not_guess(self):
        self._fixture()
        points, status = nearby_points(self.db, "Stone Hive", None)
        self.assertEqual(points, [])
        self.assertEqual(status, "location_unknown")
        text = nearby_text(self.db, "Stone Hive", None)
        self.assertIn("player /loc unknown", text)
        self.assertIn("needs an observed /loc", text)

    def test_session_zone_change_invalidates_previous_loc(self):
        state = SessionState(
            current_zone="Stone Hive",
            zone_source="log",
            last_location=(10.0, 20.0, 3.0),
        )
        changed = state.set_zone("Blightfire Moors", source="log", force=True)
        self.assertTrue(changed)
        self.assertEqual(state.current_zone, "Blightfire Moors")
        self.assertIsNone(state.last_location)

    def test_map_nearest_hands_game_space_to_map_owner(self):
        self._fixture()
        emitted: list[tuple] = []
        statuses: list[str] = []
        fake = SimpleNamespace(
            db=self.db,
            _live_current_zone=lambda: "Stone Hive",
            get_location=lambda: (0.0, 0.0, 0.0),
            on_map_target=lambda *args: emitted.append(args),
            status_var=SimpleNamespace(set=lambda value: statuses.append(str(value))),
            _nearby_map_label=TravelFrame._nearby_map_label,
        )

        TravelFrame.map_nearest(fake)
        self.assertEqual(len(emitted), 1)
        zone, x, y, z, label = emitted[0]
        self.assertEqual(zone, "Stone Hive")
        # The closest provider statement is already normalized game-space X/Y/Z.
        # Travel must not apply the native map sign reversal; the map owner does that.
        self.assertEqual((x, y, z), (3.0, 4.0, 120.0))
        self.assertEqual(label, "A Stone Worker [npc]")
        self.assertIn("The Map tab owns", statuses[-1])

    def test_ambiguous_zone_identity_does_not_rank_points(self):
        north = self.db.upsert_entity(kind="zone", name="North Freeport", merge_by_name=True)
        south = self.db.upsert_entity(kind="zone", name="South Freeport", merge_by_name=True)
        self.db.add_alias(north, "Freeport", alias_type="provider_alias")
        self.db.add_alias(south, "Freeport", alias_type="provider_alias")
        points, status = nearby_points(self.db, "Freeport", (0.0, 0.0, 0.0))
        self.assertEqual(points, [])
        self.assertEqual(status, "ambiguous")

    def test_text_marks_distance_as_non_pathfinding_and_sources_each_point(self):
        self._fixture()
        text = nearby_text(self.db, "Stone Hive", (0.0, 0.0, 0.0), limit=10)
        self.assertIn("straight-line horizontal X/Y", text)
        self.assertIn("not pathfinding", text)
        self.assertIn("[npc] A Stone Worker", text)
        self.assertIn("Fixture Provider 1", text)
        self.assertIn("Brewall 2026-08", text)
        self.assertIn("[travel:travel] → Blightfire Moors", text)
        self.assertIn("ΔZ +120.0", text)

    def test_finalized_runtime_ranks_same_points_read_only(self):
        zone, target, incoming, npc = self._fixture()
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.working,
            snapshot,
            snapshot_version="nearby-test",
        )

        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            points, status = nearby_points(runtime, "400", (0.0, 0.0, 0.0), limit=20)
            self.assertEqual(status, "linked")
            self.assertEqual(len(points), 3)
            self.assertEqual(points[0].entity_id, npc)
            self.assertEqual(points[-1].neighbor_zone_entity_id, target)
            self.assertNotIn(incoming, {point.neighbor_zone_entity_id for point in points})
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entities SET name='mutated' WHERE id=?", (zone,))
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
