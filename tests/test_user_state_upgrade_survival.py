from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.knowledge_snapshot import create_knowledge_snapshot
from eqquest.runtime import RuntimeDatabase, USER_STATE_SCHEMA_VERSION


class UserStateUpgradeSurvivalTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.knowledge = self.root / "everquestie-knowledge.sqlite3"
        self.state = self.root / "everquestie-user.sqlite3"

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def _state_artifacts(self) -> dict[str, bytes]:
        result: dict[str, bytes] = {}
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.state) + suffix)
            if path.is_file():
                result[suffix or "main"] = path.read_bytes()
        return result

    def _build_snapshot(
        self,
        *,
        version: str,
        dummy_entities: int,
        quest_name: str,
        step_count: int,
    ) -> tuple[int, str]:
        working = self.root / f"{version}.working.sqlite3"
        working.unlink(missing_ok=True)
        db = Database(working)
        try:
            for index in range(dummy_entities):
                db.upsert_entity(
                    kind="quest",
                    name=f"Upgrade Dummy {version} {index + 1}",
                    merge_by_name=True,
                )

            quest_id = db.upsert_entity(
                kind="quest",
                name=quest_name,
                external_namespace="everquestie:quest",
                external_id="upgrade-survival",
                merge_by_name=True,
            )
            for step_order in range(1, step_count + 1):
                db.add_quest_step(
                    quest_id,
                    step_order,
                    f"Upgrade step {step_order} for {version}.",
                    match={
                        "event": "loot",
                        "item": f"Upgrade Token {step_order}",
                        "count": 1,
                    },
                )
        finally:
            db.close()

        create_knowledge_snapshot(
            working,
            self.knowledge,
            snapshot_version=version,
            overwrite=True,
        )
        return quest_id, self._digest(self.knowledge)

    @staticmethod
    def _sentinel_value(db: RuntimeDatabase) -> str:
        row = db.conn.execute(
            "SELECT value FROM player_upgrade_sentinel WHERE id=1"
        ).fetchone()
        return str(row["value"]) if row is not None else ""

    def test_player_state_survives_three_successive_knowledge_replacements(self):
        v1_id, v1_hash = self._build_snapshot(
            version="upgrade-v1",
            dummy_entities=0,
            quest_name="Portable Upgrade Quest",
            step_count=1,
        )

        runtime = RuntimeDatabase(
            self.knowledge,
            self.state,
            migrate_legacy=False,
        )
        try:
            runtime.set_meta("map_root", r"C:\EverQuest\maps")
            runtime.set_meta("map_theme", "Brewall")
            runtime.add_event(
                Event(
                    kind="loot",
                    raw="You have looted an Upgrade Token 1.",
                    item="Upgrade Token 1",
                )
            )
            runtime.track_quest(v1_id)
            runtime.set_step_progress(v1_id, 1, 1, True)
            runtime.conn.execute(
                "CREATE TABLE player_upgrade_sentinel(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
            runtime.conn.execute(
                "INSERT INTO player_upgrade_sentinel(id,value) VALUES(1,'preserve-me')"
            )
            runtime.conn.commit()
        finally:
            runtime.close()

        state_before_v2 = self._state_artifacts()
        self.assertIn("main", state_before_v2)

        v2_id, v2_hash = self._build_snapshot(
            version="upgrade-v2",
            dummy_entities=2,
            quest_name="Portable Upgrade Quest Revised",
            step_count=2,
        )
        self.assertNotEqual(v1_id, v2_id)
        self.assertNotEqual(v1_hash, v2_hash)
        self.assertEqual(self._state_artifacts(), state_before_v2)

        runtime = RuntimeDatabase(
            self.knowledge,
            self.state,
            migrate_legacy=False,
        )
        try:
            self.assertEqual(runtime.get_meta("knowledge_snapshot_version"), "upgrade-v2")
            self.assertEqual(runtime.get_meta("map_root"), r"C:\EverQuest\maps")
            self.assertEqual(runtime.get_meta("map_theme"), "Brewall")
            self.assertEqual(self._sentinel_value(runtime), "preserve-me")
            self.assertEqual(len(runtime.observed_event_history()), 1)

            tracked = runtime.tracked_quests()
            self.assertEqual(len(tracked), 1)
            self.assertEqual(int(tracked[0]["id"]), v2_id)
            self.assertEqual(tracked[0]["name"], "Portable Upgrade Quest Revised")
            steps = runtime.quest_steps(v2_id)
            self.assertEqual(len(steps), 2)
            self.assertEqual(int(steps[0]["complete"]), 1)
            self.assertEqual(int(steps[1]["complete"]), 0)

            runtime.add_event(
                Event(
                    kind="loot",
                    raw="You have looted an Upgrade Token 2.",
                    item="Upgrade Token 2",
                )
            )
            runtime.set_meta("map_theme", "Goods")
        finally:
            runtime.close()

        state_before_v3 = self._state_artifacts()
        v3_id, v3_hash = self._build_snapshot(
            version="upgrade-v3",
            dummy_entities=5,
            quest_name="Portable Upgrade Quest Final",
            step_count=3,
        )
        self.assertNotEqual(v2_id, v3_id)
        self.assertEqual(len({v1_hash, v2_hash, v3_hash}), 3)
        self.assertEqual(self._state_artifacts(), state_before_v3)

        runtime = RuntimeDatabase(
            self.knowledge,
            self.state,
            migrate_legacy=False,
        )
        try:
            self.assertEqual(runtime.get_meta("knowledge_snapshot_version"), "upgrade-v3")
            self.assertEqual(runtime.get_meta("map_root"), r"C:\EverQuest\maps")
            self.assertEqual(runtime.get_meta("map_theme"), "Goods")
            self.assertEqual(self._sentinel_value(runtime), "preserve-me")
            self.assertEqual(len(runtime.observed_event_history()), 2)

            tracked = runtime.tracked_quests()
            self.assertEqual(len(tracked), 1)
            self.assertEqual(int(tracked[0]["id"]), v3_id)
            self.assertEqual(tracked[0]["name"], "Portable Upgrade Quest Final")
            steps = runtime.quest_steps(v3_id)
            self.assertEqual(len(steps), 3)
            self.assertEqual([int(step["complete"]) for step in steps], [1, 0, 0])

            schema = runtime.conn.execute(
                "SELECT value FROM user_state_meta WHERE key='schema_version'"
            ).fetchone()
            self.assertIsNotNone(schema)
            self.assertEqual(str(schema["value"]), USER_STATE_SCHEMA_VERSION)
        finally:
            runtime.close()

        self.assertFalse(Path(str(self.knowledge) + "-wal").exists())
        self.assertFalse(Path(str(self.knowledge) + "-shm").exists())

    def test_newer_user_state_schema_fails_closed_without_resetting_player_data(self):
        quest_id, _digest = self._build_snapshot(
            version="upgrade-schema-guard",
            dummy_entities=0,
            quest_name="Schema Guard Quest",
            step_count=1,
        )
        runtime = RuntimeDatabase(
            self.knowledge,
            self.state,
            migrate_legacy=False,
        )
        try:
            runtime.set_meta("map_root", "/player/maps")
            runtime.add_event(
                Event(
                    kind="loot",
                    raw="You have looted a Schema Guard Token.",
                    item="Schema Guard Token",
                )
            )
            runtime.track_quest(quest_id)
            runtime.set_step_progress(quest_id, 1, 1, True)
            runtime.conn.execute(
                "CREATE TABLE player_upgrade_sentinel(id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
            runtime.conn.execute(
                "INSERT INTO player_upgrade_sentinel(id,value) VALUES(1,'future-state')"
            )
            runtime.conn.commit()
        finally:
            runtime.close()

        raw = sqlite3.connect(self.state)
        try:
            raw.execute(
                "UPDATE user_state_meta SET value='999' WHERE key='schema_version'"
            )
            raw.commit()
        finally:
            raw.close()

        with self.assertRaisesRegex(
            ValueError,
            "Incompatible EverQuestie user-state schema",
        ):
            RuntimeDatabase(
                self.knowledge,
                self.state,
                migrate_legacy=False,
            )

        raw = sqlite3.connect(self.state)
        try:
            self.assertEqual(
                raw.execute(
                    "SELECT value FROM user_state_meta WHERE key='schema_version'"
                ).fetchone()[0],
                "999",
            )
            self.assertEqual(
                raw.execute(
                    "SELECT value FROM user_meta WHERE key='map_root'"
                ).fetchone()[0],
                "/player/maps",
            )
            self.assertEqual(
                raw.execute("SELECT COUNT(*) FROM observed_events").fetchone()[0],
                1,
            )
            self.assertEqual(
                raw.execute("SELECT COUNT(*) FROM tracked_quests").fetchone()[0],
                1,
            )
            self.assertEqual(
                raw.execute("SELECT COUNT(*) FROM quest_progress WHERE complete=1").fetchone()[0],
                1,
            )
            self.assertEqual(
                raw.execute(
                    "SELECT value FROM player_upgrade_sentinel WHERE id=1"
                ).fetchone()[0],
                "future-state",
            )
        finally:
            raw.close()


if __name__ == "__main__":
    unittest.main()
