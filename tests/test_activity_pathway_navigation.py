from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.activity_pathway_navigation import pathway_contact_navigation
from eqquest.db import Database


class ActivityPathwayNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")
        self.current_zone = self.db.upsert_entity(
            kind="zone",
            name="Current Test Zone",
            external_id="101",
            external_namespace="eqclient:zone",
        )
        self.remote_zone = self.db.upsert_entity(
            kind="zone",
            name="Remote Test Zone",
            external_id="102",
            external_namespace="eqclient:zone",
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _page(self, key: str, entity_type: str = "quest") -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/db/{entity_type}.html?id={key}",
            title=f"Source {key}",
            entity_type=entity_type,
            sha256=f"sha-{key}",
            plain_text=f"Source {key}",
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=f"{entity_type}:{key}",
        )

    def _npc(self, name: str, external_id: str, zone_id: int, y: float, x: float) -> int:
        page = self._page(external_id, "npc")
        npc = self.db.upsert_entity(
            kind="npc",
            name=name,
            external_id=external_id,
            source_page_id=page,
        )
        self.db.add_location(
            npc,
            zone_entity_id=zone_id,
            y=y,
            x=x,
            z=1.0,
            label="known location",
            source_page_id=page,
            evidence=f"{name} at {y}, {x}",
        )
        return npc

    def _quest(self, name: str = "Pathway Quest") -> tuple[int, int]:
        page = self._page("quest-contact")
        quest = self.db.upsert_entity(
            kind="quest",
            name=name,
            external_id="quest:pathway-contact",
            source_page_id=page,
        )
        return quest, page

    def test_current_zone_starter_is_map_ready_and_preferred_over_turn_in(self):
        quest, page = self._quest()
        starter = self._npc("Starter Test", "npc:starter", self.current_zone, 10.0, 20.0)
        turnin = self._npc("Turnin Test", "npc:turnin", self.current_zone, 30.0, 40.0)
        self.db.upsert_relationship(
            quest,
            starter,
            "started_by",
            source_page_id=page,
            evidence="Quest Started By: Starter Test",
        )
        self.db.upsert_relationship(
            quest,
            turnin,
            "objective_turn_in_to",
            source_page_id=page,
            evidence="Give token to Turnin Test",
        )

        result = pathway_contact_navigation(self.db, quest, "Current Test Zone")
        self.assertTrue(result.map_ready)
        self.assertFalse(result.route_ready)
        self.assertEqual(result.contact_kind, "quest starter")
        self.assertEqual([choice.location_entity_id for choice in result.map_choices], [starter])

    def test_remote_starter_becomes_explicit_travel_destination(self):
        quest, page = self._quest()
        starter = self._npc("Remote Starter", "npc:remote-starter", self.remote_zone, 1.0, 2.0)
        self.db.upsert_relationship(
            quest,
            starter,
            "started_by",
            source_page_id=page,
            evidence="remote starter",
        )

        result = pathway_contact_navigation(self.db, quest, "Current Test Zone")
        self.assertFalse(result.map_ready)
        self.assertTrue(result.route_ready)
        self.assertEqual(result.contact_kind, "quest starter")
        self.assertEqual(len(result.route_choices), 1)
        self.assertEqual(result.route_choices[0].zone_entity_id, self.remote_zone)
        self.assertEqual(result.route_choices[0].zone_name, "Remote Test Zone")

    def test_turn_in_is_fallback_only_when_no_navigable_starter_is_known(self):
        quest, page = self._quest()
        starter = self.db.upsert_entity(kind="npc", name="Unmapped Starter", external_id="npc:unmapped")
        turnin = self._npc("Mapped Turnin", "npc:mapped-turnin", self.current_zone, 5.0, 6.0)
        self.db.upsert_relationship(
            quest,
            starter,
            "started_by",
            source_page_id=page,
            evidence="starter exists but has no safe location",
        )
        self.db.upsert_relationship(
            quest,
            turnin,
            "objective_turn_in_to",
            source_page_id=page,
            evidence="turn in here",
        )

        result = pathway_contact_navigation(self.db, quest, "Current Test Zone")
        self.assertTrue(result.map_ready)
        self.assertEqual(result.contact_kind, "turn-in NPC")
        self.assertEqual(result.map_choices[0].location_entity_id, turnin)

    def test_other_objective_actor_is_not_substituted_for_quest_contact(self):
        quest, page = self._quest()
        target = self._npc("Quest Target", "npc:target", self.current_zone, 7.0, 8.0)
        self.db.upsert_relationship(
            quest,
            target,
            "objective_kill",
            source_page_id=page,
            evidence="Kill Quest Target",
        )

        result = pathway_contact_navigation(self.db, quest, "Current Test Zone")
        self.assertFalse(result.map_ready)
        self.assertFalse(result.route_ready)
        self.assertEqual(result.status, "no_contact_location")
        self.assertIn("starter or turn-in NPC", result.reason)

    def test_multiple_remote_starter_zones_remain_explicit_choices(self):
        quest, page = self._quest()
        third_zone = self.db.upsert_entity(
            kind="zone",
            name="Third Test Zone",
            external_id="103",
            external_namespace="eqclient:zone",
        )
        first = self._npc("Starter One", "npc:one", self.remote_zone, 1.0, 2.0)
        second = self._npc("Starter Two", "npc:two", third_zone, 3.0, 4.0)
        for npc, text in ((first, "starter one"), (second, "starter two")):
            self.db.upsert_relationship(
                quest,
                npc,
                "started_by",
                source_page_id=page,
                evidence=text,
            )

        result = pathway_contact_navigation(self.db, quest, "Current Test Zone")
        self.assertTrue(result.route_ready)
        self.assertEqual(len(result.route_choices), 2)
        self.assertEqual(
            {choice.zone_name for choice in result.route_choices},
            {"Remote Test Zone", "Third Test Zone"},
        )


if __name__ == "__main__":
    unittest.main()
