from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from eqquest.approved_travel_supplements import stage_builder_with_approved_travel_supplements
from eqquest.knowledge_snapshot import create_knowledge_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_TOOL = REPO_ROOT / "tools" / "create_release_smoke_fixture.py"
AUDIT_TOOL = REPO_ROOT / "tools" / "audit_release_inputs.py"
TRAVEL_DIR = REPO_ROOT / "builder-data" / "travel-supplements"
ZONE_ALIAS_DIR = REPO_ROOT / "builder-data" / "zone-aliases"


class ReleaseSmokeFixtureTests(unittest.TestCase):
    def test_fixture_compiles_current_reviewed_release_corpus_without_source_mutation(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            working = root / "working.sqlite3"
            staged = root / "staged.sqlite3"
            snapshot = root / "everquestie-knowledge.sqlite3"

            created = subprocess.run(
                [
                    sys.executable,
                    str(FIXTURE_TOOL),
                    "--output",
                    str(working),
                    "--force",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(created.returncode, 0, created.stderr or created.stdout)
            self.assertTrue(working.is_file())
            before = working.read_bytes()

            results = stage_builder_with_approved_travel_supplements(
                working,
                staged,
                TRAVEL_DIR,
                zone_alias_dir=ZONE_ALIAS_DIR,
            )
            self.assertEqual(len(results), 3)
            self.assertEqual(sum(result.edges for result in results), 9)
            self.assertEqual(working.read_bytes(), before)

            create_knowledge_snapshot(
                staged,
                snapshot,
                snapshot_version="windows-packaging-smoke-fixture",
            )
            audited = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT_TOOL),
                    str(snapshot),
                    "--json",
                    "--require-release-inputs",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(audited.returncode, 0, audited.stderr or audited.stdout)
            payload = json.loads(audited.stdout)
            self.assertTrue(payload["publish_ready"])
            self.assertEqual(
                payload["actual"],
                {
                    "zone_alias_supplements": 1,
                    "zone_aliases": 1,
                    "travel_supplements": 3,
                    "travel_edges": 9,
                },
            )


if __name__ == "__main__":
    unittest.main()
