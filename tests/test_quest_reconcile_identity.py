from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.quest_engine import QuestEngine
from eqquest.quest_progress_identity import install_quest_progress_identity_policy


class QuestReconcileIdentityTests(unittest.TestCase):
    def setUp(self):
        install_quest_progress_identity_policy()

    @staticmethod
    def _source(db: Database, key: str, kind: str) -> int:
        return db.upsert_source_page(
            url=f"https://example.invalid/{key}",
            title=key,
            entity_type=kind,
            sha256=key,
            plain_text=key,
            raw_html="",
            source_name="Test Source",
            source_kind="fixture",
            source_key=key,
        )

    def _quest(
        self,
        db: Database,
        name: str,
        external_id: str,
        *,
        count: int = 1,
        track: bool = False,
    ) -> int:
        page = self._source(db, external_id, "quest")
        quest = db.upsert_entity(
            kind="quest",
            name=name,
            external_id=external_id,
            source_page_id=page,
        )
        db.add_quest_step(
            quest,
            1,
            "Kill a skeleton",
            match={"event": "kill", "npc": "a skeleton", "count": count},
            source_page_id=page,
        )
        if track:
            db.track_quest(quest)
        return quest

    def _npc(self, db: Database, name: str, external_id: str) -> int:
        page = self._source(db, external_id, "npc")
        return db.upsert_entity(
            kind="npc",
            name=name,
            external_id=external_id,
            source_page_id=page,
        )

    def _zone(self, db: Database, name: str, external_id: str) -> int:
        page = self._source(db, external_id, "zone")
        return db.upsert_entity(
            kind="zone",
            name=name,
            external_id=external_id,
            source_page_id=page,
        )

    def _locate(
        self,
        db: Database,
        entity_id: int,
        zone_id: int,
        key: str,
        *,
        provenanced: bool = True,
    ) -> None:
        source_page_id = self._source(db, key, "npc") if provenanced else None
        db.add_location(
            entity_id,
            zone_entity_id=zone_id,
            y=1.0,
            x=2.0,
            source_page_id=source_page_id,
            evidence="fixture location" if provenanced else "",
        )

    @staticmethod
    def _personal_kill() -> Event:
        return Event(
            kind="kill",
            raw="You have slain a skeleton!",
            actor="a skeleton",
            target="You",
        )

    @staticmethod
    def _progress(db: Database, quest_id: int) -> int:
        return int(db.quest_steps(quest_id)[0]["progress_count"])

    def test_unique_task_assignment_is_high_confidence_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Unique Task", "quest:1", track=True)
                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="task_assigned", raw="assigned", text="Unique Task"),
                        self._personal_kill(),
                    ],
                )
                self.assertEqual(result.boundary, "task assignment")
                self.assertEqual(result.confidence, "high")
                self.assertEqual(result.progress_total, 1)
            finally:
                db.close()

    def test_duplicate_canonical_task_name_cannot_reset_or_replay_progress(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Twin Task", "quest:1", count=2, track=True)
                self._quest(db, "Twin Task", "quest:2")
                db.set_step_progress(quest, 1, 1, False)

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="task_assigned", raw="assigned", text="Twin Task"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
                self.assertEqual(result.events_replayed, -1)
                self.assertEqual(result.progress_total, 1)
                self.assertEqual(self._progress(db, quest), 1)
            finally:
                db.close()

    def test_unique_task_alias_can_establish_assignment_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Formal Task Name", "quest:1", track=True)
                db.add_alias(quest, "Short Task", alias_type="quest_short_name")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="task_assigned", raw="assigned", text="Short Task"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "task assignment")
                self.assertEqual(result.progress_total, 1)
            finally:
                db.close()

    def test_duplicate_task_alias_is_not_a_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Formal One", "quest:1", track=True)
                other = self._quest(db, "Formal Two", "quest:2")
                db.add_alias(quest, "Shared Task", alias_type="quest_short_name")
                db.add_alias(other, "Shared Task", alias_type="quest_short_name")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="task_assigned", raw="assigned", text="Shared Task"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
                self.assertEqual(result.events_replayed, -1)
            finally:
                db.close()

    def test_exact_quest_name_takes_precedence_over_other_quest_alias(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Formal Task", "quest:1", track=True)
                db.add_alias(quest, "Shared Name", alias_type="quest_short_name")
                self._quest(db, "Shared Name", "quest:2")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="task_assigned", raw="assigned", text="Shared Name"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
                self.assertEqual(result.events_replayed, -1)
            finally:
                db.close()

    def test_unique_explicit_hail_plus_qualifying_objective_is_medium_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Hail Task", "quest:1", track=True)
                starter = self._npc(db, "Quest Guide", "npc:1")
                db.upsert_relationship(quest, starter, "started_by")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "starter NPC hail")
                self.assertEqual(result.confidence, "medium")
                self.assertEqual(result.progress_total, 1)
            finally:
                db.close()

    def test_arbitrary_say_containing_starter_name_is_not_a_hail_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Hail Task", "quest:1", track=True)
                starter = self._npc(db, "Quest Guide", "npc:1")
                db.upsert_relationship(quest, starter, "started_by")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="say", raw="say", text="Quest Guide"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
                self.assertEqual(result.events_replayed, -1)
            finally:
                db.close()

    def test_duplicate_starter_name_without_logged_zone_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Hail Task", "quest:1", track=True)
                starter = self._npc(db, "Quest Guide", "npc:1")
                self._npc(db, "Quest Guide", "npc:2")
                db.upsert_relationship(quest, starter, "started_by")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
            finally:
                db.close()

    def test_complete_provenanced_zone_geography_can_resolve_duplicate_starter(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                west = self._zone(db, "West Zone", "zone:west")
                east = self._zone(db, "East Zone", "zone:east")
                quest = self._quest(db, "Hail Task", "quest:1", track=True)
                starter = self._npc(db, "Quest Guide", "npc:west")
                other = self._npc(db, "Quest Guide", "npc:east")
                self._locate(db, starter, west, "loc:west")
                self._locate(db, other, east, "loc:east")
                db.upsert_relationship(quest, starter, "started_by")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="zone", raw="zone", zone="West Zone"),
                        Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "starter NPC hail")
                self.assertEqual(result.progress_total, 1)
            finally:
                db.close()

    def test_duplicate_starters_both_known_in_zone_remain_ambiguous(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                west = self._zone(db, "West Zone", "zone:west")
                quest = self._quest(db, "Hail Task", "quest:1", track=True)
                starter = self._npc(db, "Quest Guide", "npc:1")
                other = self._npc(db, "Quest Guide", "npc:2")
                self._locate(db, starter, west, "loc:1")
                self._locate(db, other, west, "loc:2")
                db.upsert_relationship(quest, starter, "started_by")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="zone", raw="zone", zone="West Zone"),
                        Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
            finally:
                db.close()

    def test_unknown_competing_starter_geography_prevents_zone_resolution(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                west = self._zone(db, "West Zone", "zone:west")
                quest = self._quest(db, "Hail Task", "quest:1", track=True)
                starter = self._npc(db, "Quest Guide", "npc:1")
                self._npc(db, "Quest Guide", "npc:2")
                self._locate(db, starter, west, "loc:1")
                db.upsert_relationship(quest, starter, "started_by")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="zone", raw="zone", zone="West Zone"),
                        Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
            finally:
                db.close()

    def test_unsourced_location_cannot_resolve_duplicate_starter(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                west = self._zone(db, "West Zone", "zone:west")
                east = self._zone(db, "East Zone", "zone:east")
                quest = self._quest(db, "Hail Task", "quest:1", track=True)
                starter = self._npc(db, "Quest Guide", "npc:1")
                other = self._npc(db, "Quest Guide", "npc:2")
                self._locate(db, starter, west, "manual:west", provenanced=False)
                self._locate(db, other, east, "loc:east")
                db.upsert_relationship(quest, starter, "started_by")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="zone", raw="zone", zone="West Zone"),
                        Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
            finally:
                db.close()

    def test_uniquely_identified_nonstarter_hail_is_not_a_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Hail Task", "quest:1", track=True)
                actual = self._npc(db, "Actual Starter", "npc:starter")
                self._npc(db, "Quest Guide", "npc:not-starter")
                db.upsert_relationship(quest, actual, "started_by")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="say", raw="hail", text="Hail, Quest Guide"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
            finally:
                db.close()

    def test_ambiguous_task_assignment_blocks_fallback_to_older_hail(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Twin Task", "quest:1", count=3, track=True)
                self._quest(db, "Twin Task", "quest:2")
                starter = self._npc(db, "Quest Guide", "npc:starter")
                db.upsert_relationship(quest, starter, "started_by")
                db.set_step_progress(quest, 1, 1, False)

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="say", raw="old hail", text="Hail, Quest Guide"),
                        self._personal_kill(),
                        Event(kind="task_assigned", raw="ambiguous", text="Twin Task"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "none")
                self.assertEqual(result.events_replayed, -1)
                self.assertEqual(self._progress(db, quest), 1)
            finally:
                db.close()

    def test_safe_hail_after_ambiguous_assignment_can_establish_new_boundary(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                quest = self._quest(db, "Twin Task", "quest:1", track=True)
                self._quest(db, "Twin Task", "quest:2")
                starter = self._npc(db, "Quest Guide", "npc:starter")
                db.upsert_relationship(quest, starter, "started_by")

                result = QuestEngine(db).reconcile_quest_from_events(
                    quest,
                    [
                        Event(kind="task_assigned", raw="ambiguous", text="Twin Task"),
                        Event(kind="say", raw="new hail", text="Hail, Quest Guide"),
                        self._personal_kill(),
                    ],
                )

                self.assertEqual(result.boundary, "starter NPC hail")
                self.assertEqual(result.confidence, "medium")
                self.assertEqual(result.events_replayed, 2)
                self.assertEqual(result.progress_total, 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
