from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.profile_availability import entity_profile_decision
from eqquest.runtime import RuntimeDatabase
from eqquest.world_profiles import (
    active_world_profile_id,
    set_active_world_profile,
    shortest_path_for_profile,
    zone_profile_decisions,
)
from eqquest.zone_travel import ZoneTravelCatalog


class WorldProfileRuntimeSplitTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def test_packaged_profile_switch_writes_only_user_state(self):
        working = self.root / "working.sqlite3"
        knowledge = self.root / "everquestie-knowledge.sqlite3"
        state = self.root / "everquestie-user.sqlite3"

        builder = Database(working)
        try:
            builder.upsert_entity(
                kind="zone",
                name="West Freeport",
                external_id="9",
                external_namespace="eqclient:zone",
                data={"expansion": "EverQuest"},
            )
        finally:
            builder.close()

        create_knowledge_snapshot(
            working,
            knowledge,
            snapshot_version="profile-runtime-test",
            overwrite=True,
        )
        before = self._digest(knowledge)

        runtime = RuntimeDatabase(knowledge, state)
        try:
            self.assertEqual(active_world_profile_id(runtime), "live")
            set_active_world_profile(runtime, "p99")
            self.assertEqual(active_world_profile_id(runtime), "p99")
            self.assertEqual(runtime.get_meta("world_profile"), "p99")
        finally:
            runtime.close()

        self.assertEqual(self._digest(knowledge), before)
        self.assertFalse(Path(str(knowledge) + "-wal").exists())
        self.assertFalse(Path(str(knowledge) + "-shm").exists())
        self.assertTrue(state.is_file())

        reopened = RuntimeDatabase(knowledge, state)
        try:
            self.assertEqual(active_world_profile_id(reopened), "p99")
            set_active_world_profile(reopened, "live")
        finally:
            reopened.close()

        self.assertEqual(self._digest(knowledge), before)

    def test_runtime_profile_travel_graph_is_cached_per_profile(self):
        working = self.root / "travel-working.sqlite3"
        knowledge = self.root / "travel-knowledge.sqlite3"
        state = self.root / "travel-user.sqlite3"

        builder = Database(working)
        try:
            source = builder.upsert_entity(
                kind="zone",
                name="Cache Route A",
                external_id="901",
                external_namespace="eqclient:zone",
                data={"expansion": "EverQuest"},
            )
            target = builder.upsert_entity(
                kind="zone",
                name="Cache Route B",
                external_id="902",
                external_namespace="eqclient:zone",
                data={"expansion": "EverQuest"},
            )
            ZoneTravelCatalog(builder).add_provider_connection(
                source,
                target,
                connection_kind="zone_line",
                bidirectional=True,
                source_name="Profile cache fixture",
                source_kind="test",
                source_key="cache-route",
            )
        finally:
            builder.close()

        create_knowledge_snapshot(
            working,
            knowledge,
            snapshot_version="profile-travel-cache-test",
            overwrite=True,
        )

        runtime = RuntimeDatabase(knowledge, state)
        try:
            self.assertEqual(
                shortest_path_for_profile(runtime, source, target, "live"),
                [source, target],
            )
            cache = getattr(runtime, "_profile_travel_adjacency_cache")
            self.assertIn("live", cache)

            statements: list[str] = []
            runtime.conn.set_trace_callback(statements.append)
            try:
                self.assertEqual(
                    shortest_path_for_profile(runtime, source, target, "live"),
                    [source, target],
                )
            finally:
                runtime.conn.set_trace_callback(None)
            sql = " ".join("\n".join(statements).casefold().split())
            self.assertNotIn("from zone_travel_edges", sql)
        finally:
            runtime.close()

    def test_runtime_zone_profile_decisions_are_cached_per_profile(self):
        working = self.root / "cache-working.sqlite3"
        knowledge = self.root / "cache-knowledge.sqlite3"
        state = self.root / "cache-user.sqlite3"

        builder = Database(working)
        try:
            builder.upsert_entity(
                kind="zone",
                name="West Freeport",
                external_id="9",
                external_namespace="eqclient:zone",
                data={"expansion": "EverQuest"},
            )
            quest_id = builder.upsert_entity(
                kind="quest",
                name="Cached Profile Quest",
            )
        finally:
            builder.close()

        create_knowledge_snapshot(
            working,
            knowledge,
            snapshot_version="profile-cache-test",
            overwrite=True,
        )

        runtime = RuntimeDatabase(knowledge, state)
        try:
            live_first = zone_profile_decisions(runtime, "live")
            live_second = zone_profile_decisions(runtime, "live")
            self.assertIs(live_first, live_second)

            p99 = zone_profile_decisions(runtime, "p99")
            cache = getattr(runtime, "_zone_profile_decisions_cache")
            self.assertIs(cache["live"], live_first)
            self.assertIs(cache["p99"], p99)

            entity_first = entity_profile_decision(runtime, quest_id, "live")
            entity_second = entity_profile_decision(runtime, quest_id, "live")
            self.assertIs(entity_first, entity_second)
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
