from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.zone_provider_reconciliation import (
    PROVIDER_ZONE_CATALOG_VERSION,
    ProviderZoneReconciliationCatalog,
)


class ProviderZoneReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _client_zone(self, name: str, zone_id: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=zone_id,
            external_namespace="eqclient:zone",
            merge_by_name=False,
        )

    def _provider_zone(self, name: str, provider_id: str) -> int:
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=f"zone:{provider_id}",
            external_namespace="allakhazam:zone",
            merge_by_name=False,
        )

    def _allakhazam_zone_page(self, zone_name: str, provider_id: str) -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/db/zone.html?zstrat={provider_id}",
            title=f"{zone_name} :: EverQuest",
            entity_type="zone",
            sha256=f"zone-{provider_id}",
            plain_text="Connected Zones",
            raw_html="",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=f"zone:{provider_id}",
            source_version="mirror-test",
        )

    def _connected(self, source: int, target: int, page_id: int, evidence: str) -> None:
        self.db.upsert_relationship(
            source,
            target,
            "connected_to",
            source_page_id=page_id,
            evidence=evidence,
            data={"confidence": "structured", "direction": "North"},
        )

    def test_exact_name_requires_structured_neighbor_corroboration(self):
        client_stone = self._client_zone("Stone Hive", "400")
        client_blight = self._client_zone("Blightfire Moors", "401")
        client_mesa = self._client_zone("Goru'kar Mesa", "402")

        provider_stone = self._provider_zone("Stone Hive", "100")
        provider_blight = self._provider_zone("Blightfire Moors", "101")
        provider_mesa = self._provider_zone("Goru'kar Mesa", "102")
        page = self._allakhazam_zone_page("Stone Hive", "100")
        self._connected(provider_stone, provider_blight, page, "Blightfire Moors / North")

        stats = ProviderZoneReconciliationCatalog(self.db).reconcile()
        self.assertEqual(PROVIDER_ZONE_CATALOG_VERSION, "1")
        self.assertEqual(stats.provider_zones, 3)
        self.assertEqual(stats.linked, 2)
        self.assertEqual(stats.candidate, 1)
        self.assertEqual(stats.ambiguous, 0)
        self.assertEqual(stats.unresolved, 0)
        self.assertEqual(stats.corroborating_relationships, 1)

        catalog = ProviderZoneReconciliationCatalog(self.db)
        stone = catalog.binding_for_provider_zone(provider_stone)
        blight = catalog.binding_for_provider_zone(provider_blight)
        mesa = catalog.binding_for_provider_zone(provider_mesa)
        assert stone is not None and blight is not None and mesa is not None

        self.assertTrue(stone.projection_safe)
        self.assertEqual(stone.gameplay_zone_entity_id, client_stone)
        self.assertEqual(stone.corroboration_count, 1)
        self.assertEqual(stone.evidence[0]["gameplay_neighbor_entity_id"], client_blight)

        # The target-side provider row is independently corroborated by the same
        # structured edge in the opposite direction relative to that provider entity.
        self.assertTrue(blight.projection_safe)
        self.assertEqual(blight.gameplay_zone_entity_id, client_blight)
        self.assertEqual(blight.evidence[0]["gameplay_neighbor_entity_id"], client_stone)

        # Exact name alone is intentionally not enough to project provider facts.
        self.assertFalse(mesa.projection_safe)
        self.assertEqual(mesa.status, "candidate")
        self.assertEqual(mesa.gameplay_zone_entity_id, client_mesa)
        self.assertIn("lacks independent", mesa.reason)

    def test_multi_client_collision_and_provider_only_zone_never_link(self):
        self._client_zone("The Arena", "77")
        self._client_zone("The Arena", "78")
        provider_arena = self._provider_zone("The Arena", "501")
        provider_unknown = self._provider_zone("Forgotten Test Zone", "502")

        stats = ProviderZoneReconciliationCatalog(self.db).reconcile()
        self.assertEqual(stats.ambiguous, 1)
        self.assertEqual(stats.unresolved, 1)

        catalog = ProviderZoneReconciliationCatalog(self.db)
        arena = catalog.binding_for_provider_zone(provider_arena)
        unknown = catalog.binding_for_provider_zone(provider_unknown)
        assert arena is not None and unknown is not None
        self.assertEqual(arena.status, "ambiguous")
        self.assertIsNone(arena.gameplay_zone_entity_id)
        self.assertFalse(arena.projection_safe)
        self.assertEqual(unknown.status, "unresolved")
        self.assertFalse(unknown.projection_safe)

    def test_unstructured_or_non_provider_relation_does_not_upgrade_candidate(self):
        client_stone = self._client_zone("Stone Hive", "400")
        self._client_zone("Blightfire Moors", "401")
        provider_stone = self._provider_zone("Stone Hive", "100")
        provider_blight = self._provider_zone("Blightfire Moors", "101")
        page = self.db.upsert_source_page(
            url="test://weak-topology",
            title="weak topology",
            entity_type="zone",
            sha256="weak-topology",
            plain_text="",
            raw_html="",
            source_name="Weak Fixture",
            source_kind="fixture",
            source_key="weak",
        )
        self.db.upsert_relationship(
            provider_stone,
            provider_blight,
            "connected_to",
            source_page_id=page,
            evidence="same-name fixture",
            data={"confidence": "inferred"},
        )

        ProviderZoneReconciliationCatalog(self.db).reconcile()
        binding = ProviderZoneReconciliationCatalog(self.db).binding_for_provider_zone(provider_stone)
        assert binding is not None
        self.assertEqual(binding.status, "candidate")
        self.assertEqual(binding.gameplay_zone_entity_id, client_stone)
        self.assertEqual(binding.corroboration_count, 0)

    def test_reconcile_rebuilds_derived_rows_and_projection_ids_are_canonical_first(self):
        client_stone = self._client_zone("Stone Hive", "400")
        self._client_zone("Blightfire Moors", "401")
        provider_stone = self._provider_zone("Stone Hive", "100")
        provider_blight = self._provider_zone("Blightfire Moors", "101")
        page = self._allakhazam_zone_page("Stone Hive", "100")
        self._connected(provider_stone, provider_blight, page, "Blightfire Moors / North")

        catalog = ProviderZoneReconciliationCatalog(self.db)
        catalog.reconcile()
        self.assertEqual(
            catalog.projected_zone_entity_ids(client_stone),
            (client_stone, provider_stone),
        )

        # Removing the corroborating source fact downgrades the provider zone on the
        # next builder reconciliation rather than leaving a stale projection-safe row.
        self.db.conn.execute("DELETE FROM entity_relationships WHERE relation='connected_to'")
        self.db.conn.commit()
        catalog.reconcile()
        binding = catalog.binding_for_provider_zone(provider_stone)
        assert binding is not None
        self.assertEqual(binding.status, "candidate")
        self.assertEqual(catalog.projected_zone_entity_ids(client_stone), (client_stone,))


if __name__ == "__main__":
    unittest.main()
