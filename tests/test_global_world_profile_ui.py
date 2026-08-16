from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from eqquest.db import Database
from eqquest.world_profile_ui import install_world_profile_ui
from eqquest.world_profiles import active_world_profile_id


class _Var:
    def __init__(self, value: str = ""):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class GlobalWorldProfileUITests(unittest.TestCase):
    def test_installer_places_profile_ownership_on_application(self):
        from eqquest import app as app_module
        from eqquest import route_guidance_ui as travel_ui

        install_world_profile_ui()

        self.assertTrue(
            getattr(
                app_module.EverQuestieApp._build_ui,
                "_everquestie_global_world_profile_ui",
                False,
            )
        )
        self.assertTrue(callable(getattr(app_module.EverQuestieApp, "_world_profile_changed", None)))
        self.assertTrue(
            getattr(
                travel_ui.RouteGuidanceFrame.show_zone_context,
                "_everquestie_world_profile_ui",
                False,
            )
        )

    def test_application_profile_callback_persists_global_user_choice(self):
        from eqquest import app as app_module

        install_world_profile_ui()
        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                class FakeApp:
                    def __init__(self):
                        self.db = db
                        self.world_profile_var = _Var("Classic / P99-style (Velious cap)")
                        self.status = _Status()

                fake = FakeApp()
                app_module.EverQuestieApp._world_profile_changed(fake)

                self.assertEqual(active_world_profile_id(db), "p99")
                self.assertEqual(fake.world_profile_var.get(), "Classic / P99-style (Velious cap)")
                self.assertIn("Server profile: Classic / P99-style", fake.status.value)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
