import json
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace

from eqquest.runtime_mode_ui import (
    database_mode_text,
    install_runtime_mode_ui,
    profile_capability_text,
    release_knowledge_inputs_text,
)
from eqquest.travel_supplement import TRAVEL_SUPPLEMENT_SOURCE_KIND
from eqquest.zone_alias_supplement import (
    ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE,
    ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
)


class RuntimeModeUiTests(unittest.TestCase):
    @staticmethod
    def _profile_db(profile_id: str, extra_meta: dict[str, str] | None = None):
        meta = {"world_profile": profile_id}
        meta.update(extra_meta or {})

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE app_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE source_pages(
                id INTEGER PRIMARY KEY,
                source_name TEXT,
                source_kind TEXT,
                source_key TEXT,
                source_version TEXT,
                entity_type TEXT
            );
            CREATE TABLE entity_aliases(
                id INTEGER PRIMARY KEY,
                source_page_id INTEGER,
                alias_type TEXT
            );
            CREATE TABLE zone_travel_edges(
                id INTEGER PRIMARY KEY,
                source_name TEXT,
                source_kind TEXT,
                source_key TEXT,
                source_version TEXT,
                status TEXT,
                target_zone_entity_id INTEGER,
                evidence TEXT,
                data_json TEXT
            );
            """
        )
        for key, value in (extra_meta or {}).items():
            conn.execute("INSERT INTO app_meta(key,value) VALUES(?,?)", (key, value))

        def count(key: str) -> int:
            try:
                return max(0, int((extra_meta or {}).get(key, "0")))
            except (TypeError, ValueError):
                return 0

        alias_supplements = count("approved_zone_alias_supplement_count")
        aliases = count("approved_zone_alias_count")
        if alias_supplements and aliases:
            for index in range(aliases):
                source_name = f"Reviewed alias supplement {index % alias_supplements + 1}"
                cursor = conn.execute(
                    """
                    INSERT INTO source_pages(
                        source_name,source_kind,source_key,source_version,entity_type
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        source_name,
                        ZONE_ALIAS_SUPPLEMENT_SOURCE_KIND,
                        f"alias-{index + 1}",
                        "1",
                        "zone_alias",
                    ),
                )
                conn.execute(
                    "INSERT INTO entity_aliases(source_page_id,alias_type) VALUES(?,?)",
                    (int(cursor.lastrowid), ZONE_ALIAS_SUPPLEMENT_ALIAS_TYPE),
                )

        travel_supplements = count("approved_travel_supplement_count")
        travel_edges = count("approved_travel_supplement_edge_count")
        if travel_supplements and travel_edges:
            for index in range(travel_edges):
                source_name = f"Reviewed travel supplement {index % travel_supplements + 1}"
                source_key = f"travel-edge-{index + 1}"
                conn.execute(
                    """
                    INSERT INTO zone_travel_edges(
                        source_name,source_kind,source_key,source_version,status,
                        target_zone_entity_id,evidence,data_json
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        source_name,
                        TRAVEL_SUPPLEMENT_SOURCE_KIND,
                        source_key,
                        "1",
                        "linked",
                        10000 + index,
                        "Reviewed travel evidence.",
                        json.dumps(
                            {
                                "manifest_schema_version": 1,
                                "manifest_source_key": source_key,
                            }
                        ),
                    ),
                )
        conn.commit()

        return SimpleNamespace(
            knowledge_writable=False,
            knowledge_path=Path(r"C:\Everquestie\dist\everquestie-knowledge.sqlite3"),
            state_path=Path(r"C:\Users\Player\.eqquest\everquestie-user.sqlite3"),
            conn=conn,
            get_meta=lambda key, default="": meta.get(key, default),
        )

    @staticmethod
    def _release_meta() -> dict[str, str]:
        return {
            "approved_zone_alias_supplement_count": "1",
            "approved_zone_alias_count": "1",
            "approved_travel_supplement_count": "3",
            "approved_travel_supplement_edge_count": "22",
        }

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

    def test_packaged_release_inputs_report_reviewed_counts(self):
        text = release_knowledge_inputs_text(self._profile_db("live", self._release_meta()))
        self.assertIn("Release knowledge inputs:", text)
        self.assertIn("Reviewed zone aliases: 1 aliases from 1 supplement(s)", text)
        self.assertIn("Reviewed travel: 22 edges from 3 supplement(s)", text)

    def test_packaged_travel_only_release_inputs_render_only_recorded_family(self):
        text = release_knowledge_inputs_text(
            self._profile_db(
                "live",
                {
                    "approved_travel_supplement_count": "1",
                    "approved_travel_supplement_edge_count": "2",
                },
            )
        )
        self.assertIn("Reviewed travel: 2 edges from 1 supplement(s)", text)
        self.assertNotIn("Reviewed zone aliases:", text)
        self.assertNotIn("FAILED", text)

    def test_packaged_release_inputs_ignore_user_meta_style_shadow(self):
        db = self._profile_db("live", self._release_meta())
        original_get_meta = db.get_meta
        db.get_meta = lambda key, default="": (
            "999"
            if key == "approved_travel_supplement_edge_count"
            else original_get_meta(key, default)
        )

        text = release_knowledge_inputs_text(db)
        self.assertIn("Reviewed travel: 22 edges from 3 supplement(s)", text)
        self.assertNotIn("999", text)

    def test_packaged_release_inputs_surface_audit_failure_not_stale_count(self):
        db = self._profile_db("live", self._release_meta())
        db.conn.execute(
            "UPDATE app_meta SET value='23' WHERE key='approved_travel_supplement_edge_count'"
        )
        db.conn.commit()

        text = release_knowledge_inputs_text(db)
        self.assertIn("Reviewed-input audit: FAILED", text)
        self.assertIn("records 23", text)
        self.assertIn("contains 22", text)
        self.assertNotIn("Reviewed travel: 23 edges", text)

    def test_builder_release_inputs_stay_hidden_even_if_counters_exist(self):
        meta = self._release_meta()
        db = SimpleNamespace(
            knowledge_writable=True,
            get_meta=lambda key, default="": meta.get(key, default),
        )
        self.assertEqual(release_knowledge_inputs_text(db), "")

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
            fake = SimpleNamespace(db=self._profile_db("p99", self._release_meta()))
            text = app_module.EverQuestieApp._database_diagnostic_text(fake)
            self.assertTrue(text.startswith("BASE DATABASE DIAGNOSTICS"))
            self.assertIn("Server profile capabilities:", text)
            self.assertIn("Classic / P99-style", text)
            self.assertIn("Live-client source facts only", text)
            self.assertIn("Release knowledge inputs:", text)
            self.assertIn("Reviewed travel: 22 edges from 3 supplement(s)", text)
        finally:
            app_module.EverQuestieApp = original


if __name__ == "__main__":
    unittest.main()
