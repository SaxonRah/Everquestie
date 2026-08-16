from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.profile_availability import (
    ProfileAwareQuestEngine,
    entity_profile_decision,
    profiled_entity_detail_text,
)
from eqquest.runtime import RuntimeDatabase
from eqquest.world_profiles import set_active_world_profile


class ProfileAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.working = self.root / "working.sqlite3"
        self.db = Database(self.working)

        self.classic = self._zone("Greater Faydark", 54, "Classic")
        self.north_freeport = self._zone("North Freeport", 8, "")
        self.stone_hive = self._zone("Stone Hive", 396, "The Serpent's Spine")

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

    def _zone(self, name: str, external_id: int, expansion: str) -> int:
        data = {"expansion": expansion} if expansion else {}
        return self.db.upsert_entity(
            kind="zone",
            name=name,
            external_id=str(external_id),
            external_namespace="eqclient:zone",
            data=data,
        )

    def _npc_in(self, name: str, zone_id: int) -> int:
        npc = self.db.upsert_entity(kind="npc", name=name, external_id=f"npc:{name}")
        self.db.add_location(
            npc,
            zone_entity_id=zone_id,
            x=10.0,
            y=20.0,
            z=3.0,
            label="spawn",
            evidence="test location",
        )
        return npc

    def _quest_in(self, name: str, zone_name: str, *, item: str = "Profile Token") -> int:
        quest = self.db.upsert_entity(kind="quest", name=name, external_id=f"quest:{name}")
        self.db.add_quest_step(
            quest,
            1,
            f"Loot one {item}",
            zone=zone_name,
            match={"event": "loot", "item": item, "count": 1},
        )
        return quest

    def test_p99_blocks_zone_bound_npc_and_quest_but_not_portable_item(self):
        npc = self._npc_in("Stone Hive Sentinel", self.stone_hive)
        quest = self._quest_in("Stone Hive Errand", "Stone Hive")
        item = self.db.upsert_entity(kind="item", name="Stone Hive Token", external_id="item:stone")
        self.db.add_location(
            item,
            zone_entity_id=self.stone_hive,
            x=1.0,
            y=2.0,
            label="known source",
            evidence="test source",
        )

        npc_decision = entity_profile_decision(self.db, npc, "p99")
        quest_decision = entity_profile_decision(self.db, quest, "p99")
        item_decision = entity_profile_decision(self.db, item, "p99")

        self.assertTrue(npc_decision.blocked)
        self.assertTrue(quest_decision.blocked)
        self.assertEqual(npc_decision.status, "blocked")
        self.assertEqual(quest_decision.status, "blocked")
        self.assertIsNone(item_decision.compatibility)
        self.assertEqual(item_decision.status, "unknown")
        self.assertIn("does not prove this entity kind is unavailable", item_decision.reason)

    def test_historical_north_freeport_changes_between_live_and_p99(self):
        quest = self._quest_in("Old Freeport Errand", "North Freeport")

        live = entity_profile_decision(self.db, quest, "live")
        p99 = entity_profile_decision(self.db, quest, "p99")

        self.assertTrue(live.blocked)
        self.assertTrue(p99.available)
        self.assertIn("historical/retired", live.zones[0].reason)
        self.assertIn("explicitly enabled", p99.zones[0].reason)

    def test_unrestricted_keeps_mixed_era_entity_available(self):
        npc = self._npc_in("Mixed Era Sentinel", self.stone_hive)
        decision = entity_profile_decision(self.db, npc, "unrestricted")
        self.assertTrue(decision.available)
        self.assertEqual(decision.status, "available")

    def test_profiled_knowledge_detail_keeps_fact_visible_and_labels_availability(self):
        npc = self._npc_in("Stone Hive Historian", self.stone_hive)
        set_active_world_profile(self.db, "p99")

        text = profiled_entity_detail_text(self.db, npc)

        self.assertIn("Stone Hive Historian", text)
        self.assertIn("World locations:", text)
        self.assertIn("Stone Hive", text)
        self.assertIn("Gameplay profile availability:", text)
        self.assertIn("Profile: Classic / P99-style (Velious cap)", text)
        self.assertIn("Status: OUTSIDE PROFILE", text)
        self.assertIn("compiled expansion evidence places this zone after Velious", text)

    def test_profile_aware_guidance_refuses_travel_but_keeps_observed_progress(self):
        quest = self._quest_in("Blocked Travel Quest", "Stone Hive")
        self.db.track_quest(quest)
        set_active_world_profile(self.db, "p99")
        engine = ProfileAwareQuestEngine(self.db)

        guidance = engine.guidance("Greater Faydark")
        self.assertEqual(len(guidance), 1)
        self.assertIn("Stone Hive is outside this profile", guidance[0].text)
        self.assertIn("will not recommend travel there", guidance[0].text)
        self.assertNotIn("Travel from Greater Faydark to Stone Hive.", guidance[0].text)

        engine.observe(Event(kind="loot", raw="", item="Profile Token"))
        step = self.db.quest_steps(quest)[0]
        self.assertEqual(int(step["progress_count"]), 1)
        self.assertEqual(int(step["complete"]), 1)
        self.assertTrue(self.db.is_quest_tracked(quest))

    def test_p99_guidance_keeps_reviewed_classic_destination_instruction(self):
        quest = self._quest_in("Classic Travel Quest", "North Freeport")
        self.db.track_quest(quest)
        set_active_world_profile(self.db, "p99")

        guidance = ProfileAwareQuestEngine(self.db).guidance("Greater Faydark")

        self.assertEqual(len(guidance), 1)
        self.assertIn("Travel from Greater Faydark to North Freeport.", guidance[0].text)
        self.assertNotIn("outside this profile", guidance[0].text)

    def test_runtime_profile_projection_changes_only_user_state(self):
        npc = self._npc_in("Immutable Profile Sentinel", self.stone_hive)
        snapshot = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"
        create_knowledge_snapshot(
            self.working,
            snapshot,
            snapshot_version="profile-availability-runtime",
            overwrite=True,
        )
        before = sha256(snapshot.read_bytes()).hexdigest()

        runtime = RuntimeDatabase(snapshot, state, migrate_legacy=False)
        try:
            set_active_world_profile(runtime, "p99")
            decision = entity_profile_decision(runtime, npc)
            detail = profiled_entity_detail_text(runtime, npc)
            self.assertTrue(decision.blocked)
            self.assertIn("Status: OUTSIDE PROFILE", detail)
        finally:
            runtime.close()

        self.assertEqual(sha256(snapshot.read_bytes()).hexdigest(), before)
        self.assertTrue(state.is_file())
        self.assertFalse(Path(str(snapshot) + "-wal").exists())
        self.assertFalse(Path(str(snapshot) + "-shm").exists())


if __name__ == "__main__":
    unittest.main()
