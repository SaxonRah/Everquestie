from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from eqquest.mechanics_context import (
    ACMitigationContext,
    BaseStatsContext,
    ClassIdentity,
    ClassMechanicsContext,
    MechanicsSource,
    SkillCapContext,
)
from eqquest.mechanics_context_ui import (
    MechanicsContextFrame,
    mechanics_context_summary,
    mechanics_skill_rows,
)
from eqquest.runtime_policy import install_runtime_policy


class MechanicsContextUITests(unittest.TestCase):
    @staticmethod
    def _source(key: str) -> MechanicsSource:
        return MechanicsSource(
            source_page_id=1,
            source_name="EverQuest Client",
            source_kind="local_game_files",
            source_key=key,
            source_version="live-client",
            local_path="",
            url=f"eqclient://{key}",
        )

    def _context(self) -> ClassMechanicsContext:
        return ClassMechanicsContext(
            identity=ClassIdentity(10, 1, "Warrior", "name"),
            requested_level=61,
            base_stats=BaseStatsContext(
                level=61,
                hp=1000.0,
                mana=0.0,
                endurance=800.0,
                hp_regen=10.0,
                mana_regen=0.0,
                endurance_regen=8.0,
                source=self._source("Resources/basedata.txt"),
            ),
            ac_mitigation=ACMitigationContext(
                level=61,
                ac_cap=300.0,
                soft_cap_multiplier=0.4,
                source=self._source("Resources/ACMitigation.txt"),
            ),
            skills=(
                SkillCapContext(
                    skill_entity_id=20,
                    skill_id=76,
                    name="Triple Attack",
                    cap=25,
                    row_level=61,
                    first_positive_level=60,
                    new_this_level=False,
                    changed_this_level=True,
                    source=self._source("Resources/skillcaps.txt"),
                ),
                SkillCapContext(
                    skill_entity_id=21,
                    skill_id=0,
                    name="1H Blunt",
                    cap=250,
                    row_level=60,
                    first_positive_level=1,
                    new_this_level=False,
                    changed_this_level=False,
                    source=self._source("Resources/skillcaps.txt"),
                ),
            ),
        )

    def test_summary_uses_exact_context_and_source_provenance(self):
        text = mechanics_context_summary(self._context())
        self.assertIn("Warrior | level 61", text)
        self.assertIn("missing base/AC levels are not interpolated", text)
        self.assertIn("HP: 1000.0", text)
        self.assertIn("AC cap: 300.0", text)
        self.assertIn("EverQuest Client live-client", text)

    def test_summary_keeps_missing_exact_rows_missing(self):
        context = self._context()
        missing = ClassMechanicsContext(
            identity=context.identity,
            requested_level=62,
            base_stats=None,
            ac_mitigation=None,
            skills=context.skills,
        )
        text = mechanics_context_summary(missing)
        self.assertIn("Base resources: no exact-level row", text)
        self.assertIn("AC mitigation: no exact-level row", text)
        self.assertNotIn("HP: 1000.0", text)

    def test_skill_rows_surface_progression_without_recomputing_it(self):
        rows = mechanics_skill_rows(self._context())
        self.assertEqual(rows[0], ("Triple Attack", 25, "cap changed", "EverQuest Client live-client"))
        self.assertEqual(rows[1], ("1H Blunt", 250, "from level 60", "EverQuest Client live-client"))

    def test_spell_selection_delegates_to_canonical_stacking_renderer(self):
        rendered: list[tuple[object, str]] = []
        db = object()
        fake = SimpleNamespace(
            db=db,
            spell_tree=SimpleNamespace(selection=lambda: ("spell-row",)),
            _spell_entity_by_item={"spell-row": 42},
            stacking_text=object(),
            _set_text=lambda widget, text: rendered.append((widget, text)),
        )
        with patch(
            "eqquest.mechanics_context_ui.spell_stacking_text",
            return_value="canonical stacking sentinel",
        ) as renderer:
            MechanicsContextFrame._spell_selected(fake)

        renderer.assert_called_once_with(db, 42)
        self.assertEqual(rendered, [(fake.stacking_text, "canonical stacking sentinel")])

    def test_spell_selection_without_selection_does_not_query_context(self):
        fake = SimpleNamespace(
            db=object(),
            spell_tree=SimpleNamespace(selection=lambda: ()),
            _spell_entity_by_item={},
            stacking_text=object(),
            _set_text=lambda *_args: self.fail("no text should be written"),
        )
        with patch("eqquest.mechanics_context_ui.spell_stacking_text") as renderer:
            MechanicsContextFrame._spell_selected(fake)
        renderer.assert_not_called()

    def test_packaged_runtime_substitutes_context_backed_mechanics_frame(self):
        install_runtime_policy()
        from eqquest import app as app_module
        from eqquest.mechanics_context_ui import MechanicsContextFrame as RuntimeMechanicsFrame

        self.assertIs(app_module.MechanicsFrame, RuntimeMechanicsFrame)


if __name__ == "__main__":
    unittest.main()
