from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from eqquest.db import Database
from eqquest.entity_lifecycle_records import upsert_lifecycle_record
from eqquest.mechanics_profile_availability import profiled_spell_stacking_text
from eqquest.profile_availability_ui import install_profile_availability_ui
from eqquest.world_profile_ui import install_world_profile_ui
from eqquest.world_profiles import set_active_world_profile, world_profile


class _Var:
    def __init__(self, value: str):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class MechanicsProfileAvailabilityTests(unittest.TestCase):
    def test_profiled_spell_output_keeps_stacking_and_appends_p99_availability(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "working.sqlite3")
            try:
                spell = db.upsert_entity(
                    kind="spell",
                    name="A Post Velious Spell",
                    external_id="4242",
                    external_namespace="eqclient:spell",
                    merge_by_name=False,
                )
                source = db.upsert_source_page(
                    url="https://everquest.allakhazam.com/db/spell.html?spell=4242",
                    title="A Post Velious Spell :: EverQuest",
                    entity_type="spell",
                    sha256="spell-4242",
                    plain_text="",
                    raw_html="",
                    source_name="Allakhazam",
                    source_kind="local_mirror",
                    source_key="spell:4242",
                )
                upsert_lifecycle_record(
                    db,
                    source_page_id=source,
                    entity_kind="spell",
                    source_external_id="spell:4242",
                    source_entity_name="A Post Velious Spell",
                    field_name="expansion",
                    field_value="Planes of Power",
                    evidence="fixture Quick Facts / Expansion",
                    entity_id=spell,
                )
                set_active_world_profile(db, "p99")

                with patch(
                    "eqquest.mechanics_profile_availability.spell_stacking_text",
                    return_value="CANONICAL STACKING SENTINEL",
                ):
                    text = profiled_spell_stacking_text(db, spell)

                self.assertTrue(text.startswith("CANONICAL STACKING SENTINEL"))
                self.assertIn("Gameplay profile availability:", text)
                self.assertIn("Classic / P99-style", text)
                self.assertIn("Status: OUTSIDE PROFILE", text)
                self.assertIn("Direct expansion: Planes of Power", text)
            finally:
                db.close()

    def test_global_profile_change_refreshes_selected_mechanics_spell(self) -> None:
        from eqquest import app as app_module
        from eqquest import mechanics_context_ui as mechanics_ui
        from eqquest.mechanics_profile_availability import profiled_spell_stacking_text as renderer

        install_world_profile_ui()
        install_profile_availability_ui()
        self.assertIs(mechanics_ui.spell_stacking_text, renderer)

        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "working.sqlite3")
            try:
                calls: list[str] = []
                profile = world_profile("p99")
                fake = SimpleNamespace(
                    db=db,
                    world_profile_var=_Var(profile.label),
                    status=SimpleNamespace(set=lambda text: calls.append("status:" + text)),
                    mechanics_view=SimpleNamespace(
                        _spell_selected=lambda: calls.append("mechanics")
                    ),
                    _show_entity=lambda: calls.append("knowledge"),
                    _refresh_guidance=lambda: calls.append("guidance"),
                )

                app_module.EverQuestieApp._world_profile_changed(fake)

                self.assertEqual(fake.world_profile_var.get(), profile.label)
                self.assertEqual(db.get_meta("world_profile", ""), "p99")
                self.assertIn("knowledge", calls)
                self.assertIn("guidance", calls)
                self.assertIn("mechanics", calls)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
