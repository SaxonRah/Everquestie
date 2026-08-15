from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_location_ui import (
    ask_knowledge_map_choice,
    knowledge_map_choice_labels,
)
from eqquest.knowledge_map_choices import knowledge_map_choices
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.packaged_ui_policy import install_packaged_ui_policy
from eqquest.runtime import RuntimeDatabase
from eqquest.runtime_policy import install_runtime_policy
from eqquest.zone_provider_reconciliation import ProviderZoneReconciliationCatalog


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class KnowledgeLocationChoiceTests(unittest.TestCase):
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
            source_version="mirror-2026-08-14",
        )

    def _npc(self, name: str, external_id: str, y: float, x: float) -> int:
        page = self._page(external_id, name, "npc")
        npc = self.db.upsert_entity(
            kind="npc",
            name=name,
            external_id=external_id,
            source_page_id=page,
            source_url=f"https://everquest.allakhazam.com/db/npc.html?id={external_id}",
        )
        self.db.add_location(
            npc,
            zone_entity_id=self.stone,
            y=y,
            x=x,
            z=5.0,
            label="known location",
            source_page_id=page,
            evidence=f"{name} at {y}, {x}",
        )
        return npc

    def test_multiple_direct_points_are_returned_as_choices_not_auto_selected(self):
        npc = self._npc("Wandering Scout", "npc:3001", 10.0, 20.0)
        self.db.add_location(
            npc,
            zone_entity_id=self.stone,
            y=30.0,
            x=40.0,
            z=5.0,
            label="second spawn",
            evidence="second point",
        )
        result = knowledge_map_choices(self.db, npc, "The Stone Hive")
        self.assertTrue(result.ready)
        self.assertEqual(len(result.choices), 2)
        self.assertEqual({choice.origin for choice in result.choices}, {"entity"})
        self.assertEqual(
            {(choice.y, choice.x) for choice in result.choices},
            {(10.0, 20.0), (30.0, 40.0)},
        )

    def test_quest_exposes_explicit_starter_and_objective_actor_locations(self):
        starter = self._npc("Scout Fana", "npc:3101", 100.0, -50.0)
        target = self._npc("A Stone Worker", "npc:3102", 200.0, -75.0)
        page = self._page("quest:6101", "A Hive Inquiry", "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name="A Hive Inquiry",
            external_id="quest:6101",
            source_page_id=page,
            source_url="https://everquest.allakhazam.com/db/quest.html?quest=6101",
        )
        self.db.upsert_relationship(
            quest,
            starter,
            "started_by",
            source_page_id=page,
            evidence="Quest Started By: Scout Fana",
            data={"confidence": "structured"},
        )
        self.db.upsert_relationship(
            quest,
            target,
            "objective_kill",
            source_page_id=page,
            evidence="Kill A Stone Worker",
            data={"derived_from": "quest_objective"},
        )

        result = knowledge_map_choices(self.db, quest, "The Stone Hive")
        self.assertTrue(result.ready)
        self.assertEqual(len(result.choices), 2)
        by_name = {choice.location_entity_name: choice for choice in result.choices}
        self.assertEqual(by_name["Scout Fana"].relation_label, "quest starter")
        self.assertEqual(by_name["A Stone Worker"].relation_label, "kill target")
        self.assertEqual(by_name["Scout Fana"].origin, "quest_actor")
        self.assertEqual(by_name["A Stone Worker"].zone_entity_id, self.stone)
        self.assertIn("quest starter", by_name["Scout Fana"].map_label)

    def test_other_zone_actor_is_not_offered_on_current_map(self):
        page = self._page("npc:3201", "Remote Scout", "npc")
        actor = self.db.upsert_entity(
            kind="npc",
            name="Remote Scout",
            external_id="npc:3201",
            source_page_id=page,
            source_url="https://everquest.allakhazam.com/db/npc.html?id=3201",
        )
        self.db.add_location(
            actor,
            zone_entity_id=self.blight,
            y=1.0,
            x=2.0,
            label="remote",
            source_page_id=page,
            evidence="remote actor",
        )
        quest_page = self._page("quest:6201", "Remote Inquiry", "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name="Remote Inquiry",
            external_id="quest:6201",
            source_page_id=quest_page,
        )
        self.db.upsert_relationship(
            quest,
            actor,
            "started_by",
            source_page_id=quest_page,
            evidence="remote starter",
            data={"confidence": "structured"},
        )
        result = knowledge_map_choices(self.db, quest, "The Stone Hive")
        self.assertFalse(result.ready)
        self.assertEqual(result.status, "not_in_current_zone")
        self.assertEqual(result.other_zone_choice_count, 1)

    def test_candidate_provider_quest_actor_is_not_offered_as_gameplay_target(self):
        mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="397",
            external_namespace="eqclient:zone",
        )
        provider_page = self._page("zone:397", "Goru'kar Mesa", "zone")
        provider_mesa = self.db.upsert_entity(
            kind="zone",
            name="Goru'kar Mesa",
            external_id="zone:397",
            source_page_id=provider_page,
            source_url="https://everquest.allakhazam.com/db/zone.html?zstrat=397",
        )
        actor_page = self._page("npc:3251", "Mesa Scout", "npc")
        actor = self.db.upsert_entity(
            kind="npc",
            name="Mesa Scout",
            external_id="npc:3251",
            source_page_id=actor_page,
        )
        self.db.add_location(
            actor,
            zone_entity_id=provider_mesa,
            y=11.0,
            x=22.0,
            z=3.0,
            label="reported spawn",
            source_page_id=actor_page,
            evidence="provider Mesa spawn",
        )
        quest_page = self._page("quest:6251", "Mesa Inquiry", "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name="Mesa Inquiry",
            external_id="quest:6251",
            source_page_id=quest_page,
        )
        self.db.upsert_relationship(
            quest,
            actor,
            "started_by",
            source_page_id=quest_page,
            evidence="Mesa Scout starts the quest",
            data={"confidence": "structured"},
        )
        ProviderZoneReconciliationCatalog(self.db).reconcile()
        binding = ProviderZoneReconciliationCatalog(self.db).binding_for_provider_zone(provider_mesa)
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.status, "candidate")

        result = knowledge_map_choices(self.db, quest, "Goru'kar Mesa")
        self.assertFalse(result.ready)
        self.assertEqual(result.status, "no_navigable_location")
        self.assertEqual(result.choices, ())
        self.assertEqual(result.current_zone_entity_id, mesa)

    def test_choice_labels_show_relation_loc_source_and_evidence_count(self):
        starter = self._npc("Scout Fana", "npc:3301", 100.0, -50.0)
        page = self._page("quest:6301", "Label Quest", "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name="Label Quest",
            external_id="quest:6301",
            source_page_id=page,
        )
        self.db.upsert_relationship(
            quest,
            starter,
            "started_by",
            source_page_id=page,
            evidence="starter",
            data={"confidence": "structured"},
        )
        result = knowledge_map_choices(self.db, quest, "The Stone Hive")
        labels = knowledge_map_choice_labels(result.choices)
        self.assertEqual(len(labels), 1)
        self.assertIn("Scout Fana (quest starter)", labels[0])
        self.assertIn("Y=100 X=-50 Z=5", labels[0])
        self.assertIn("Allakhazam mirror-2026-08-14", labels[0])
        self.assertIn("1 evidence row", labels[0])
        self.assertIs(ask_knowledge_map_choice(None, "Label Quest", "The Stone Hive", result.choices), result.choices[0])

    def test_finalized_runtime_exposes_same_quest_actor_choices_read_only(self):
        starter = self._npc("Runtime Scout", "npc:3351", 77.0, -33.0)
        page = self._page("quest:6351", "Runtime Inquiry", "quest")
        quest = self.db.upsert_entity(
            kind="quest",
            name="Runtime Inquiry",
            external_id="quest:6351",
            source_page_id=page,
        )
        self.db.upsert_relationship(
            quest,
            starter,
            "started_by",
            source_page_id=page,
            evidence="runtime starter",
            data={"confidence": "structured"},
        )
        builder = knowledge_map_choices(self.db, quest, "The Stone Hive")
        self.assertTrue(builder.ready)
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="knowledge-location-chooser-test",
        )
        runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        try:
            packaged = knowledge_map_choices(runtime, quest, "The Stone Hive")
            self.assertEqual(packaged.status, builder.status)
            self.assertEqual(packaged.choices, builder.choices)
            self.assertEqual(packaged.choices[0].relation_label, "quest starter")
            with self.assertRaises(Exception):
                runtime.conn.execute("UPDATE entity_locations SET x=999")
        finally:
            runtime.close()

    def test_packaged_action_uses_explicit_choice_for_multiple_safe_points(self):
        npc = self._npc("Wandering Scout", "npc:3401", 10.0, 20.0)
        self.db.add_location(
            npc,
            zone_entity_id=self.stone,
            y=30.0,
            x=40.0,
            z=5.0,
            label="second spawn",
            evidence="second point",
        )
        choices = knowledge_map_choices(self.db, npc, "The Stone Hive").choices
        self.assertEqual(len(choices), 2)
        chosen = choices[1]

        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        status = _Status()
        emitted: list[tuple] = []
        fake = SimpleNamespace(
            db=self.db,
            state_model=SimpleNamespace(current_zone="The Stone Hive"),
            status=status,
            _selected_entity_id=lambda: npc,
            _focus_navigation_map_target=lambda *args: emitted.append(args),
        )
        with patch(
            "eqquest.knowledge_location_ui.ask_knowledge_map_choice",
            return_value=chosen,
        ):
            app_module.EverQuestieApp._map_selected_knowledge_location(fake)
        self.assertEqual(
            emitted,
            [(
                chosen.zone_name,
                chosen.x,
                chosen.y,
                chosen.z,
                chosen.map_label,
            )],
        )

    def test_packaged_action_cancel_never_hands_off(self):
        npc = self._npc("Wandering Scout", "npc:3501", 10.0, 20.0)
        self.db.add_location(
            npc,
            zone_entity_id=self.stone,
            y=30.0,
            x=40.0,
            z=5.0,
            label="second spawn",
            evidence="second point",
        )
        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        status = _Status()
        emitted: list[tuple] = []
        fake = SimpleNamespace(
            db=self.db,
            state_model=SimpleNamespace(current_zone="The Stone Hive"),
            status=status,
            _selected_entity_id=lambda: npc,
            _focus_navigation_map_target=lambda *args: emitted.append(args),
        )
        with patch(
            "eqquest.knowledge_location_ui.ask_knowledge_map_choice",
            return_value=None,
        ):
            app_module.EverQuestieApp._map_selected_knowledge_location(fake)
        self.assertEqual(emitted, [])
        self.assertIn("cancelled", status.value.casefold())


if __name__ == "__main__":
    unittest.main()
