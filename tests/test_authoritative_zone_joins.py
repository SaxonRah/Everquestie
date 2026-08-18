from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.route_guidance import build_route_guidance, next_hop_for_zone
from eqquest.runtime import RuntimeDatabase
from eqquest.travel import build_route_result
from eqquest.zone_authority import authoritative_zones_match, resolve_authoritative_zone
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_context import build_zone_context
from eqquest.zone_identity import ZoneIdentityIndex
from eqquest.zone_travel import ZoneTravelCatalog


class AuthoritativeZoneJoinTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, external_id: str, namespace: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=external_id,
            external_namespace=namespace,
            merge_by_name=False,
        )

    def _duplicate_zone(self, name: str, *, client_id: str, provider_id: str) -> tuple[int, int]:
        provider = self._zone(name, provider_id, "allakhazam:zone")
        client = self._zone(name, client_id, "eqclient:zone")
        return provider, client

    @staticmethod
    def _write_map(folder: Path, stem: str, *labels: str) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        lines = ["L 0,0,0,100,100,0,255,255,255"]
        for index, label in enumerate(labels or ("Test_Label",), start=1):
            lines.append(f"P {index * 10},{index * 20},3,255,0,0,2,{label}")
        path = folder / f"{stem}.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_strict_collision_is_retained_while_authoritative_join_prefers_client(self):
        provider, client = self._duplicate_zone(
            "Stone Hive",
            client_id="396",
            provider_id="884",
        )

        strict = ZoneIdentityIndex(self.db).resolve("Stone Hive")
        self.assertEqual(strict.status, "ambiguous")
        self.assertEqual({item.entity_id for item in strict.candidates}, {provider, client})

        chosen = resolve_authoritative_zone(self.db, "Stone Hive")
        self.assertEqual(chosen.status, "linked")
        self.assertEqual(chosen.entity_id, client)
        self.assertIn("EverQuest client identity", chosen.reason)

        collisions = ZoneIdentityIndex(self.db).exact_collisions()
        self.assertIn("stonehive", collisions)

    def test_authoritative_zone_match_accepts_literal_and_exact_alias_equivalence(self):
        hole = self._zone("The Hole", "39", "eqclient:zone")
        self.db.add_alias(hole, "Hole")

        self.assertTrue(authoritative_zones_match(self.db, "  The Hole ", "the   hole"))
        self.assertTrue(authoritative_zones_match(self.db, "The Hole", "Hole"))
        self.assertFalse(authoritative_zones_match(self.db, None, "The Hole"))

    def test_authoritative_zone_match_refuses_ambiguous_and_missing_geography(self):
        north = self._zone("North Freeport", "8", "eqclient:zone")
        south = self._zone("South Freeport", "9", "eqclient:zone")
        self.db.add_alias(north, "Freeport")
        self.db.add_alias(south, "Freeport")

        self.assertFalse(authoritative_zones_match(self.db, "Freeport", "North Freeport"))
        self.assertFalse(authoritative_zones_match(self.db, "Unknown Place", "North Freeport"))

    def test_zone_context_uses_client_backed_join_target(self):
        _provider, client = self._duplicate_zone(
            "Stone Hive",
            client_id="396",
            provider_id="884",
        )

        context, status = build_zone_context(self.db, "Stone Hive")

        self.assertEqual(status, "linked")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.identity.entity_id, client)
        self.assertTrue(context.identity.client_zone_ids)

    def test_route_endpoints_and_cached_progress_use_client_backed_identity(self):
        _stone_provider, stone = self._duplicate_zone(
            "Stone Hive",
            client_id="396",
            provider_id="884",
        )
        _blight_provider, blight = self._duplicate_zone(
            "Blightfire Moors",
            client_id="395",
            provider_id="883",
        )
        ZoneTravelCatalog(self.db).add_provider_connection(
            stone,
            blight,
            source_name="test topology",
            source_kind="test",
            source_key="stone-to-blight",
            evidence="confirmed test edge",
        )
        self.db.conn.commit()

        route = build_route_result(self.db, "Stone Hive", "Blightfire Moors")
        self.assertTrue(route.ok)
        self.assertEqual(route.source_entity_id, stone)
        self.assertEqual(route.target_entity_id, blight)
        self.assertEqual(route.path, (stone, blight))

        guidance = build_route_guidance(self.db, "Stone Hive", "Blightfire Moors")
        hop, status = next_hop_for_zone(self.db, guidance, "Stone Hive")
        self.assertEqual(status, "linked")
        self.assertIsNotNone(hop)
        assert hop is not None
        self.assertEqual(hop.source_entity_id, stone)
        self.assertEqual(hop.target_entity_id, blight)

    def test_map_and_travel_reconciliation_choose_client_backed_duplicate_names(self):
        _stone_provider, stone = self._duplicate_zone(
            "Stone Hive",
            client_id="396",
            provider_id="884",
        )
        _blight_provider, blight = self._duplicate_zone(
            "Blightfire Moors",
            client_id="395",
            provider_id="883",
        )
        maps = self.root / "maps"
        self._write_map(maps, "stonehive", "To_Blightfire_Moors")
        MapCatalog(self.db).index_root(maps, source_name="Good's Maps")

        map_stats = ZoneMapCatalog(self.db).reconcile(source_name="Good's Maps")
        self.assertEqual(map_stats.linked, 1)
        binding = ZoneMapCatalog(self.db).binding_for_map("Good's Maps", "stonehive")
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.status, "linked")
        self.assertEqual(binding.zone_entity_id, stone)

        travel_stats = ZoneTravelCatalog(self.db).reconcile_from_maps(source_name="Good's Maps")
        self.assertEqual(travel_stats.candidates, 1)
        self.assertEqual(travel_stats.linked, 1)
        edge = ZoneTravelCatalog(self.db).edges_from(stone)[0]
        self.assertEqual(edge.target_zone_entity_id, blight)

    def test_finalization_rebuild_keeps_duplicate_name_map_and_travel_links(self):
        _stone_provider, stone = self._duplicate_zone(
            "Stone Hive",
            client_id="396",
            provider_id="884",
        )
        _blight_provider, blight = self._duplicate_zone(
            "Blightfire Moors",
            client_id="395",
            provider_id="883",
        )
        maps = self.root / "maps"
        self._write_map(maps, "stonehive", "To_Blightfire_Moors")
        MapCatalog(self.db).index_root(maps, source_name="Good's Maps")

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.db.path,
            snapshot,
            snapshot_version="authoritative-zone-join-test",
        )

        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            binding = ZoneMapCatalog(runtime).binding_for_map("Good's Maps", "stonehive")
            self.assertIsNotNone(binding)
            assert binding is not None
            self.assertEqual(binding.status, "linked")
            self.assertEqual(binding.zone_entity_id, stone)

            route = build_route_result(runtime, "Stone Hive", "Blightfire Moors")
            self.assertTrue(route.ok)
            self.assertEqual(route.path, (stone, blight))
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entities SET name='mutated' WHERE id=?", (stone,))
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
