from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from tools.audit_allakhazam_mirror import main


class AllakhazamMirrorCompletionGateTests(unittest.TestCase):
    @staticmethod
    def _page(url: str) -> str:
        return (
            '<html><head><link rel="canonical" href="'
            + url
            + '"></head><body>fixture</body></html>'
        )

    @staticmethod
    def _project(root: Path) -> tuple[Path, Path]:
        project = root / "project"
        mirror = project / "everquest.allakhazam.com"
        mirror.mkdir(parents=True)
        return project, mirror

    @staticmethod
    def _completed_log() -> str:
        return (
            "HTTrack Website Copier/3.49-2 launched on fixture\n"
            "HTTrack Website Copier/3.49-2 mirror complete in 1 minutes 2 seconds : "
            "10 links scanned, 9 files written\n"
        )

    def test_require_complete_rejects_in_progress_httrack_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, mirror = self._project(Path(temp))
            (project / "hts-log.txt").write_text(self._completed_log(), encoding="utf-8")
            (mirror / "zone.html").write_text(
                self._page("https://everquest.allakhazam.com/db/zone.html?zone=1"),
                encoding="utf-8",
            )
            (mirror / "item.html.tmp").write_text(
                self._page("https://everquest.allakhazam.com/db/item.html?item=2"),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        str(mirror),
                        "--httrack-project",
                        str(project),
                        "--require-complete",
                    ]
                )

            self.assertEqual(code, 2)
            self.assertIn("Temporary/in-progress files ignored: 1", stdout.getvalue())
            self.assertIn("temporary httrack file", stderr.getvalue().casefold())

    def test_default_audit_remains_diagnostic_for_in_progress_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "item.html.tmp").write_text(
                self._page("https://everquest.allakhazam.com/db/item.html?item=2"),
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main([str(root)])

            self.assertEqual(code, 0)

    def test_require_complete_requires_explicit_httrack_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "zone.html").write_text(
                self._page("https://everquest.allakhazam.com/db/zone.html?zone=1"),
                encoding="utf-8",
            )

            stderr = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                code = main([str(root), "--require-complete"])

            self.assertEqual(code, 2)
            self.assertIn("requires --httrack-project", stderr.getvalue().casefold())

    def test_require_complete_rejects_cleanly_interrupted_run_even_without_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, mirror = self._project(Path(temp))
            (mirror / "zone.html").write_text(
                self._page("https://everquest.allakhazam.com/db/zone.html?zone=1"),
                encoding="utf-8",
            )
            (project / "hts-log.txt").write_text(
                "Info: Exit requested by shell or user\n"
                + self._completed_log()
                + "* * MIRROR ABORTED! * *\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(
                    [
                        str(mirror),
                        "--httrack-project",
                        str(project),
                        "--json",
                        "--require-complete",
                    ]
                )

            self.assertEqual(code, 2)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["httrack_run_state"], "interrupted")
            self.assertTrue(payload["httrack_completion_summary_present"])
            self.assertIn("mirror aborted", payload["httrack_interruption_markers"])
            self.assertIn("not canonical-complete", stderr.getvalue().casefold())

    def test_require_complete_rejects_active_lock_even_with_completed_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, mirror = self._project(Path(temp))
            (mirror / "zone.html").write_text(
                self._page("https://everquest.allakhazam.com/db/zone.html?zone=1"),
                encoding="utf-8",
            )
            (project / "hts-log.txt").write_text(self._completed_log(), encoding="utf-8")
            (project / "hts-in_progress.lock").write_text("fixture", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                code = main(
                    [
                        str(mirror),
                        "--httrack-project",
                        str(project),
                        "--json",
                        "--require-complete",
                    ]
                )

            self.assertEqual(code, 2)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["httrack_run_state"], "active")
            self.assertTrue(payload["httrack_lock_file_present"])

    def test_require_complete_fails_closed_when_httrack_log_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, mirror = self._project(Path(temp))
            (mirror / "zone.html").write_text(
                self._page("https://everquest.allakhazam.com/db/zone.html?zone=1"),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                code = main(
                    [
                        str(mirror),
                        "--httrack-project",
                        str(project),
                        "--json",
                        "--require-complete",
                    ]
                )

            self.assertEqual(code, 2)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["httrack_run_state"], "unknown")
            self.assertFalse(payload["httrack_log_file_present"])

    def test_require_complete_accepts_confirmed_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project, mirror = self._project(Path(temp))
            (mirror / "zone.html").write_text(
                self._page("https://everquest.allakhazam.com/db/zone.html?zone=1"),
                encoding="utf-8",
            )
            (project / "hts-log.txt").write_text(self._completed_log(), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                code = main(
                    [
                        str(mirror),
                        "--httrack-project",
                        str(project),
                        "--json",
                        "--require-complete",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["httrack_run_state"], "completed")
            self.assertTrue(payload["httrack_completion_summary_present"])
            self.assertEqual(payload["httrack_interruption_markers"], [])


if __name__ == "__main__":
    unittest.main()
