from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.live_quest_map import live_quest_map_choices
from eqquest.packaged_ui_policy import install_packaged_ui_policy
from eqquest.runtime import RuntimeDatabase
from eqquest.runtime_policy import install_runtime_policy


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class LiveQuestMapTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        builder = Database(self.root / "working.sqlite3")
        self.stone = builder.upsert_entity(
            kind="zone",
            name="The Stone Hive",
            external_id="351",
            external_namespace="eqclient:zone",
        )
        self.blight = builder.upsert_entity(
            kind="zone",
            name="Blightfire Moors",
            external_id="202",
            external_namespace="eqclient:zone",
        )
        self.starter = builder.upsert_entity(
            kind="npc",
            name="Scout Fana",
            external_id="npc:5001",
        )
        builder.add_alias(self.starter, "Fana Alias", alias_type="source")
        builder.add_location(
            self.starter,
            zone_entity_id=self.stone,
            y=100.0,
            x=-50.0,
            z=5.0,
            label="quest starter",
            evidence="Scout Fana location",
        )
        self.wrong_npc = builder.upsert_entity(
            kind="npc",
            name="Wrong Scout",
            external_id="npc:5002",
        )
        builder.add_location(
            self.wrong_npc,
            zone_entity_id=self.stone,
            y=999.0,
            x=999.0,
            z=0.0,
            label="wrong location",
            evidence="Wrong Scout location",
        )
        self.dropper = builder.upsert_entity(
            kind="npc",
            name="A Stone Worker",
            external_id="npc:5003",
        )
        builder.add_location(
            self.dropper,
            zone_entity_id=self.stone,
            y=200.0,
            x=-75.0,
            z=8.0,
            label="known spawn",
            evidence="A Stone Worker location",
        )
        self.item = builder.upsert_entity(
            kind="item",
            name="Hive Sample",
            external_id="item:8001",
        )
        builder.upsert_relationship(
            self.item,
            self.dropper,
            "drops_from",
            evidence="Hive Sample drops from A Stone Worker",
            data={"confidence": "structured"},
        )
        self.quest = builder.upsert_entity(
            kind="quest",
            name="A Hive Inquiry",
            external_id="quest:9001",
            external_namespace="allakhazam:quest",
        )
        builder.add_quest_step(
            self.quest,
            1,
            "Speak with Scout Fana",
            zone="The Stone Hive",
            match={
                "event": "npc_say",
                "npc_entity_id": self.starter,
                # Deliberately conflicting display name: stable identity must win.
                "npc": "Wrong Scout",
                "count": 1,
            },
        )
        builder.add_quest_step(
            self.quest,
            2,
            "Loot one Hive Sample",
            zone="The Stone Hive",
            match={
                "event": "loot",
                "item_entity_id": self.item,
                "item": "Hive Sample",
                "count": 1,
            },
        )

        self.alias_quest = builder.upsert_entity(
            kind="quest",
            name="Alias Inquiry",
            external_id="quest:9002",
        )
        builder.add_quest_step(
            self.alias_quest,
            1,
            "Speak with Fana Alias",
            zone="The Stone Hive",
            match={"event": "npc_say", "npc": "Fana Alias", "count": 1},
        )

        self.ambiguous_a = builder.upsert_entity(
            kind="npc",
            name="Ambiguous Scout",
            external_id="npc:5101",
        )
        self.ambiguous_b = builder.upsert_entity(
            kind="npc",
            name="Ambiguous Scout",
            external_id="npc:5102",
        )
        self.ambiguous_quest = builder.upsert_entity(
            kind="quest",
            name="Ambiguous Inquiry",
            external_id="quest:9003",
        )
        builder.add_quest_step(
            self.ambiguous_quest,
            1,
            "Find Ambiguous Scout",
            zone="The Stone Hive",
            match={"event": "target_npc", "npc": "Ambiguous Scout"},
        )

        self.no_target_quest = builder.upsert_entity(
            kind="quest",
            name="Untargeted Inquiry",
            external_id="quest:9004",
        )
        builder.add_quest_step(
            self.no_target_quest,
            1,
            "Observe the hive entrance",
            zone="The Stone Hive",
            match={"event": "emote", "count": 1},
        )

        snapshot = self.root / "everquestie-knowledge.sqlite3"
        create_knowledge_snapshot(
            self.root / "working.sqlite3",
            snapshot,
            snapshot_version="live-quest-map-test",
        )
        builder.close()
        self.runtime = RuntimeDatabase(
            snapshot,
            self.root / "everquestie-user.sqlite3",
            migrate_legacy=False,
        )
        self.runtime.track_quest(self.quest)

    def tearDown(self):
        self.runtime.close()
        self.tempdir.cleanup()

    def _track(self, quest_id: int) -> None:
        self.runtime.track_quest(quest_id)

    def test_active_step_uses_stable_npc_entity_id_before_conflicting_name(self):
        result = live_quest_map_choices(
            self.runtime,
            self.quest,
            "The Stone Hive",
        )
        self.assertTrue(result.ready)
        assert result.objective is not None
        self.assertEqual(result.objective.step_order, 1)
        self.assertEqual(result.objective.step_selection, "active_step")
        self.assertEqual(result.objective.target_entity_id, self.starter)
        self.assertEqual(result.objective.target_name, "Scout Fana")
        self.assertEqual(result.objective.target_resolution, "npc_entity_id")
        self.assertNotEqual(result.objective.target_entity_id, self.wrong_npc)
        self.assertEqual(len(result.objective.choices), 1)
        choice = result.objective.choices[0]
        self.assertEqual(choice.location_entity_id, self.starter)
        self.assertEqual((choice.x, choice.y, choice.z), (-50.0, 100.0, 5.0))

    def test_user_progress_advances_active_step_then_item_reuses_dropper_location(self):
        self.runtime.set_step_progress(self.quest, 1, 1, True)
        tracked = next(row for row in self.runtime.tracked_quests() if int(row["id"]) == self.quest)
        self.assertEqual(int(tracked["active_step"]), 2)

        result = live_quest_map_choices(self.runtime, self.quest, "The Stone Hive")
        self.assertTrue(result.ready)
        assert result.objective is not None
        self.assertEqual(result.objective.step_order, 2)
        self.assertEqual(result.objective.target_entity_id, self.item)
        self.assertEqual(result.objective.target_resolution, "item_entity_id")
        self.assertEqual(len(result.objective.choices), 1)
        choice = result.objective.choices[0]
        self.assertEqual(choice.location_entity_id, self.dropper)
        self.assertEqual(choice.relation, "drops_from")
        self.assertEqual(choice.relation_label, "drops from")
        self.assertEqual((choice.x, choice.y, choice.z), (-75.0, 200.0, 8.0))

    def test_explicit_selected_completed_step_overrides_active_step(self):
        self.runtime.set_step_progress(self.quest, 1, 1, True)
        result = live_quest_map_choices(
            self.runtime,
            self.quest,
            "The Stone Hive",
            selected_step_order=1,
        )
        self.assertTrue(result.ready)
        assert result.objective is not None
        self.assertEqual(result.objective.step_order, 1)
        self.assertEqual(result.objective.step_selection, "selected_step")
        self.assertTrue(result.objective.complete)
        self.assertEqual(result.objective.target_entity_id, self.starter)

    def test_all_complete_root_selection_reports_quest_complete(self):
        self.runtime.set_step_progress(self.quest, 1, 1, True)
        self.runtime.set_step_progress(self.quest, 2, 1, True)
        result = live_quest_map_choices(self.runtime, self.quest, "The Stone Hive")
        self.assertFalse(result.ready)
        self.assertEqual(result.status, "quest_complete")
        self.assertIn("All structured steps are complete", result.reason)

    def test_exact_alias_name_fallback_is_allowed_without_substring_guessing(self):
        self._track(self.alias_quest)
        result = live_quest_map_choices(
            self.runtime,
            self.alias_quest,
            "The Stone Hive",
        )
        self.assertTrue(result.ready)
        assert result.objective is not None
        self.assertEqual(result.objective.target_entity_id, self.starter)
        self.assertEqual(result.objective.target_resolution, "npc:alias")

    def test_ambiguous_exact_name_target_is_refused(self):
        self._track(self.ambiguous_quest)
        result = live_quest_map_choices(
            self.runtime,
            self.ambiguous_quest,
            "The Stone Hive",
        )
        self.assertFalse(result.ready)
        self.assertEqual(result.status, "target_ambiguous")
        self.assertIn("will not guess", result.reason)

    def test_step_without_explicit_normalized_target_is_not_parsed_from_prose(self):
        self._track(self.no_target_quest)
        result = live_quest_map_choices(
            self.runtime,
            self.no_target_quest,
            "The Stone Hive",
        )
        self.assertFalse(result.ready)
        self.assertEqual(result.status, "no_target_identity")
        self.assertIn("no explicit normalized item/NPC target identity", result.reason)

    def test_untracked_quest_is_rejected_even_when_knowledge_has_steps(self):
        self.runtime.untrack_quest(self.quest)
        result = live_quest_map_choices(self.runtime, self.quest, "The Stone Hive")
        self.assertEqual(result.status, "not_tracked")
        self.assertFalse(result.ready)

    def test_packaged_live_action_maps_active_objective_through_map_owner(self):
        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        status = _Status()
        emitted: list[tuple] = []
        fake = SimpleNamespace(
            db=self.runtime,
            state_model=SimpleNamespace(current_zone="The Stone Hive"),
            status=status,
            _tracked_selected_step=lambda: None,
            _tracked_selected_quest_id=lambda: self.quest,
            _focus_navigation_map_target=lambda *args: emitted.append(args),
        )
        app_module.EverQuestieApp._map_selected_live_objective(fake)
        self.assertEqual(
            emitted,
            [("The Stone Hive", -50.0, 100.0, 5.0, "Scout Fana")],
        )

        # User progress changes which objective is active; immutable world knowledge
        # then supplies the item's explicitly related dropper location.
        self.runtime.set_step_progress(self.quest, 1, 1, True)
        emitted.clear()
        app_module.EverQuestieApp._map_selected_live_objective(fake)
        self.assertEqual(
            emitted,
            [("The Stone Hive", -75.0, 200.0, 8.0, "A Stone Worker (drops from)")],
        )

    def test_packaged_tracked_tree_selection_no_longer_calls_legacy_direct_focus(self):
        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        # A packaged selection event must be a no-op even with none of the legacy
        # map_view/focus_entity attributes present. Mapping is explicit via the button.
        fake = SimpleNamespace(_packaged_runtime=lambda: True)
        app_module.EverQuestieApp._tracked_tree_selected(fake)

    def test_packaged_live_action_requires_explicit_tracked_selection(self):
        install_runtime_policy()
        install_packaged_ui_policy()
        from eqquest import app as app_module

        status = _Status()
        fake = SimpleNamespace(
            db=self.runtime,
            state_model=SimpleNamespace(current_zone="The Stone Hive"),
            status=status,
            _tracked_selected_step=lambda: None,
            _tracked_selected_quest_id=lambda: None,
            _focus_navigation_map_target=lambda *_args: self.fail("unexpected map handoff"),
        )
        app_module.EverQuestieApp._map_selected_live_objective(fake)
        self.assertIn("Select a tracked quest or objective", status.value)


if __name__ == "__main__":
    unittest.main()
