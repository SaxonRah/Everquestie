from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.world_profile_routing import build_profiled_route_guidance, profiled_route_guidance_text
from eqquest.world_profiles import (
    active_world_profile_id,
    build_profiled_route_result,
    p99_expansion_allowed,
    set_active_world_profile,
    shortest_path_for_profile,
    zone_profile_decision,
)
from eqquest.zone_travel import ZoneTravelCatalog


class WorldProfileRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, number: int, expansion: str = "") -> int:
        data = {"expansion": expansion} if expansion else None
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=str(number),
            external_namespace="eqclient:zone",
            data=data,
        )

    def _edge(
        self,
        source: int,
        target: int,
        key: str,
        *,
        bidirectional: bool = False,
    ) -> None:
        ZoneTravelCatalog(self.db).add_provider_connection(
            source,
            target,
            connection_kind="travel",
            bidirectional=bidirectional,
            source_name="World-profile regression",
            source_kind="test_confirmed_topology",
            source_key=key,
            source_version="test-v1",
            evidence=key,
        )

    def test_live_is_default_and_excludes_historical_north_freeport(self):
        west = self._zone("West Freeport", 9, "EverQuest")
        north = self._zone("North Freeport", 6, "EverQuest")
        self._edge(west, north, "west-to-north")

        self.assertEqual(active_world_profile_id(self.db), "live")
        decision = zone_profile_decision(self.db, north, "live")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "historical")

        route = build_profiled_route_result(self.db, "West Freeport", "North Freeport", "live")
        self.assertFalse(route.ok)
        self.assertIn("retained as knowledge", route.text)
        self.assertIn("not routeable", route.text)

    def test_live_keeps_modern_stone_hive_to_west_freeport_route(self):
        stone = self._zone("Stone Hive", 396, "The Serpent's Spine")
        blight = self._zone("Blightfire Moors", 395, "The Serpent's Spine")
        pok = self._zone("The Plane of Knowledge", 202, "Planes of Power")
        west = self._zone("West Freeport", 9, "EverQuest")
        self._edge(stone, blight, "stone-to-blight")
        self._edge(blight, pok, "blight-to-pok")
        self._edge(pok, west, "pok-to-west")

        self.assertEqual(
            shortest_path_for_profile(self.db, stone, west, "live"),
            [stone, blight, pok, west],
        )
        set_active_world_profile(self.db, "live")
        guidance = build_profiled_route_guidance(self.db, "Stone Hive", "West Freeport")
        self.assertTrue(guidance.ok)
        self.assertEqual(tuple(guidance.route.path), (stone, blight, pok, west))
        text = profiled_route_guidance_text(self.db, guidance)
        self.assertIn("Gameplay profile: Live (default)", text)
        self.assertIn("Route: Stone Hive → West Freeport", text)
        self.assertIn("Confirmed hops: 3", text)

    def test_p99_allows_north_freeport_and_classic_routes(self):
        west = self._zone("West Freeport", 9, "EverQuest")
        north = self._zone("North Freeport", 6, "EverQuest")
        self._edge(west, north, "classic-freeport", bidirectional=True)

        self.assertTrue(zone_profile_decision(self.db, north, "p99").allowed)
        self.assertEqual(
            shortest_path_for_profile(self.db, west, north, "p99"),
            [west, north],
        )
        self.assertEqual(
            shortest_path_for_profile(self.db, north, west, "p99"),
            [north, west],
        )

    def test_p99_rejects_post_velious_zone_from_expansion_evidence(self):
        classic = self._zone("West Freeport", 9, "EverQuest")
        stone = self._zone("Stone Hive", 396, "The Serpent's Spine")
        self._edge(classic, stone, "classic-to-modern")

        decision = zone_profile_decision(self.db, stone, "p99")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "post_velious")
        self.assertIn("after Velious", decision.reason)

        route = build_profiled_route_result(self.db, "West Freeport", "Stone Hive", "p99")
        self.assertFalse(route.ok)
        self.assertIn("not routeable", route.text)

    def test_p99_expansion_absence_markers_remain_unknown(self):
        for marker in ("Unknown", "N/A", "NA", "None", "null", "?", "Unspecified", "Not specified", "TBD"):
            with self.subTest(marker=marker):
                self.assertIsNone(p99_expansion_allowed(marker))

        unknown_zone = self._zone("Mystery Zone", 9001, "Unknown")
        decision = zone_profile_decision(self.db, unknown_zone, "p99")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, "era_unknown")
        self.assertIn("no compiled expansion fact proves", decision.reason)

    def test_p99_unreviewed_taxonomy_values_remain_unknown(self):
        for value in ("Antonica", "Norrath Geography", "Some Future Taxonomy"):
            with self.subTest(value=value):
                self.assertIsNone(p99_expansion_allowed(value))

        antonica = self._zone("Taxonomy Example", 9002, "Antonica")
        decision = zone_profile_decision(self.db, antonica, "p99")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, "era_unknown")

    def test_p99_uses_exact_reviewed_expansion_names_not_classic_substrings(self):
        for value in ("EverQuest", "Kunark", "The Ruins of Kunark", "Velious", "The Scars of Velious"):
            with self.subTest(value=value):
                self.assertIs(p99_expansion_allowed(value), True)

        for value in (
            "Luclin",
            "Power",
            "Planes of Power",
            "LDoN",
            "Gates",
            "Omens",
            "Empires of Kunark",
            "Torment of Velious",
            "Claws of Veeshan",
            "The Serpent's Spine",
            "The Outer Brood",
            "Shattering of Ro",
        ):
            with self.subTest(value=value):
                self.assertIs(p99_expansion_allowed(value), False)

    def test_p99_blocks_modern_hub_even_when_expansion_metadata_is_missing(self):
        west = self._zone("West Freeport", 9, "EverQuest")
        pok = self._zone("The Plane of Knowledge", 202)
        north = self._zone("North Freeport", 6, "EverQuest")
        self._edge(west, pok, "west-to-pok")
        self._edge(pok, north, "pok-to-north")

        decision = zone_profile_decision(self.db, pok, "p99")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "post_velious_override")

        self.assertEqual(shortest_path_for_profile(self.db, west, north, "p99"), [])
        unrestricted = shortest_path_for_profile(self.db, west, north, "unrestricted")
        self.assertEqual(unrestricted, [west, pok, north])

        route = build_profiled_route_result(self.db, "West Freeport", "North Freeport", "p99")
        self.assertFalse(route.ok)
        self.assertIn("unrestricted knowledge", route.text)
        self.assertIn("The Plane of Knowledge", route.text)

    def test_unrestricted_retains_mixed_era_topology(self):
        stone = self._zone("Stone Hive", 396, "The Serpent's Spine")
        pok = self._zone("The Plane of Knowledge", 202, "Planes of Power")
        north = self._zone("North Freeport", 6, "EverQuest")
        self._edge(stone, pok, "stone-to-pok")
        self._edge(pok, north, "pok-to-north")

        self.assertEqual(
            shortest_path_for_profile(self.db, stone, north, "unrestricted"),
            [stone, pok, north],
        )
        route = build_profiled_route_result(
            self.db,
            "Stone Hive",
            "North Freeport",
            "unrestricted",
        )
        self.assertTrue(route.ok)

    def test_profile_selection_is_persisted_in_user_metadata_interface(self):
        selected = set_active_world_profile(self.db, "p99")
        self.assertEqual(selected.profile_id, "p99")
        self.assertEqual(active_world_profile_id(self.db), "p99")

        selected = set_active_world_profile(self.db, "unrestricted")
        self.assertEqual(selected.profile_id, "unrestricted")
        self.assertEqual(active_world_profile_id(self.db), "unrestricted")

        # Invalid/corrupt stored values safely fall back to Live.
        self.db.set_meta("world_profile", "something-unknown")
        self.assertEqual(active_world_profile_id(self.db), "live")


if __name__ == "__main__":
    unittest.main()
