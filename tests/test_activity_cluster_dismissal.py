from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from eqquest.activity_clusters_ui import install_activity_clusters_ui
from eqquest.activity_pathway_dismiss_ui import install_activity_pathway_dismiss_ui
from eqquest.activity_pathways import PathwayEvidence, PathwaySuggestion
from eqquest.activity_pathways_ui import install_activity_pathways_ui
from eqquest.db import Database
from eqquest.events import Event


class _Status:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


class ActivityClusterDismissalTests(unittest.TestCase):
    def test_current_activity_never_names_session_dismissed_pathway(self):
        from eqquest import app as app_module

        # The projection must be correct even if decorators were installed earlier by
        # another test/launcher order; Current Activity independently checks the set.
        install_activity_pathways_ui()
        install_activity_pathway_dismiss_ui()
        install_activity_clusters_ui()

        with tempfile.TemporaryDirectory() as tempdir:
            db = Database(Path(tempdir) / "working.sqlite3")
            try:
                for _ in range(3):
                    db.add_event(Event(kind="kill", raw="kill", actor="Cluster Mob"))

                suggestion = PathwaySuggestion(
                    quest_id=77,
                    quest_name="Dismissed Quest",
                    score=80,
                    evidence=(
                        PathwayEvidence(
                            "kill",
                            "Cluster Mob",
                            3,
                            1,
                            "Defeat Cluster Mob",
                            "Test Zone",
                        ),
                    ),
                    profile_status="available",
                )
                fake = SimpleNamespace(
                    db=db,
                    state_model=SimpleNamespace(current_zone="Test Zone"),
                    _activity_session_start_event_id=0,
                    _activity_pathway_by_item={"pathway:77": suggestion},
                    _activity_pathway_dismissed_quests={77},
                    activity_cluster_status=_Status(),
                    tailer=object(),
                )

                app_module.EverQuestieApp._refresh_activity_cluster(fake)

                self.assertIn("Cluster Mob", fake.activity_cluster_status.value)
                self.assertNotIn("Dismissed Quest", fake.activity_cluster_status.value)
                self.assertNotIn("Related pathways", fake.activity_cluster_status.value)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
