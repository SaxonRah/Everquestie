from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase
from eqquest.world_profiles import active_world_profile_id, set_active_world_profile


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


if __name__ == "__main__":
    unittest.main()
