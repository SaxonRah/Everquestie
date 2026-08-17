from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from eqquest.current_zone_dashboard import (
    build_current_zone_dashboard,
    current_zone_dashboard_text,
)
from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.route_guidance_ui import RouteGuidanceFrame
from eqquest.runtime import RuntimeDatabase
from eqquest.travel import TravelFrame
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog
from eqquest.zone_travel import ZoneTravelCatalog


class _Var:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class CurrentZoneDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

        self.stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )
        self.mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="397",
            external_namespace="eqclient:zone",
        )

        stone_page = self._source("zone:351", "The Stone Hive", "zone")
        provider_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            source_page_id=stone_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=351",
            external_id="zone:351",
        )
        provider_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=202",
            external_id="zone:202",
        )
        self.db.upsert_relationship(
            provider_stone,
            provider_blight,
            "connected_to",
            source_page_id=stone_page,
            evidence="Blightfire Moors / south",
            data={"confidence": "structured"},
        )
        ProviderZoneReconciliationCatalog(self.db).reconcile()

        npc_page = self._source("npc:1001", "Scout Fana", "npc")
        self.npc = self.db.upsert_entity(
            kind="npc",
            name="Scout Fana",
            source_page_id=npc_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1001",
            external_id="npc:1001",
        )
        quest_page = self._source("quest:5001", "A Hive Inquiry", "quest")
        self.quest = self.db.upsert_entity(
            kind="quest",
            name="A Hive Inquiry",
            source_page_id=quest_page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=5001",
            external_id="quest:5001",
        )
        item_page = self._source("item:7001", "Hive Token", "item")
        self.item = self.db.upsert_entity(
            kind="item",
            name="Hive Token",
            source_page_id=item_page,
            source_url="https://everquest.allakhazam.com/db/item.html?item=7001",
            external_id="item:7001",
        )
        located_page = self._source("npc:1002", "A Wandering Bixie", "npc")
        self.location_only = self.db.upsert_entity(
            kind="npc",
            name="A Wandering Bixie",
            source_page_id=located_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1002",
            external_id="npc:1002",
        )

        self.db.upsert_relationship(
            self.npc,
            provider_stone,
            "found_in",
            source_page_id=npc_page,
            evidence="Known Habitats: The Stone Hive",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            self.quest,
            provider_stone,
            "starts_in",
            source_page_id=quest_page,
            evidence="Quests Starting In preview",
            data={"confidence": "structured", "preview": True, "shown": 25, "total": 80},
        )
        self.db.upsert_relationship(
            self.quest,
            provider_stone,
            "occurs_in",
            source_page_id=quest_page,
            evidence="Quests In preview",
            data={"confidence": "structured", "preview": True, "shown": 25, "total": 120},
        )
        self.db.upsert_relationship(
            self.item,
            provider_stone,
            "found_in",
            source_page_id=item_page,
            evidence="Items preview",
            data={"confidence": "structured", "preview": True, "shown": 25, "total": 900},
        )
        self.db.add_location(
            self.npc,
            zone_entity_id=provider_stone,
            y=125.0,
            x=-42.0,
            z=7.0,
            label="quest starter",
            source_page_id=npc_page,
            evidence="Scout Fana at 125, -42, 7",
        )
        self.db.add_location(
            self.location_only,
            zone_entity_id=provider_stone,
            y=210.0,
            x=90.0,
            label="sighting",
            source_page_id=located_page,
            evidence="A Wandering Bixie at 210, 90",
        )

        travel = ZoneTravelCatalog(self.db)
        travel.add_provider_connection(
            self.stone,
            self.blight,
            connection_kind="zone_line",
            source_name="Test topology",
            source_key="stone->blight",
            evidence="south tunnel",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=-10,y=20,z=3 WHERE source_key='stone->blight'"
        )
        travel.add_provider_connection(
            self.mesa,
            self.stone,
            connection_kind="portal",
            source_name="Test topology",
            source_key="mesa->stone",
            evidence="one-way portal into Stone Hive",
        )
        self.db.conn.execute(
            "UPDATE zone_travel_edges SET x=900,y=800,z=20 WHERE source_key='mesa->stone'"
        )
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _source(self, key: str, title: str, entity_type: str) -> int:
        return self.db.upsert_source_page(
            url=f"https://everquest.allakhazam.com/{key.replace(':', '/')}",
            title=title,
            entity_type=entity_type,
            sha256=key,
            plain_text=title,
            raw_html="<html></html>",
            source_name="Allakhazam",
            source_kind="local_mirror",
            source_key=key,
            source_version="mirror-2026-08-14",
        )

    def test_dashboard_aggregates_roles_preview_and_independent_locations(self):
        dashboard, status = build_current_zone_dashboard(self.db, "The Stone Hive")
        self.assertEqual(status, "linked")
        self.assertIsNotNone(dashboard)
        assert dashboard is not None

        by_id = {row.entity_id: row for row in dashboard.entities}
        self.assertEqual(
            set(by_id[self.quest].roles),
            {"Quest starts here", "Quest occurs here"},
        )
        self.assertEqual(by_id[self.quest].preview_fact_count, 2)
        self.assertEqual(by_id[self.npc].location_count, 1)
        self.assertEqual(
            set(by_id[self.npc].roles),
            {"Known NPC", "Located here"},
        )
        self.assertEqual(by_id[self.location_only].roles, ("Located here",))
        self.assertEqual(by_id[self.location_only].relationship_ids, ())
        self.assertEqual(dashboard.located_entity_count, 2)

        choices = {row.entity_id: row for row in dashboard.choices if row.kind != "zone"}
        self.assertEqual(choices[self.quest].category, "Quest")
        self.assertEqual(choices[self.location_only].category, "NPC")
        self.assertIn("Allakhazam mirror-2026-08-14", choices[self.npc].source_text)

    def test_provider_coordinates_do_not_make_topology_edges_mappable(self):
        dashboard, _ = build_current_zone_dashboard(self.db, "The Stone Hive")
        assert dashboard is not None
        self.assertEqual(len(dashboard.exits), 2)
        outgoing = next(row for row in dashboard.exits if row.zone_entity_id == self.blight)
        incoming = next(row for row in dashboard.exits if row.zone_entity_id == self.mesa)

        self.assertTrue(outgoing.usable)
        self.assertFalse(outgoing.source_owned_coordinate)
        self.assertIn("Exit via zone line", outgoing.role_text)
        self.assertFalse(incoming.usable)
        self.assertFalse(incoming.source_owned_coordinate)
        self.assertIn("Incoming-only portal", incoming.role_text)
        self.assertEqual(dashboard.usable_exit_count, 1)
        self.assertEqual(dashboard.mappable_exit_count, 0)

        text = current_zone_dashboard_text(self.db, "The Stone Hive")
        self.assertIn("usable exits: 1", text)
        self.assertIn("mappable exits: 0", text)
        self.assertIn("Incoming-only portal", text)
        self.assertNotIn("source-side coordinate", text)
        self.assertIn("Evidence-backed entities (not exhaustive):", text)

    def test_finalized_runtime_exposes_same_dashboard_read_only(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="current-zone-dashboard-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            builder, _ = build_current_zone_dashboard(self.db, "The Stone Hive")
            packaged, status = build_current_zone_dashboard(runtime, "The Stone Hive")
            self.assertEqual(status, "linked")
            self.assertIsNotNone(packaged)
            assert builder is not None and packaged is not None
            self.assertEqual(
                [(row.entity_id, row.roles, row.location_count) for row in packaged.entities],
                [(row.entity_id, row.roles, row.location_count) for row in builder.entities],
            )
            self.assertEqual(
                [(row.zone_entity_id, row.usable, row.source_owned_coordinate) for row in packaged.exits],
                [(row.zone_entity_id, row.usable, row.source_owned_coordinate) for row in builder.exits],
            )
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_relationships SET relation='mutated'")
        finally:
            runtime.close()

    def test_travel_dashboard_hands_selected_exact_id_to_knowledge_owner(self):
        dashboard, _ = build_current_zone_dashboard(self.db, "The Stone Hive")
        assert dashboard is not None
        choice = next(row for row in dashboard.choices if row.entity_id == self.quest)

        fake = type("FakeTravel", (), {})()
        fake.db = self.db
        fake.status_var = _Var()
        fake.on_knowledge_entity = lambda entity_id: opened.append(int(entity_id)) or True
        fake._clear_nearby_points = lambda: None
        fake._selected_or_current_zone = lambda: "The Stone Hive"
        rendered = []
        fake._set_result = lambda text: rendered.append(text)
        opened: list[int] = []

        with patch.object(TravelFrame, "_ensure_navigation_catalog_ready", return_value=True), patch(
            "eqquest.route_guidance_ui.ask_current_zone_dashboard",
            return_value=choice,
        ):
            self.assertTrue(RouteGuidanceFrame.show_current_zone_dashboard(fake))

        self.assertEqual(opened, [self.quest])
        self.assertTrue(rendered and "WHAT'S HERE | The Stone Hive" in rendered[0])
        self.assertIn("Opened Knowledge", fake.status_var.value)

    def test_ambiguous_zone_dashboard_never_opens_knowledge(self):
        duplicate = self.db.upsert_entity(
            kind="zone",
            name="Duplicate Landing",
            external_id="900",
            external_namespace="eqclient:zone",
        )
        self.db.upsert_entity(
            kind="zone",
            name="Duplicate Landing",
            external_id="901",
            external_namespace="eqclient:zone",
        )
        self.assertGreater(duplicate, 0)

        fake = type("FakeTravel", (), {})()
        fake.db = self.db
        fake.status_var = _Var()
        opened: list[int] = []
        fake.on_knowledge_entity = lambda entity_id: opened.append(int(entity_id)) or True
        fake._clear_nearby_points = lambda: None
        fake._selected_or_current_zone = lambda: "Duplicate Landing"
        fake._set_result = lambda _text: None

        with patch.object(TravelFrame, "_ensure_navigation_catalog_ready", return_value=True), patch(
            "eqquest.route_guidance_ui.ask_current_zone_dashboard"
        ) as chooser:
            self.assertFalse(RouteGuidanceFrame.show_current_zone_dashboard(fake))

        chooser.assert_not_called()
        self.assertEqual(opened, [])
        self.assertIn("ambiguous", fake.status_var.value.casefold())


if __name__ == "__main__":
    unittest.main()
