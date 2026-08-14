from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.travel import build_route_result
from eqquest.zone_travel import ZoneTravelCatalog


class TravelRouteViewTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tempdir.name) / "knowledge.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str) -> int:
        return self.db.upsert_entity(kind="zone", name=name, merge_by_name=True)

    def test_route_text_uses_canonical_names_and_provider_evidence(self):
        a = self._zone("Stone Hive")
        b = self._zone("Blightfire Moors")
        c = self._zone("The Plane of Knowledge")
        catalog = ZoneTravelCatalog(self.db)
        catalog.add_provider_connection(
            a,
            b,
            connection_kind="zone_line",
            bidirectional=True,
            source_name="EverQuest Client",
            source_kind="client_topology",
            source_key="stonehive-blightfire",
            evidence="confirmed client zone line",
        )
        catalog.add_provider_connection(
            b,
            c,
            connection_kind="portal",
            source_name="Future Provider",
            source_kind="provider",
            source_key="blightfire-pok",
            evidence="portal to Plane of Knowledge",
        )

        result = build_route_result(self.db, "Stone Hive", "The Plane of Knowledge")
        self.assertTrue(result.ok)
        self.assertEqual(result.path, (a, b, c))
        self.assertIn("Stone Hive → The Plane of Knowledge", result.text)
        self.assertIn("Stone Hive → Blightfire Moors", result.text)
        self.assertIn("Blightfire Moors → The Plane of Knowledge", result.text)
        self.assertIn("EverQuest Client", result.text)
        self.assertIn("Future Provider", result.text)
        self.assertIn("confirmed client zone line", result.text)

    def test_route_endpoints_accept_shared_zone_identity_signals(self):
        source = self.db.upsert_entity(
            kind="zone",
            name="The Nexus",
            external_id="152",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"map_short_name": "nexus"},
        )
        target = self.db.upsert_entity(
            kind="zone",
            name="The Plane of Knowledge",
            external_id="202",
            external_namespace="eqclient:zone",
            merge_by_name=True,
            data={"short_name": "poknowledge"},
        )
        self.db.add_alias(target, "PoK", alias_type="provider_alias")
        ZoneTravelCatalog(self.db).add_provider_connection(
            source,
            target,
            connection_kind="portal",
            source_name="Topology Source",
            source_key="nexus-pok",
        )

        for start, destination in (
            ("152", "202"),
            ("nexus", "PoK"),
            ("The Nexus", "Plane of Knowledge"),
            ("The Nexus", "poknowledge"),
        ):
            with self.subTest(start=start, destination=destination):
                result = build_route_result(self.db, start, destination)
                self.assertTrue(result.ok)
                self.assertEqual(result.path, (source, target))
                self.assertIn("The Nexus → The Plane of Knowledge", result.text)

    def test_unique_substring_is_not_promoted_to_zone_identity(self):
        source = self._zone("Stone Hive")
        target = self._zone("The Plane of Knowledge")
        ZoneTravelCatalog(self.db).add_provider_connection(
            source,
            target,
            source_name="Topology Source",
            source_key="stonehive-pok",
        )

        # Generic entity search previously treated the unique substring "Knowledge"
        # as sufficient. Route endpoints now require a canonical zone identity token.
        result = build_route_result(self.db, "Stone Hive", "Knowledge")
        self.assertFalse(result.ok)
        self.assertIsNone(result.target_entity_id)
        self.assertIn("was not found", result.text)

    def test_route_view_honors_explicit_bidirectional_evidence(self):
        a = self._zone("Zone A")
        b = self._zone("Zone B")
        ZoneTravelCatalog(self.db).add_provider_connection(
            a,
            b,
            connection_kind="zone_line",
            bidirectional=True,
            source_name="Topology Source",
            source_key="A-B",
        )

        result = build_route_result(self.db, "Zone B", "Zone A")
        self.assertTrue(result.ok)
        self.assertEqual(result.path, (b, a))
        self.assertIn("reverse direction of explicitly two-way evidence", result.text)

    def test_unconfirmed_route_is_not_invented(self):
        self._zone("Zone A")
        self._zone("Zone B")
        result = build_route_result(self.db, "Zone A", "Zone B")
        self.assertFalse(result.ok)
        self.assertEqual(result.path, ())
        self.assertIn("No confirmed route", result.text)
        self.assertIn("are not guessed", result.text)

    def test_unknown_destination_reports_local_knowledge_miss(self):
        self._zone("Zone A")
        result = build_route_result(self.db, "Zone A", "Definitely Not A Zone")
        self.assertFalse(result.ok)
        self.assertIn("Destination zone", result.text)
        self.assertIn("was not found", result.text)


if __name__ == "__main__":
    unittest.main()
