from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.packaged_ui_policy import install_packaged_ui_policy
from eqquest.quest_objective_navigation import tracked_quest_objective_navigation
from eqquest.runtime import RuntimeDatabase
from eqquest.runtime_policy import install_runtime_policy
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class QuestObjectiveNavigationTests(unittest.TestCase):
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

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _page(self, key: str, title: str, entity_type: str) -> int:
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
            source_version="mirror-2026-08-15",
        )

    def _npc(self, name: str, key: str, zone_id: int, *, y=10.0, x=20.0):
        page = self._page(key, name, "npc")
        npc = self.db.upsert_entity(
            kind="npc",
            name=name,
            external_id=key,
            source_page_id=page,
        )
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
        return npc, page

    def _quest(self, name: str, key: str):
        page = self._page(key, name, "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name=name,
            external_id=key,
            source_page_id=page,
        )
        return quest, page

    def test_current_zone_kill_objective_maps_exact_target(self):
        npc, _npc_page = self._npc("A Stone Worker", "npc:6001", self.stone)
        quest, page = self._quest("Hive Defense", "quest:9001")
        description = "Kill 1 A Stone Worker"
        self.db.add_quest_step(
            quest,
            1,
            description,
            zone="The Stone Hive",
            match={"event": "kill", "npc": "A Stone Worker", "npc_entity_id": npc, "count": 1},
            source_page_id=page,
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "objective_kill",
            quantity=1,
            source_page_id=page,
            evidence=description,
            data={"confidence": "structured"},
        )

        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )
        self.assertTrue(result.map_ready)
        self.assertFalse(result.route_ready)
        self.assertEqual(len(result.map_choices), 1)
        self.assertEqual(result.map_choices[0].location_entity_id, npc)
        self.assertEqual(result.map_choices[0].relation_label, "kill target")
        self.assertEqual(result.map_choices[0].zone_name, "The Stone Hive")

    def test_remote_kill_objective_becomes_travel_destination(self):
        npc, _npc_page = self._npc("A Blight Worker", "npc:6101", self.blight)
        quest, page = self._quest("Remote Defense", "quest:9101")
        description = "Kill 1 A Blight Worker"
        self.db.add_quest_step(
            quest,
            1,
            description,
            zone="Blightfire Moors",
            match={"event": "kill", "npc": "A Blight Worker", "npc_entity_id": npc, "count": 1},
            source_page_id=page,
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "objective_kill",
            quantity=1,
            source_page_id=page,
            evidence=description,
            data={"confidence": "structured"},
        )

        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )
        self.assertTrue(result.route_ready)
        self.assertEqual(len(result.route_choices), 1)
        self.assertEqual(result.route_choices[0].zone_name, "Blightfire Moors")
        self.assertIn("A Blight Worker (kill target)", result.route_choices[0].target_labels)

    def test_canonical_step_zone_routes_even_without_exact_coordinate(self):
        quest, page = self._quest("Go to the Moors", "quest:9201")
        self.db.add_quest_step(
            quest,
            1,
            "Investigate the Moors",
            zone="Blightfire Moors",
            match={},
            source_page_id=page,
        )

        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )
        self.assertTrue(result.route_ready)
        self.assertEqual(result.route_choices[0].zone_entity_id, self.blight)
        self.assertEqual(result.route_choices[0].location_choice_count, 0)
        self.assertIn("no exact objective coordinate", result.reason.casefold())

    def test_loot_objective_uses_quest_derived_source_creature(self):
        dropper, dropper_page = self._npc("Blight Worker", "npc:6301", self.blight)
        item_page = self._page("item:9301", "Hive Sample", "item")
        item = self.db.upsert_entity(
            kind="item",
            name="Hive Sample",
            external_id="item:9301",
            source_page_id=item_page,
        )
        quest, page = self._quest("Collect Samples", "quest:9301")
        description = "Loot 2 Hive Sample from Blight Worker"
        self.db.add_quest_step(
            quest,
            1,
            description,
            zone="Blightfire Moors",
            match={"event": "loot", "item": "Hive Sample", "item_entity_id": item, "count": 2},
            source_page_id=page,
        )
        self.db.upsert_relationship(
            quest,
            dropper,
            "objective_source_creature",
            source_page_id=page,
            evidence=description,
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            item,
            dropper,
            "drops_from",
            source_page_id=page,
            evidence=description,
            data={"derived_from": "quest_objective"},
        )

        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )
        self.assertTrue(result.route_ready)
        self.assertEqual(result.route_choices[0].zone_name, "Blightfire Moors")
        self.assertIn("Blight Worker (loot source)", result.route_choices[0].target_labels)
        self.assertIn("Allakhazam mirror-2026-08-15", result.route_choices[0].source_labels)

    def test_candidate_provider_objective_location_never_routes(self):
        self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="397",
            external_namespace="eqclient:zone",
        )
        provider_page = self._page("zone:9397", "Goru'kar Mesa", "zone")
        provider_zone = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="zone:9397",
            source_page_id=provider_page,
        )
        npc, _npc_page = self._npc("Mesa Scout", "npc:6401", provider_zone)
        quest, page = self._quest("Unsafe Mesa Objective", "quest:9401")
        description = "Kill 1 Mesa Scout"
        self.db.add_quest_step(
            quest,
            1,
            description,
            zone="",
            match={"event": "kill", "npc": "Mesa Scout", "npc_entity_id": npc, "count": 1},
            source_page_id=page,
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "objective_kill",
            source_page_id=page,
            evidence=description,
            data={"confidence": "structured"},
        )
        ProviderZoneReconciliationCatalog(self.db).reconcile()
        binding = ProviderZoneReconciliationCatalog(self.db).binding_for_provider_zone(provider_zone)
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.status, "candidate")

        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )
        self.assertFalse(result.map_ready)
        self.assertFalse(result.route_ready)
        self.assertEqual(result.status, "no_actionable_location")

    def test_finalized_runtime_preserves_objective_navigation_read_only(self):
        npc, _npc_page = self._npc("Runtime Worker", "npc:6501", self.blight)
        quest, page = self._quest("Runtime Objective", "quest:9501")
        description = "Kill 1 Runtime Worker"
        self.db.add_quest_step(
            quest,
            1,
            description,
            zone="Blightfire Moors",
            match={"event": "kill", "npc_entity_id": npc, "npc": "Runtime Worker", "count": 1},
            source_page_id=page,
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "objective_kill",
            source_page_id=page,
            evidence=description,
            data={"confidence": "structured"},
        )
        builder = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )
        self.assertTrue(builder.route_ready)

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="quest-objective-navigation-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            packaged = tracked_quest_objective_navigation(
                runtime, quest, "The Stone Hive", step_order=1
            )
            self.assertEqual(packaged, builder)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_locations SET x=999")
        finally:
            runtime.close()

    def test_packaged_live_action_routes_remote_objective_through_travel(self):
        npc, _npc_page = self._npc("Travel Worker", "npc:6601", self.blight)
        quest, page = self._quest("Travel Objective", "quest:9601")
        description = "Kill 1 Travel Worker"
        self.db.add_quest_step(
            quest,
            1,
            description,
            zone="Blightfire Moors",
            match={"event": "kill", "npc_entity_id": npc, "npc": "Travel Worker", "count": 1},
            source_page_id=page,
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "objective_kill",
            source_page_id=page,
            evidence=description,
            data={"confidence": "structured"},
        )
        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )
        self.assertTrue(result.route_ready)

        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        status = _Status()
        routed: list[str] = []
        selected_tabs: list[object] = []
        travel_tab = SimpleNamespace(route_to_zone=lambda zone: routed.append(str(zone)) or True)
        fake = SimpleNamespace(
            status=status,
            travel_tab=travel_tab,
            notebook=SimpleNamespace(select=lambda tab: selected_tabs.append(tab)),
            _selected_objective_navigation=lambda: result,
            _refresh_objective_navigation_status=lambda: None,
        )
        app_module.EverQuestieApp._navigate_selected_tracked_objective(fake)
        self.assertEqual(routed, ["Blightfire Moors"])
        self.assertEqual(selected_tabs, [travel_tab])
        self.assertIn("active objective", status.value.casefold())

    def test_packaged_live_action_maps_same_zone_objective(self):
        npc, _npc_page = self._npc("Local Worker", "npc:6701", self.stone)
        quest, page = self._quest("Local Objective", "quest:9701")
        description = "Kill 1 Local Worker"
        self.db.add_quest_step(
            quest,
            1,
            description,
            zone="The Stone Hive",
            match={"event": "kill", "npc_entity_id": npc, "npc": "Local Worker", "count": 1},
            source_page_id=page,
        )
        self.db.upsert_relationship(
            quest,
            npc,
            "objective_kill",
            source_page_id=page,
            evidence=description,
            data={"confidence": "structured"},
        )
        result = tracked_quest_objective_navigation(
            self.db, quest, "The Stone Hive", step_order=1
        )
        self.assertTrue(result.map_ready)

        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        emitted: list[tuple] = []
        fake = SimpleNamespace(
            status=_Status(),
            _selected_objective_navigation=lambda: result,
            _refresh_objective_navigation_status=lambda: None,
            _focus_navigation_map_target=lambda *args: emitted.append(args),
        )
        app_module.EverQuestieApp._navigate_selected_tracked_objective(fake)
        choice = result.map_choices[0]
        self.assertEqual(
            emitted,
            [(choice.zone_name, choice.x, choice.y, choice.z, choice.map_label)],
        )


if __name__ == "__main__":
    unittest.main()
