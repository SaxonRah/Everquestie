from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from eqquest.db import Database
from eqquest.entity_lifecycle_records import upsert_lifecycle_record
from eqquest.mechanics_context_ui import MechanicsContextFrame
from eqquest.mechanics_profile_availability import (
    mechanics_profile_source_notice,
    profiled_spell_stacking_text,
)
from eqquest.profile_availability_ui import install_profile_availability_ui
from eqquest.world_profile_ui import install_world_profile_ui
from eqquest.world_profiles import set_active_world_profile, world_profile


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class _Tree:
    def __init__(self):
        self.inserted: list[tuple] = []

    def get_children(self):
        return ()

    def delete(self, *_items) -> None:
        pass

    def insert(self, _parent, _where, *, values) -> None:
        self.inserted.append(tuple(values))


class MechanicsProfileAvailabilityTests(unittest.TestCase):
    def test_live_mechanics_notice_names_exact_live_client_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "working.sqlite3")
            try:
                set_active_world_profile(db, "live")
                text = mechanics_profile_source_notice(db)
                self.assertIn("Live (default)", text)
                self.assertIn("exact installed Live-client support files", text)
                self.assertNotIn("not a profile-specific ruleset", text)
            finally:
                db.close()

    def test_p99_mechanics_notice_refuses_to_claim_live_caps_as_p99_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "working.sqlite3")
            try:
                set_active_world_profile(db, "p99")
                text = mechanics_profile_source_notice(db)
                self.assertIn("Classic / P99-style", text)
                self.assertIn("installed Live-client support files", text)
                self.assertIn("not a profile-specific ruleset", text)
                self.assertIn("does not reinterpret Live-client caps", text)
            finally:
                db.close()

    def test_class_refresh_appends_profile_source_notice_without_changing_summary(self) -> None:
        rendered: list[str] = []
        fake = SimpleNamespace(
            db=object(),
            class_var=_Var("Warrior"),
            level_var=_Var(60),
            skills_tree=_Tree(),
            class_summary=object(),
            _set_text=lambda _widget, text: rendered.append(text),
        )
        context = SimpleNamespace()
        with patch(
            "eqquest.mechanics_context_ui.build_class_mechanics_context",
            return_value=(context, "exact"),
        ), patch(
            "eqquest.mechanics_context_ui.mechanics_context_summary",
            return_value="CANONICAL CLASS SUMMARY",
        ), patch(
            "eqquest.mechanics_context_ui.mechanics_profile_source_notice",
            return_value="PROFILE SOURCE NOTICE",
        ), patch(
            "eqquest.mechanics_context_ui.mechanics_skill_rows",
            return_value=[],
        ):
            MechanicsContextFrame.refresh_class_level(fake)

        self.assertEqual(
            rendered,
            ["CANONICAL CLASS SUMMARY\n\nPROFILE SOURCE NOTICE"],
        )

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

    def test_global_profile_change_refreshes_class_and_selected_spell_mechanics(self) -> None:
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
                        refresh_class_level=lambda: calls.append("mechanics-class"),
                        _spell_selected=lambda: calls.append("mechanics-spell"),
                    ),
                    _show_entity=lambda: calls.append("knowledge"),
                    _refresh_guidance=lambda: calls.append("guidance"),
                )

                app_module.EverQuestieApp._world_profile_changed(fake)

                self.assertEqual(fake.world_profile_var.get(), profile.label)
                self.assertEqual(db.get_meta("world_profile", ""), "p99")
                self.assertIn("knowledge", calls)
                self.assertIn("guidance", calls)
                self.assertIn("mechanics-class", calls)
                self.assertIn("mechanics-spell", calls)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
