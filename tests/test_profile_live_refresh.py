from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.db import Database
from eqquest.profile_availability_ui import install_profile_availability_ui
from eqquest.world_profile_ui import install_world_profile_ui
from eqquest.world_profiles import world_profile


class _Var:
    def __init__(self, value: str):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = str(value)


class ProfileLiveRefreshTests(unittest.TestCase):
    def test_profile_change_immediately_refreshes_composed_live_intelligence(self):
        from eqquest import app as app_module

        install_world_profile_ui()
        install_profile_availability_ui()

        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                profile = world_profile("p99")
                calls: list[object] = []
                fake = SimpleNamespace(
                    db=db,
                    world_profile_var=_Var(profile.label),
                    status=SimpleNamespace(
                        set=lambda text: calls.append(("status", str(text)))
                    ),
                    _show_entity=lambda: calls.append("knowledge"),
                    _refresh_guidance=lambda: calls.append("guidance"),
                    _refresh_activity_pathways=lambda force=False: calls.append(
                        ("live", bool(force))
                    ),
                    mechanics_view=SimpleNamespace(
                        refresh_class_level=lambda: calls.append("mechanics-class"),
                        _spell_selected=lambda: calls.append("mechanics-spell"),
                    ),
                )

                app_module.EverQuestieApp._world_profile_changed(fake)

                self.assertEqual(db.get_meta("world_profile", ""), "p99")
                self.assertIn(("live", True), calls)
                self.assertEqual(calls.count(("live", True)), 1)
                self.assertIn("knowledge", calls)
                self.assertIn("guidance", calls)
                self.assertIn("mechanics-class", calls)
                self.assertIn("mechanics-spell", calls)
            finally:
                db.close()

    def test_live_refresh_failure_does_not_break_other_profile_surfaces(self):
        from eqquest import app as app_module

        install_world_profile_ui()
        install_profile_availability_ui()

        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                profile = world_profile("p99")
                calls: list[str] = []

                def broken_live(*, force=False):
                    self.assertTrue(force)
                    calls.append("live-attempt")
                    raise RuntimeError("projection unavailable")

                fake = SimpleNamespace(
                    db=db,
                    world_profile_var=_Var(profile.label),
                    status=SimpleNamespace(set=lambda _text: None),
                    _show_entity=lambda: calls.append("knowledge"),
                    _refresh_guidance=lambda: calls.append("guidance"),
                    _refresh_activity_pathways=broken_live,
                    mechanics_view=SimpleNamespace(
                        refresh_class_level=lambda: calls.append("mechanics-class"),
                        _spell_selected=lambda: calls.append("mechanics-spell"),
                    ),
                )

                app_module.EverQuestieApp._world_profile_changed(fake)

                self.assertEqual(db.get_meta("world_profile", ""), "p99")
                self.assertEqual(calls.count("live-attempt"), 1)
                self.assertIn("knowledge", calls)
                self.assertIn("guidance", calls)
                self.assertIn("mechanics-class", calls)
                self.assertIn("mechanics-spell", calls)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
