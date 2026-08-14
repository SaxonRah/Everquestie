from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.map_catalog import MapCatalog
from eqquest.map_resolution import resolve_catalog_map_for_zone
from eqquest.runtime import RuntimeDatabase
from eqquest.zone_catalog import ZoneMapCatalog
from eqquest.zone_identity import ZoneIdentityIndex, resolve_zone, zone_identity_audit_text
from eqquest.zone_travel import ZoneTravelCatalog


class ZoneIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _add_binding(self, zone_id: int, stem: str, *, source: str = "Brewall") -> None:
        ZoneMapCatalog(self.db).ensure_schema()
        self.db.conn.execute(
            """
            INSERT INTO zone_map_bindings(
                source_name,source_version,map_stem,zone_entity_id,zone_name,
                status,reason,catalog_version,updated_at
            )
            SELECT ?,?,?,?,?,?,?,?,?
            """,
            (
                source,
                "2026-08",
                stem,
                zone_id,
                str(self.db.entity(zone_id)["name"]),
                "linked",
                "test binding",
                "1",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.db.conn.commit()

    def _write_map(self, folder: Path, stem: str, *labels: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        lines = [
            f"P {index * 10},{index * 20},3,255,0,0,2,{label}"
            for index, label in enumerate(labels or ("Test_Label",), start=1)
        ]
        (folder / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_one_zone_identity_resolves_name_alias_short_name_client_id_and_map_stem(self):
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "poknowledge"},
        )
        self.db.add_alias(zone_id, "PoK", alias_type="provider_alias")
        self._add_binding(zone_id, "planeofknowledge")

        index = ZoneIdentityIndex(self.db)
        cases = {
            "The Plane of Knowledge": "canonical_name",
            "Plane of Knowledge": "canonical_name",
            "PoK": "alias",
            "poknowledge": "short_name",
            "202": "client_id",
            # This is also a confirmed map stem, but canonical article-stripped name
            # identity is intentionally the stronger explanation for the same token.
            "planeofknowledge": "canonical_name",
        }
        for token, expected_kind in cases.items():
            with self.subTest(token=token):
                result = index.resolve(token)
                self.assertEqual(result.status, "linked")
                self.assertEqual(result.entity_id, zone_id)
                self.assertEqual(result.zone_name, "The Plane of Knowledge")
                self.assertEqual(result.match_kind, expected_kind)

    def test_duplicate_external_token_stays_ambiguous(self):
        south = self.db.upsert_entity(kind="zone", name="South Freeport", merge_by_name=True)
        east = self.db.upsert_entity(kind="zone", name="East Freeport", merge_by_name=True)
        self.db.add_alias(south, "Freeport", alias_type="provider_alias")
        self.db.add_alias(east, "Freeport", alias_type="provider_alias")

        result = resolve_zone(self.db, "Freeport")
        self.assertEqual(result.status, "ambiguous")
        self.assertIsNone(result.identity)
        self.assertEqual({row.entity_id for row in result.candidates}, {south, east})

        audit = zone_identity_audit_text(self.db)
        self.assertIn("Ambiguous exact external tokens: 1", audit)
        self.assertIn("freeport", audit)
        self.assertIn("South Freeport", audit)
        self.assertIn("East Freeport", audit)

    def test_builder_inference_modes_are_opt_in(self):
        south = self.db.upsert_entity(kind="zone", name="South Qeynos", merge_by_name=True)
        self.db.upsert_entity(kind="zone", name="North Qeynos", merge_by_name=True)
        index = ZoneIdentityIndex(self.db, include_map_bindings=False)

        strict = index.resolve("south")
        self.assertEqual(strict.status, "unresolved")

        significant = index.resolve("south", allow_significant_word=True)
        self.assertEqual(significant.status, "linked")
        self.assertEqual(significant.entity_id, south)
        self.assertEqual(significant.match_kind, "significant_word")

        contained = index.resolve("southqeynos2", allow_containment=True)
        self.assertEqual(contained.status, "linked")
        self.assertEqual(contained.entity_id, south)
        self.assertEqual(contained.match_kind, "containment")

        shared = index.resolve("qeynos", allow_significant_word=True)
        self.assertEqual(shared.status, "ambiguous")
        self.assertEqual(len(shared.candidates), 2)

    def test_map_catalog_can_link_article_stripped_canonical_name(self):
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            merge_by_name=True,
        )
        maps = self.root / "article-maps"
        self._write_map(maps, "planeofknowledge")
        MapCatalog(self.db).index_root(maps, source_name="Brewall")

        stats = ZoneMapCatalog(self.db).reconcile(source_name="Brewall")
        self.assertEqual(stats.linked, 1)
        binding = ZoneMapCatalog(self.db).binding_for_map("Brewall", "planeofknowledge")
        self.assertIsNotNone(binding)
        self.assertEqual(binding.status, "linked")
        self.assertEqual(binding.zone_entity_id, zone_id)
        self.assertEqual(binding.zone_name, "The Plane of Knowledge")

    def test_derived_map_short_name_cannot_preserve_stale_binding(self):
        zone_id = self.db.upsert_entity(kind="zone", name="Zone Alpha", merge_by_name=True)
        self.db.add_alias(zone_id, "oldstem", alias_type="provider_short_name")
        maps = self.root / "stale-maps"
        self._write_map(maps, "oldstem")
        MapCatalog(self.db).index_root(maps, source_name="Brewall")
        catalog = ZoneMapCatalog(self.db)

        first = catalog.reconcile(source_name="Brewall")
        self.assertEqual(first.linked, 1)
        first_binding = catalog.binding_for_map("Brewall", "oldstem")
        self.assertIsNotNone(first_binding)
        self.assertEqual(first_binding.zone_entity_id, zone_id)
        first_data = json.loads(self.db.entity(zone_id)["data_json"] or "{}")
        self.assertEqual(first_data.get("map_short_name"), "oldstem")
        self.assertEqual(first_data.get("map_short_name_source"), "zone_map_catalog")

        # Remove the independent provider identity evidence. map_sources.zone_name,
        # zone_map_bindings and the derived map_short_name all still contain the old
        # answer; none is permitted to bootstrap the next catalog pass.
        self.db.conn.execute(
            "DELETE FROM entity_aliases WHERE entity_id=? AND normalized_alias='oldstem'",
            (zone_id,),
        )
        self.db.conn.commit()

        second = catalog.reconcile(source_name="Brewall")
        self.assertEqual(second.unresolved, 1)
        second_binding = catalog.binding_for_map("Brewall", "oldstem")
        self.assertIsNotNone(second_binding)
        self.assertEqual(second_binding.status, "unresolved")
        self.assertIsNone(second_binding.zone_entity_id)
        second_data = json.loads(self.db.entity(zone_id)["data_json"] or "{}")
        self.assertNotIn("map_short_name", second_data)
        self.assertNotIn("map_short_name_source", second_data)

    def test_runtime_can_consume_finalized_catalog_derived_short_name(self):
        zone_id = self.db.upsert_entity(kind="zone", name="Zone Alpha", merge_by_name=True)
        self.db.merge_entity_data(
            zone_id,
            {
                "map_short_name": "alphamap",
                "map_short_name_source": "zone_map_catalog",
            },
        )
        runtime_index = ZoneIdentityIndex(self.db)
        self.assertEqual(runtime_index.resolve("alphamap").entity_id, zone_id)

        rebuild_index = ZoneIdentityIndex(
            self.db,
            include_map_bindings=False,
            include_derived_map_short_names=False,
        )
        self.assertEqual(rebuild_index.resolve("alphamap").status, "unresolved")

    def test_travel_catalog_resolves_article_stripped_destination(self):
        source = self.db.upsert_entity(
            kind="zone",
            name="The Nexus",
            merge_by_name=True,
            data={"map_short_name": "nexus"},
        )
        target = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            merge_by_name=True,
        )
        maps = self.root / "travel-maps"
        self._write_map(maps, "nexus", "To_Plane_of_Knowledge")
        MapCatalog(self.db).index_root(maps, source_name="Brewall")
        ZoneMapCatalog(self.db).reconcile(source_name="Brewall")

        stats = ZoneTravelCatalog(self.db).reconcile_from_maps(source_name="Brewall")
        self.assertEqual(stats.candidates, 1)
        self.assertEqual(stats.linked, 1)
        edge = ZoneTravelCatalog(self.db).edges_from(source)[0]
        self.assertEqual(edge.target_zone_entity_id, target)

    def test_runtime_map_resolution_accepts_canonical_article_variant(self):
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=True,
        )
        self._add_binding(zone_id, "poknowledge")
        maps = self.root / "maps"
        maps.mkdir()
        (maps / "poknowledge.txt").write_text("", encoding="utf-8")

        result = resolve_catalog_map_for_zone(self.db, "Plane of Knowledge", maps)
        self.assertIsNotNone(result.path)
        self.assertEqual(result.path.name, "poknowledge.txt")
        self.assertEqual(result.reason, "shipped canonical zone/map binding")

    def test_runtime_map_resolution_refuses_to_break_zone_identity_ambiguity(self):
        south = self.db.upsert_entity(kind="zone", name="South Qeynos", merge_by_name=True)
        north = self.db.upsert_entity(kind="zone", name="North Qeynos", merge_by_name=True)
        self.db.add_alias(south, "qeynos", alias_type="provider_alias")
        self.db.add_alias(north, "qeynos", alias_type="provider_alias")
        maps = self.root / "maps"
        maps.mkdir()
        # Legacy filename matching would happily choose this file. Canonical identity
        # ambiguity must win unless the player supplied an explicit binding.
        (maps / "qeynos.txt").write_text("", encoding="utf-8")

        result = resolve_catalog_map_for_zone(self.db, "qeynos", maps)
        self.assertIsNone(result.path)
        self.assertIn("canonical zone identity is ambiguous", result.reason)

        bound = resolve_catalog_map_for_zone(
            self.db,
            "qeynos",
            maps,
            bound_stem="qeynos",
        )
        self.assertIsNotNone(bound.path)
        self.assertEqual(bound.reason, "user map binding")

    def test_finalized_runtime_uses_same_identity_projection_read_only(self):
        zone_id = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "poknowledge"},
        )
        self.db.add_alias(zone_id, "PoK", alias_type="provider_alias")
        self._add_binding(zone_id, "planeofknowledge")
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.db.path,
            snapshot,
            snapshot_version="zone-identity-test",
        )

        self.db.close()
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            index = ZoneIdentityIndex(runtime)
            for token in ("Plane of Knowledge", "PoK", "poknowledge", "202", "planeofknowledge"):
                with self.subTest(token=token):
                    result = index.resolve(token)
                    self.assertEqual(result.status, "linked")
                    self.assertEqual(result.entity_id, zone_id)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entities SET name='mutated' WHERE id=?", (zone_id,))
        finally:
            runtime.close()
            self.db = Database(self.root / "teardown.sqlite3")


if __name__ == "__main__":
    unittest.main()
