from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch
import unittest

from eqquest.activity_pathways_ui import install_activity_pathways_ui


class ActivitySessionRecapUITests(unittest.TestCase):
    def test_recap_uses_current_monitoring_boundary_start_zone_and_pathway_count(self):
        from eqquest import app as app_module

        install_activity_pathways_ui()

        class FakeApp:
            pass

        fake = FakeApp()
        fake.db = object()
        fake.state_model = SimpleNamespace(current_zone="Zone B")
        fake._activity_session_start_event_id = 123
        fake._activity_session_start_zone = "Zone A"
        fake._activity_pathway_by_item = {"one": object(), "two": object()}
        summary = object()

        with (
            patch(
                "eqquest.activity_pathways_ui.session_activity_summary",
                return_value=summary,
            ) as build_summary,
            patch(
                "eqquest.activity_pathways_ui.session_activity_text",
                return_value="recap text",
            ) as render,
            patch("eqquest.activity_pathways_ui.messagebox.showinfo") as showinfo,
        ):
            app_module.EverQuestieApp._activity_session_recap(fake)

        build_summary.assert_called_once_with(
            fake.db,
            123,
            starting_zone="Zone A",
            current_zone="Zone B",
            pathway_count=2,
        )
        render.assert_called_once_with(summary)
        showinfo.assert_called_once_with("EverQuestie Session Recap", "recap text")


if __name__ == "__main__":
    unittest.main()
