from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.provider_zone_travel import ProviderZoneTravelCatalog
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog
from eqquest.zone_travel import ZoneTravelCatalog


class ProviderZoneTravelTests(unittest.TestCase):
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

    def _page(self, zone_name: str, provider_id: str, *, source_name: str = "Allakhazam") -> int:
        scheme = "https" if source_name == "Allakhazam" else "test"
        url = (
            f"https://everquest.allakhazam.com/db/zone.html?zstrat={provider_id}"
            if source_name == "Allakhazam"
            else f"{scheme}://provider/{provider_id}"
        )
        return self.db.upsert_source_page(
            url=url,
            title=f"{zone_name} provider page",
            entity_type="zone",
            sha256=f"{source_name}-{provider_id}",
            plain_text="Connected Zones",
            raw_html="",
            source_name=source_name,
            source_kind="local_mirror" if source_name == "Allakhazam" else "fixture",
            source_key=f"zone:{provider_id}",
            source_version="mirror-test",
        )

    def _connected(
        self,
        source: int,
        target: int,
        page_id: int,
        evidence: str,
        *,
        confidence: str = "structured",
        direction: str = "",
    ) -> None:
        data = {"confidence": confidence}
        if direction:
            data["direction"] = direction
        self.db.upsert_relationship(
            source,
            target,
            "connected_to",
            source_page_id=page_id,
            evidence=evidence,
            data=data,
        )

    def _stone_blight_fixture(self):
        client_stone = self._client_zone("Stone Hive", "400")
        client_blight = self._client_zone("Blightfire Moors", "401")
        provider_stone = self._provider_zone("Stone Hive", "100")
        provider_blight = self._provider_zone("Blightfire Moors", "101")
        stone_page = self._page("Stone Hive", "100")
        self._connected(
            provider_stone,
            provider_blight,
            stone_page,
            "Blightfire Moors / North",
            direction="North",
        )
        return client_stone, client_blight, provider_stone, provider_blight

    def test_structured_connected_zone_compiles_one_directed_canonical_edge(self):
        client_stone, client_blight, provider_stone, provider_blight = self._stone_blight_fixture()
        provider_stats = ProviderZoneReconciliationCatalog(self.db).reconcile()
        self.assertEqual(provider_stats.linked, 2)

        stats = ProviderZoneTravelCatalog(self.db).reconcile()
        self.assertEqual(stats.relationships_scanned, 1)
        self.assertEqual(stats.linked, 1)
        self.assertEqual(stats.ignored_unstructured, 0)
        self.assertEqual(stats.blocked_source, 0)
        self.assertEqual(stats.blocked_target, 0)
        self.assertEqual(stats.self_edges, 0)

        edges = [
            edge
            for edge in ZoneTravelCatalog(self.db).edges_from(client_stone)
            if edge.source_kind == "provider_zone_relationship"
        ]
        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertEqual(edge.source_zone_entity_id, client_stone)
        self.assertEqual(edge.target_zone_entity_id, client_blight)
        self.assertEqual(edge.connection_kind, "zone_connection")
        self.assertFalse(edge.bidirectional)
        self.assertEqual(edge.source_name, "Allakhazam")
        self.assertEqual(edge.source_version, "mirror-test")
        self.assertIn("Blightfire Moors / North", edge.evidence)
        self.assertIsNone(edge.x)
        self.assertIsNone(edge.y)
        self.assertIsNone(edge.z)
        self.assertIn("zone:100#connected_to:zone:101", edge.source_key)

        self.assertEqual(
            ZoneTravelCatalog(self.db).shortest_path(client_stone, client_blight),
            [client_stone, client_blight],
        )
        self.assertEqual(
            ZoneTravelCatalog(self.db).shortest_path(client_blight, client_stone),
            [],
        )

        # Provider entities remain source evidence; topology points at gameplay IDs.
        self.assertNotEqual(provider_stone, client_stone)
        self.assertNotEqual(provider_blight, client_blight)

    def test_reverse_route_requires_separate_explicit_provider_relationship(self):
        client_stone, client_blight, provider_stone, provider_blight = self._stone_blight_fixture()
        blight_page = self._page("Blightfire Moors", "101")
        self._connected(
            provider_blight,
            provider_stone,
            blight_page,
            "Stone Hive / South",
            direction="South",
        )

        ProviderZoneReconciliationCatalog(self.db).reconcile()
        stats = ProviderZoneTravelCatalog(self.db).reconcile()
        self.assertEqual(stats.linked, 2)

        all_edges = self.db.conn.execute(
            """
            SELECT source_zone_entity_id,target_zone_entity_id,bidirectional
            FROM zone_travel_edges
            WHERE source_kind='provider_zone_relationship'
            ORDER BY source_zone_entity_id,target_zone_entity_id
            """
        ).fetchall()
        self.assertEqual(len(all_edges), 2)
        self.assertTrue(all(int(row["bidirectional"]) == 0 for row in all_edges))
        self.assertEqual(
            {(int(row["source_zone_entity_id"]), int(row["target_zone_entity_id"])) for row in all_edges},
            {(client_stone, client_blight), (client_blight, client_stone)},
        )
        self.assertEqual(
            ZoneTravelCatalog(self.db).shortest_path(client_blight, client_stone),
            [client_blight, client_stone],
        )

    def test_unresolved_provider_target_is_blocked_not_guessed(self):
        client_stone = self._client_zone("Stone Hive", "400")
        self._client_zone("Blightfire Moors", "401")
        provider_stone = self._provider_zone("Stone Hive", "100")
        provider_blight = self._provider_zone("Blightfire Moors", "101")
        provider_unknown = self._provider_zone("Forgotten Test Zone", "999")
        page = self._page("Stone Hive", "100")
        self._connected(provider_stone, provider_blight, page, "Blightfire Moors / North")
        self._connected(provider_stone, provider_unknown, page, "Forgotten Test Zone / East")

        reconciliation = ProviderZoneReconciliationCatalog(self.db).reconcile()
        self.assertGreaterEqual(reconciliation.linked, 2)
        unknown = ProviderZoneReconciliationCatalog(self.db).binding_for_provider_zone(provider_unknown)
        self.assertIsNotNone(unknown)
        assert unknown is not None
        self.assertEqual(unknown.status, "unresolved")

        stats = ProviderZoneTravelCatalog(self.db).reconcile()
        self.assertEqual(stats.relationships_scanned, 2)
        self.assertEqual(stats.linked, 1)
        self.assertEqual(stats.blocked_target, 1)

        edges = self.db.conn.execute(
            "SELECT target_zone_entity_id FROM zone_travel_edges WHERE source_kind='provider_zone_relationship'"
        ).fetchall()
        self.assertEqual(len(edges), 1)
        self.assertNotEqual(int(edges[0]["target_zone_entity_id"]), provider_unknown)
        self.assertEqual(
            ZoneTravelCatalog(self.db).edges_from(client_stone)[0].source_zone_entity_id,
            client_stone,
        )

    def test_inferred_connected_to_row_is_ignored_even_when_endpoints_are_linked(self):
        client_stone, client_blight, provider_stone, provider_blight = self._stone_blight_fixture()
        ProviderZoneReconciliationCatalog(self.db).reconcile()

        weak_page = self._page("Stone Hive", "weak-100", source_name="Weak Fixture")
        self._connected(
            provider_stone,
            provider_blight,
            weak_page,
            "inferred duplicate connection",
            confidence="inferred",
        )

        stats = ProviderZoneTravelCatalog(self.db).reconcile()
        self.assertEqual(stats.relationships_scanned, 2)
        self.assertEqual(stats.linked, 1)
        self.assertEqual(stats.ignored_unstructured, 1)

        rows = self.db.conn.execute(
            "SELECT source_name,source_zone_entity_id,target_zone_entity_id FROM zone_travel_edges "
            "WHERE source_kind='provider_zone_relationship'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0]["source_name"]), "Allakhazam")
        self.assertEqual(int(rows[0]["source_zone_entity_id"]), client_stone)
        self.assertEqual(int(rows[0]["target_zone_entity_id"]), client_blight)

    def test_source_filter_rebuilds_only_that_provider_rows(self):
        client_stone, client_blight, _provider_stone, _provider_blight = self._stone_blight_fixture()
        ProviderZoneReconciliationCatalog(self.db).reconcile()
        ProviderZoneTravelCatalog(self.db).reconcile()
        before = self.db.conn.execute(
            "SELECT COUNT(*) FROM zone_travel_edges WHERE source_kind='provider_zone_relationship'"
        ).fetchone()[0]
        self.assertEqual(int(before), 1)

        stats = ProviderZoneTravelCatalog(self.db).reconcile(source_name="Allakhazam")
        self.assertEqual(stats.linked, 1)
        self.assertEqual(
            ZoneTravelCatalog(self.db).shortest_path(client_stone, client_blight),
            [client_stone, client_blight],
        )


if __name__ == "__main__":
    unittest.main()
