from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.events import Event
from eqquest.profile_availability_ui import player_knowledge_detail_text


class PersonalObservationsKnowledgeUITests(unittest.TestCase):
    def test_player_detail_keeps_canonical_sections_and_appends_personal_history(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                source = db.upsert_source_page(
                    url="eqclient://fixture.txt",
                    title="Fixture source",
                    entity_type="item",
                    sha256="fixture",
                    plain_text="WHOLE FILE SENTINEL SHOULD STAY HIDDEN",
                    raw_html="",
                    source_name="EverQuest Client",
                    source_kind="local_game_files",
                    source_key="fixture.txt",
                )
                item = db.upsert_entity(
                    kind="item",
                    name="Observed Token",
                    external_id="item:observed-token",
                    source_page_id=source,
                    source_url="eqclient://fixture.txt#token",
                    notes="Canonical item note.",
                )
                db.add_event(
                    Event(
                        kind="loot",
                        raw="loot",
                        item="Observed Token",
                        actor="a test corpse",
                    )
                )

                text = player_knowledge_detail_text(
                    db,
                    item,
                    include_source_text=True,
                )
                self.assertIn("Canonical item note.", text)
                self.assertIn("Primary source: eqclient://fixture.txt#token", text)
                self.assertIn("Gameplay profile availability:", text)
                self.assertNotIn("Primary source text snapshot", text)
                self.assertNotIn("WHOLE FILE SENTINEL", text)
                self.assertIn("Your log observations:", text)
                self.assertIn("You looted: 1", text)
                self.assertIn("a test corpse: 1", text)
                self.assertIn("not canonical EverQuest source data", text)
            finally:
                db.close()

    def test_entity_without_personal_history_does_not_get_empty_noise_block(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                item = db.upsert_entity(
                    kind="item",
                    name="Never Observed Token",
                    external_id="item:never-observed",
                )
                text = player_knowledge_detail_text(db, item)
                self.assertNotIn("Your log observations:", text)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
