from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.knowledge import entity_detail_text
from eqquest.profile_availability_ui import (
    install_profile_availability_ui,
    player_knowledge_detail_text,
)
from eqquest.profile_availability import ProfileAwareQuestEngine
from eqquest.world_profiles import set_active_world_profile


class ProfileAvailabilityUITests(unittest.TestCase):
    def test_installer_rebinds_app_profile_surfaces(self):
        from eqquest import app as app_module
        from eqquest.world_profile_ui import install_world_profile_ui

        # The production launcher installs global world-profile ownership first.
        install_world_profile_ui()
        install_profile_availability_ui()

        self.assertIs(app_module.QuestEngine, ProfileAwareQuestEngine)
        self.assertIs(app_module.entity_detail_text, player_knowledge_detail_text)
        self.assertTrue(
            getattr(
                app_module.EverQuestieApp._world_profile_changed,
                "_everquestie_profile_availability_ui",
                False,
            )
        )
        self.assertTrue(
            getattr(
                app_module.EverQuestieApp._suggest_zone_from_quest,
                "_everquestie_profile_quest_zone_policy",
                False,
            )
        )

    def test_player_knowledge_hides_raw_source_snapshot_but_keeps_provenance_and_detail(self):
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                source_id = db.upsert_source_page(
                    url="eqclient://dbstr_us.txt",
                    title="EverQuest dbstr_us.txt selected identities",
                    entity_type="multi",
                    sha256="dbstr-fixture",
                    plain_text="WHOLE FILE SENTINEL\n0^10^Strength...\n1^20^Ruins of Kunark",
                    raw_html="",
                    source_name="EverQuest Client",
                    source_kind="local_game_files",
                    source_key="dbstr_us.txt",
                )
                entity_id = db.upsert_entity(
                    kind="alt_currency",
                    name="Chronobine",
                    source_page_id=source_id,
                    source_url="eqclient://dbstr_us.txt#17:15",
                    external_id="15",
                    external_namespace="eqclient:alt_currency",
                    merge_by_name=False,
                    notes="Identity imported from the installed EverQuest client's dbstr_us.txt.",
                    data={"dbstr_type": 17, "description": "Currency of a specific merchant."},
                )
                db.upsert_entity_detail(
                    entity_id,
                    source_page_id=source_id,
                    detail_format="text",
                    detail_text="Currency of a specific merchant.",
                    detail_json={"dbstr_type": 17, "description": "Currency of a specific merchant."},
                )

                diagnostic = entity_detail_text(db, entity_id, include_source_text=True)
                self.assertIn("--- Primary source text snapshot ---", diagnostic)
                self.assertIn("WHOLE FILE SENTINEL", diagnostic)

                # The legacy app callback still passes include_source_text=True. The
                # player-facing wrapper intentionally refuses that raw dump while
                # preserving the useful entity-specific projections and provenance.
                visible = player_knowledge_detail_text(
                    db,
                    entity_id,
                    include_source_text=True,
                )
                self.assertNotIn("--- Primary source text snapshot ---", visible)
                self.assertNotIn("WHOLE FILE SENTINEL", visible)
                self.assertIn("Primary source: eqclient://dbstr_us.txt#17:15", visible)
                self.assertIn("Provenance:", visible)
                self.assertIn("EverQuest Client [primary]", visible)
                self.assertIn("Installed EverQuest client detail:", visible)
                self.assertIn("Currency of a specific merchant.", visible)
                self.assertIn("Gameplay profile availability:", visible)
            finally:
                db.close()

    def test_blocked_quest_does_not_infer_current_zone(self):
        from eqquest import app as app_module
        from eqquest.world_profile_ui import install_world_profile_ui

        install_world_profile_ui()
        install_profile_availability_ui()

        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                db.upsert_entity(
                    kind="zone",
                    name="Stone Hive",
                    external_id="396",
                    external_namespace="eqclient:zone",
                    data={"expansion": "The Serpent's Spine"},
                )
                quest = db.upsert_entity(
                    kind="quest",
                    name="Blocked Zone Suggestion",
                    external_id="quest:blocked-zone-suggestion",
                )
                db.add_quest_step(
                    quest,
                    1,
                    "Visit Stone Hive",
                    zone="Stone Hive",
                    match={"event": "zone"},
                )
                set_active_world_profile(db, "p99")

                class FakeApp:
                    def __init__(self):
                        self.db = db
                        self.events: list[str] = []

                    def _quest_zone_name(self, _quest_id: int) -> str:
                        return "Stone Hive"

                    def _append_event(self, text: str) -> None:
                        self.events.append(text)

                fake = FakeApp()
                app_module.EverQuestieApp._suggest_zone_from_quest(fake, quest)
                self.assertEqual(len(fake.events), 1)
                self.assertIn("not inferred from quest", fake.events[0])
                self.assertIn("Classic / P99-style", fake.events[0])
                self.assertIn("Stone Hive", fake.events[0])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
