from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.activity_pathways import ActivityPathwayEngine
from eqquest.db import Database
from eqquest.events import Event
from eqquest.world_profiles import set_active_world_profile


class ActivityPathwayProfileTests(unittest.TestCase):
    def test_p99_suppresses_quest_bound_to_forced_modern_zone(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                page = db.upsert_source_page(
                    url="https://everquest.allakhazam.com/db/quest.html?quest=modern-hub",
                    title="Modern Hub Opportunity",
                    entity_type="quest",
                    sha256="sha-modern-hub",
                    plain_text="reviewed structured quest objective",
                    raw_html="<html></html>",
                    source_name="Allakhazam",
                    source_kind="local_mirror",
                    source_key="quest:modern-hub",
                )
                db.upsert_entity(
                    kind="zone",
                    name="Plane of Knowledge",
                    external_id="202",
                    external_namespace="eqclient:zone",
                )
                quest = db.upsert_entity(kind="quest", name="Modern Hub Opportunity")
                db.add_quest_step(
                    quest,
                    1,
                    "Loot a Modern Hub Token",
                    zone="Plane of Knowledge",
                    match={"event": "loot", "item": "Modern Hub Token"},
                    source_page_id=page,
                )
                db.add_event(Event(kind="loot", raw="loot", item="Modern Hub Token"))

                engine = ActivityPathwayEngine(db)
                engine.reset_session(0)
                engine.refresh_observations()

                self.assertEqual([s.quest_id for s in engine.suggestions()], [quest])
                set_active_world_profile(db, "p99")
                self.assertEqual(engine.suggestions(), [])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
