from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.loot_turn_in_navigation import loot_turn_in_navigation


class LootTurnInNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.current_zone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.remote_zone = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _page(self, key: str, title: str, entity_type: str) -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/{key.replace(':', '/')}",
            title=title,
            entity_type=entity_type,
            sha256=f"sha-{key}",
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="mirror-test",
        )

    def _quest(self, name: str = "Bark for the Brewer") -> tuple[int, int]:
        page = self._page("quest:7001", name, "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name=name,
            external_id="quest:7001",
            source_page_id=page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=7001",
        )
        return quest, page

    def _npc(
        self,
        name: str,
        external_id: str,
        zone_id: int | None,
        *,
        y: float = 10.0,
        x: float = 20.0,
    ) -> int:
        page = self._page(external_id, name, "npc")
        npc = self.db.upsert_entity(
            kind="npc",
            name=name,
            external_id=external_id,
            source_page_id=page,
            source_url=f"https://everquest.allakhazam.com/db/npc.html?id={external_id}",
        )
        if zone_id is not None:
            self.db.add_location(
                npc,
                zone_entity_id=zone_id,
                y=y,
                x=x,
                z=5.0,
                label="known location",
                source_page_id=page,
                evidence=f"{name} at {y}, {x}",
            )
        return npc

    def test_current_zone_maps_only_explicit_turn_in_contact(self):
        quest, page = self._quest()
        starter = self._npc("Starter Sela", "npc:7101", self.current_zone, y=1.0, x=2.0)
        turnin = self._npc("Brewer Brolin", "npc:7102", self.current_zone, y=30.0, x=40.0)
        self.db.upsert_relationship(
            quest,
            starter,
            "started_by",
            source_page_id=page,
            evidence="Quest Started By: Starter Sela",
        )
        self.db.upsert_relationship(
            quest,
            turnin,
            "objective_turn_in_to",
            source_page_id=page,
            evidence="Give Bog Bark to Brewer Brolin.",
        )

        result = loot_turn_in_navigation(self.db, quest, "The Stone Hive")
        self.assertEqual(result.status, "map_ready")
        self.assertTrue(result.map_ready)
        self.assertFalse(result.route_ready)
        self.assertEqual(len(result.map_choices), 1)
        choice = result.map_choices[0]
        self.assertEqual(choice.location_entity_id, turnin)
        self.assertEqual(choice.location_entity_name, "Brewer Brolin")
        self.assertEqual(choice.relation, "objective_turn_in_to")
        self.assertEqual(choice.relation_label, "turn-in NPC")
        self.assertEqual((choice.y, choice.x), (30.0, 40.0))
        self.assertNotEqual(choice.location_entity_id, starter)

    def test_remote_turn_in_becomes_canonical_route_destination(self):
        quest, page = self._quest("Remote Bark")
        turnin = self._npc("Remote Brewer", "npc:7201", self.remote_zone)
        self.db.upsert_relationship(
            quest,
            turnin,
            "objective_turn_in_to",
            source_page_id=page,
            evidence="Give the bark to Remote Brewer.",
        )

        result = loot_turn_in_navigation(self.db, quest, "The Stone Hive")
        self.assertEqual(result.status, "route_ready")
        self.assertFalse(result.map_ready)
        self.assertTrue(result.route_ready)
        self.assertEqual(len(result.route_choices), 1)
        route = result.route_choices[0]
        self.assertEqual(route.zone_entity_id, self.remote_zone)
        self.assertEqual(route.zone_name, "Blightfire Moors")
        self.assertEqual(route.target_labels, ("Remote Brewer (turn-in NPC)",))

    def test_known_contact_without_safe_location_stays_non_actionable(self):
        quest, page = self._quest("Unmapped Turn-In")
        turnin = self._npc("Hidden Brewer", "npc:7301", None)
        self.db.upsert_relationship(
            quest,
            turnin,
            "objective_turn_in_to",
            source_page_id=page,
            evidence="Give the bark to Hidden Brewer.",
        )

        result = loot_turn_in_navigation(self.db, quest, "The Stone Hive")
        self.assertEqual(result.status, "contact_location_unavailable")
        self.assertFalse(result.navigable)
        self.assertIn("Hidden Brewer", result.reason)
        self.assertIn("no safe canonical Map/Travel location", result.reason)

    def test_unproven_turn_in_relationship_is_not_navigation_evidence(self):
        quest, _page = self._quest("Unproven Turn-In")
        turnin = self._npc("Rumored Brewer", "npc:7401", self.current_zone)
        self.db.upsert_relationship(
            quest,
            turnin,
            "objective_turn_in_to",
            evidence="synthetic relation without source provenance",
        )

        result = loot_turn_in_navigation(self.db, quest, "The Stone Hive")
        self.assertEqual(result.status, "no_explicit_turn_in_contact")
        self.assertFalse(result.navigable)

    def test_missing_current_zone_does_not_guess_map_or_route(self):
        quest, page = self._quest("Unknown Position Turn-In")
        turnin = self._npc("Located Brewer", "npc:7501", self.remote_zone)
        self.db.upsert_relationship(
            quest,
            turnin,
            "objective_turn_in_to",
            source_page_id=page,
            evidence="Give the item to Located Brewer.",
        )

        result = loot_turn_in_navigation(self.db, quest, None)
        self.assertEqual(result.status, "no_current_zone")
        self.assertFalse(result.navigable)
        self.assertIn("Current zone", result.reason)


if __name__ == "__main__":
    unittest.main()
