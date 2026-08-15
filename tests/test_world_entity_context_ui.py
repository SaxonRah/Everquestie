from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest import app as app_module
from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.world_entity_context_ui import (
    WorldEntityMapTarget,
    install_world_entity_context_ui,
    map_selected_world_entity_location,
    world_entity_map_targets,
)
from eqquest.world_entity_detail import build_world_entity_context_for_id
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class _FakeSelectionTree:
    def __init__(self, selected: str | None = None):
        self.selected = selected

    def selection(self):
        return (self.selected,) if self.selected else ()


class _FakeStringVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class WorldEntityContextUITests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db = Database(self.root / "working.sqlite3")

        self.client_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.client_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )
        self.client_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="397",
            external_namespace="eqclient:zone",
        )

        stone_page = self._source_page("zone:351", "The Stone Hive", "zone")
        blight_page = self._source_page("zone:202", "Blightfire Moors", "zone")
        mesa_page = self._source_page("zone:397", "Goru'kar Mesa", "zone")
        self.provider_stone = self.db.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            source_page_id=stone_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=351",
            external_id="zone:351",
        )
        self.provider_blight = self.db.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            source_page_id=blight_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=202",
            external_id="zone:202",
        )
        self.provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            source_page_id=mesa_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=397",
            external_id="zone:397",
        )
        self.db.upsert_relationship(
            self.provider_stone,
            self.provider_blight,
            "connected_to",
            source_page_id=stone_page,
            evidence="Blightfire Moors / south",
            data={"confidence": "structured", "direction": "south"},
        )
        ProviderZoneReconciliationCatalog(self.db).reconcile()

        npc_page = self._source_page("npc:1001", "Scout Fana", "npc")
        self.scout = self.db.upsert_entity(
            kind="npc",
            name="Scout Fana",
            source_page_id=npc_page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=1001",
            external_id="npc:1001",
        )
        self.db.add_location(
            self.scout,
            zone_entity_id=self.provider_stone,
            y=125.0,
            x=-42.0,
            z=7.0,
            label="quest starter",
            source_page_id=npc_page,
            evidence="Scout Fana at 125, -42, 7",
        )
        self.db.add_location(
            self.scout,
            zone_entity_id=self.provider_mesa,
            y=10.0,
            x=20.0,
            label="candidate-zone report",
            source_page_id=npc_page,
            evidence="Unreconciled Mesa sighting",
        )

        quest_page = self._source_page("quest:5001", "A Hive Inquiry", "quest")
        self.quest = self.db.upsert_entity(
            kind="quest",
            name="A Hive Inquiry",
            source_page_id=quest_page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=5001",
            external_id="quest:5001",
        )
        self.db.upsert_relationship(
            self.quest,
            self.scout,
            "started_by",
            source_page_id=quest_page,
            evidence="Quest Started By: Scout Fana",
            data={"confidence": "structured"},
        )
        self.db.add_quest_step(
            self.quest,
            1,
            "Speak with Scout Fana",
            zone="The Stone Hive",
            match={"event": "npc_say", "npc_entity_id": self.scout, "count": 1},
            source_page_id=quest_page,
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _source_page(self, key: str, title: str, entity_type: str) -> int:
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

    def test_linked_provider_location_is_map_ready_and_candidate_is_not(self):
        context = build_world_entity_context_for_id(self.db, self.scout)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(len(context.locations), 2)

        targets = world_entity_map_targets(context)
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target.zone_entity_id, self.client_stone)
        self.assertEqual(target.zone_name, "The Stone Hive")
        self.assertEqual((target.x, target.y, target.z), (-42.0, 125.0, 7.0))
        self.assertEqual(target.loc_text, "Y=125 X=-42 Z=7")
        self.assertEqual(target.label, "quest starter")

        candidate = next(row for row in context.locations if row.label == "candidate-zone report")
        self.assertEqual(candidate.zone_projection_status, "provider_candidate")
        self.assertFalse(candidate.navigable)

    def test_quest_actor_location_uses_same_safe_target_projection(self):
        context = build_world_entity_context_for_id(self.db, self.quest)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(len(context.related_locations), 2)

        targets = world_entity_map_targets(context)
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertTrue(target.related)
        self.assertEqual(target.relation, "started_by")
        self.assertEqual(target.entity_id, self.scout)
        self.assertEqual(target.zone_entity_id, self.client_stone)
        self.assertIn("Started by: Scout Fana", target.label)

    def test_map_action_delegates_exact_game_space_target_to_existing_owner(self):
        target = WorldEntityMapTarget(
            location_id=7,
            entity_id=self.scout,
            entity_name="Scout Fana",
            relation="self",
            zone_entity_id=self.client_stone,
            zone_name="The Stone Hive",
            x=-42.0,
            y=125.0,
            z=7.0,
            label="quest starter",
            source_label="Allakhazam mirror-2026-08-14",
            related=False,
        )
        app = type("FakeApp", (), {})()
        app.world_entity_location_tree = _FakeSelectionTree("row")
        app._world_entity_target_by_item = {"row": target}
        app.world_entity_location_status = _FakeStringVar()
        calls = []
        app._focus_navigation_map_target = lambda *args: calls.append(args)

        self.assertTrue(map_selected_world_entity_location(app))
        self.assertEqual(
            calls,
            [("The Stone Hive", -42.0, 125.0, 7.0, "quest starter")],
        )

    def test_finalized_runtime_exposes_same_target_subset_read_only(self):
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="world-entity-context-ui-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            context = build_world_entity_context_for_id(runtime, self.scout)
            self.assertIsNotNone(context)
            targets = world_entity_map_targets(context)
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0].zone_entity_id, self.client_stone)
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_locations SET x=0")
        finally:
            runtime.close()

    def test_installer_subclasses_current_app_and_preserves_parent_show(self):
        original = app_module.EverQuestieApp

        class FakeBase:
            def _show_entity(self):
                self.base_show_called = True

            def _build_knowledge(self):
                self.base_build_called = True

            def _selected_entity_id(self):
                return None

        try:
            app_module.EverQuestieApp = FakeBase
            install_world_entity_context_ui()
            installed = app_module.EverQuestieApp
            self.assertTrue(issubclass(installed, FakeBase))
            instance = object.__new__(installed)
            instance._show_entity()
            self.assertTrue(instance.base_show_called)
        finally:
            app_module.EverQuestieApp = original


if __name__ == "__main__":
    unittest.main()
