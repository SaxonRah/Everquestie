from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from eqquest.db import Database
from eqquest.route_acceptance import (
    DEFAULT_ROUTE_ACCEPTANCE_CASES,
    evaluate_route_acceptance,
    route_acceptance_text,
)
from eqquest.zone_travel import ZoneTravelCatalog


class RouteAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "working.sqlite3"
        self.db = Database(self.db_path)

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
        bidirectional: bool = False,
    ) -> None:
        ZoneTravelCatalog(self.db).add_provider_connection(
            source,
            target,
            connection_kind="zone_connection",
            bidirectional=bidirectional,
            source_name="Route acceptance regression topology",
            source_kind="test_confirmed_topology",
            source_key=f"acceptance:{index}",
            source_version="test-v1",
            evidence=f"confirmed acceptance edge {index}",
        )

    def test_default_suite_keeps_difficult_current_live_endpoint_queries_literal(self):
        self.assertEqual(
            DEFAULT_ROUTE_ACCEPTANCE_CASES,
            (
                ("The Hole", "Labyrinth of Spite"),
                ("Paineel", "The Hole"),
                ("Stonebrunt Mountains", "Paineel"),
                ("Greater Faydark", "The Hole"),
                ("Stone Hive", "West Freeport"),
            ),
        )
        flattened = {name for pair in DEFAULT_ROUTE_ACCEPTANCE_CASES for name in pair}
        self.assertNotIn("Feldax Hive", flattened)
        self.assertNotIn("The Stone Hive", flattened)
        self.assertNotIn("North Freeport", flattened)
        self.assertIn("West Freeport", flattened)

    def test_default_suite_literals_resolve_when_exact_client_names_exist(self):
        # This catches a regression where a synthetic stress-test zone, retired default,
        # or display-name typo leaks into the current-live snapshot acceptance suite.
        # No fuzzy aliases are added.
        real_client_names = (
            "The Hole",
            "Labyrinth of Spite",
            "Paineel",
            "Stonebrunt Mountains",
            "Greater Faydark",
            "Stone Hive",
            "West Freeport",
        )
        for number, name in enumerate(real_client_names, start=100):
            self._zone(name, number)

        summary = evaluate_route_acceptance(self.db)
        self.assertEqual(summary.total, len(DEFAULT_ROUTE_ACCEPTANCE_CASES))
        for result in summary.results:
            self.assertTrue(result.source.linked, result.source.as_dict())
            self.assertTrue(result.target.linked, result.target.as_dict())
            self.assertNotIn(result.status, {"source_unresolved", "target_unresolved"})
            self.assertNotIn(result.status, {"source_ambiguous", "target_ambiguous"})

    def test_stone_hive_query_keeps_historical_zone_identity_without_live_default(self):
        self._zone("Stone Hive", 396)
        self._zone("West Freeport", 9)
        self._zone("North Freeport", 8)

        canonical = evaluate_route_acceptance(self.db, [("Stone Hive", "West Freeport")])
        self.assertTrue(canonical.results[0].source.linked)
        self.assertEqual(canonical.results[0].source.canonical_name, "Stone Hive")
        self.assertTrue(canonical.results[0].target.linked)
        self.assertEqual(canonical.results[0].target.canonical_name, "West Freeport")

        noncanonical = evaluate_route_acceptance(self.db, [("The Stone Hive", "West Freeport")])
        self.assertEqual(noncanonical.results[0].status, "source_unresolved")
        self.assertFalse(noncanonical.results[0].source.linked)

        historical = evaluate_route_acceptance(self.db, [("Stone Hive", "North Freeport")])
        self.assertTrue(historical.results[0].target.linked)
        self.assertEqual(historical.results[0].target.canonical_name, "North Freeport")
        self.assertNotIn(("Stone Hive", "North Freeport"), DEFAULT_ROUTE_ACCEPTANCE_CASES)

    def test_reachable_acceptance_has_no_64_hop_ceiling(self):
        source = self._zone("The Hole", 39)
        transit = [self._zone(f"Acceptance Transit {i:02d}", 1000 + i) for i in range(70)]
        target = self._zone("Labyrinth of Spite", 9999)
        path = [source, *transit, target]
        for index, (a, b) in enumerate(zip(path, path[1:]), start=1):
            self._edge(a, b, index)

        summary = evaluate_route_acceptance(self.db, [("The Hole", "Labyrinth of Spite")])
        self.assertEqual(summary.total, 1)
        result = summary.results[0]
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "reachable")
        self.assertEqual(result.hop_count, 71)
        self.assertEqual(result.path_entity_ids, tuple(path))
        self.assertEqual(result.path_zone_names[0], "The Hole")
        self.assertEqual(result.path_zone_names[-1], "Labyrinth of Spite")

        text = route_acceptance_text(summary)
        self.assertIn("[PASS reachable] The Hole → Labyrinth of Spite", text)
        self.assertIn("71 hop(s)", text)
        self.assertIn("…", text)

    def test_directionality_blocked_and_disconnected_are_distinct_failures(self):
        a = self._zone("A", 1)
        b = self._zone("B", 2)
        c = self._zone("C", 3)
        island = self._zone("Island", 4)
        self._edge(a, b, 1)
        self._edge(b, c, 2)

        summary = evaluate_route_acceptance(
            self.db,
            [("C", "A"), ("A", "Island")],
        )
        reverse, disconnected = summary.results

        self.assertEqual(reverse.status, "directionality_blocked")
        self.assertFalse(reverse.ok)
        self.assertIsNotNone(reverse.diagnostic)
        self.assertTrue(reverse.diagnostic.target_in_weak_component)
        self.assertFalse(reverse.diagnostic.target_in_directed_reachable_set)

        self.assertEqual(disconnected.status, "disconnected")
        self.assertFalse(disconnected.ok)
        self.assertIsNotNone(disconnected.diagnostic)
        self.assertFalse(disconnected.diagnostic.target_in_weak_component)

    def test_exact_identity_policy_refuses_unresolved_and_multi_client_ambiguity(self):
        self._zone("Twin Zone", 10)
        self._zone("Twin Zone", 11)
        target = self._zone("Target", 12)

        summary = evaluate_route_acceptance(
            self.db,
            [("Missing Zone", "Target"), ("Twin Zone", "Target")],
        )
        missing, ambiguous = summary.results
        self.assertEqual(missing.status, "source_unresolved")
        self.assertEqual(ambiguous.status, "source_ambiguous")
        self.assertEqual(len(ambiguous.source.candidates), 2)
        self.assertEqual(ambiguous.target.entity_id, target)

        text = route_acceptance_text(summary)
        self.assertIn("source candidates:", text)
        self.assertIn("Twin Zone", text)

    def test_unique_eqclient_identity_wins_same_name_provider_zone(self):
        provider = self.db.upsert_entity(
            kind="zone",
            name="Authority Zone",
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=777",
            external_id="zone:777",
        )
        client = self._zone("Authority Zone", 77)
        target = self._zone("Target", 78)
        self._edge(client, target, 1)

        summary = evaluate_route_acceptance(self.db, [("Authority Zone", "Target")])
        result = summary.results[0]
        self.assertEqual(result.status, "reachable")
        self.assertEqual(result.source.entity_id, client)
        self.assertNotEqual(result.source.entity_id, provider)

    def test_same_canonical_zone_is_an_accepted_zero_hop_case(self):
        qeynos = self._zone("South Qeynos", 1)
        self.db.add_alias(qeynos, "Qeynos South", alias_type="provider_alias")

        summary = evaluate_route_acceptance(self.db, [("South Qeynos", "Qeynos South")])
        result = summary.results[0]
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "same_zone")
        self.assertEqual(result.hop_count, 0)
        self.assertEqual(result.path_entity_ids, (qeynos,))

    def test_read_only_snapshot_adapter_does_not_require_schema_mutation(self):
        source = self._zone("Paineel", 75)
        target = self._zone("The Hole", 39)
        self._edge(source, target, 1)

        ro = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)
        ro.row_factory = sqlite3.Row
        try:
            runtime_like = SimpleNamespace(conn=ro, knowledge_writable=False)
            summary = evaluate_route_acceptance(runtime_like, [("Paineel", "The Hole")])
            self.assertTrue(summary.results[0].ok)
            self.assertEqual(summary.results[0].path_zone_names, ("Paineel", "The Hole"))
        finally:
            ro.close()

    def test_summary_json_is_stable_and_machine_readable(self):
        source = self._zone("Greater Faydark", 54)
        target = self._zone("The Hole", 39)
        self._edge(source, target, 1)
        summary = evaluate_route_acceptance(self.db, [("Greater Faydark", "The Hole")])
        payload = summary.as_dict()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["accepted"], 1)
        self.assertEqual(payload["failed"], 0)
        self.assertEqual(payload["status_counts"], {"reachable": 1})
        self.assertEqual(payload["results"][0]["hop_count"], 1)
        self.assertEqual(payload["results"][0]["path_zone_names"], ["Greater Faydark", "The Hole"])


if __name__ == "__main__":
    unittest.main()
