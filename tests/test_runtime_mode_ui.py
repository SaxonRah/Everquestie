import unittest
from pathlib import Path
from types import SimpleNamespace

from eqquest.runtime_mode_ui import (
    database_mode_text,
    install_runtime_mode_ui,
    profile_capability_text,
)


class RuntimeModeUiTests(unittest.TestCase):
    @staticmethod
    def _profile_db(profile_id: str):
        return SimpleNamespace(
            knowledge_writable=False,
            knowledge_path=Path(r"C:\Everquestie\dist\everquestie-knowledge.sqlite3"),
            state_path=Path(r"C:\Users\Player\.eqquest\everquestie-user.sqlite3"),
            get_meta=lambda key, default="": profile_id if key == "world_profile" else default,
        )

    def test_packaged_mode_names_both_databases_and_profile(self):
        db = self._profile_db("p99")
        text = database_mode_text(db)
        self.assertIn("PACKAGED / IMMUTABLE", text)
        self.assertIn("Server: Classic / P99-style (Velious cap)", text)
        self.assertIn("everquestie-knowledge.sqlite3", text)
        self.assertIn("everquestie-user.sqlite3", text)

    def test_builder_mode_names_mutable_database_and_default_profile(self):
        db = SimpleNamespace(
            knowledge_writable=True,
            path=Path(r"C:\Users\Player\.eqquest\eqquest.sqlite3"),
            get_meta=lambda key, default="": default,
        )
        text = database_mode_text(db)
        self.assertIn("BUILDER / MUTABLE", text)
        self.assertIn("Server: Live (default)", text)
        self.assertIn("eqquest.sqlite3", text)

    def test_diagnostics_degrade_cleanly_when_profile_storage_is_unavailable(self):
        db = SimpleNamespace(
            knowledge_writable=True,
            path=Path(r"C:\temp\working.sqlite3"),
        )
        text = database_mode_text(db)
        self.assertIn("Server: not reported", text)
        self.assertIn("working.sqlite3", text)
        capability = profile_capability_text(db)
        self.assertIn("Profile: not reported", capability)
        self.assertIn("source compatibility not reported", capability)

    def test_live_capabilities_name_profile_aligned_live_client_mechanics(self):
        text = profile_capability_text(self._profile_db("live"))
        self.assertIn("Profile: Live (default)", text)
        self.assertIn("Routing / entity availability: Live profile policy", text)
        self.assertIn("exact installed Live-client support-file facts", text)
        self.assertNotIn("not a profile-specific ruleset projection", text)

    def test_p99_capabilities_separate_era_policy_from_live_client_mechanics(self):
        text = profile_capability_text(self._profile_db("p99"))
        self.assertIn("Profile: Classic / P99-style (Velious cap)", text)
        self.assertIn("profile-filtered topology / lifecycle through Velious", text)
        self.assertIn("Live-client source facts only", text)
        self.assertIn("not a profile-specific ruleset projection", text)

    def test_unrestricted_capabilities_do_not_claim_custom_server_mechanics(self):
        text = profile_capability_text(self._profile_db("unrestricted"))
        self.assertIn("Profile: Unrestricted / custom", text)
        self.assertIn("unrestricted confirmed topology / lifecycle projection", text)
        self.assertIn("not a custom-server ruleset projection", text)

    def test_installer_appends_capabilities_to_database_diagnostics(self):
        from eqquest import app as app_module

        original = app_module.EverQuestieApp

        class FakeApp:
            def _build_ui(self):
                pass

            def _database_diagnostic_text(self):
                return "BASE DATABASE DIAGNOSTICS"

            def _world_profile_changed(self, event=None):
                pass

        try:
            app_module.EverQuestieApp = FakeApp
            install_runtime_mode_ui()
            fake = SimpleNamespace(db=self._profile_db("p99"))
            text = app_module.EverQuestieApp._database_diagnostic_text(fake)
            self.assertTrue(text.startswith("BASE DATABASE DIAGNOSTICS"))
            self.assertIn("Server profile capabilities:", text)
            self.assertIn("Classic / P99-style", text)
            self.assertIn("Live-client source facts only", text)
        finally:
            app_module.EverQuestieApp = original


if __name__ == "__main__":
    unittest.main()
