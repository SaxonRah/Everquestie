from __future__ import annotations

import contextlib
import io
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

    def test_require_complete_rejects_in_progress_httrack_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "zone.html").write_text(
                self._page("https://everquest.allakhazam.com/db/zone.html?zone=1"),
                encoding="utf-8",
            )
            (root / "item.html.tmp").write_text(
                self._page("https://everquest.allakhazam.com/db/item.html?item=2"),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main([str(root), "--require-complete"])

            self.assertEqual(code, 2)
            self.assertIn("Temporary/in-progress files ignored: 1", stdout.getvalue())
            self.assertIn("mirror is still in progress", stderr.getvalue().casefold())

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

    def test_require_complete_accepts_tree_after_temp_files_are_gone(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "zone.html").write_text(
                self._page("https://everquest.allakhazam.com/db/zone.html?zone=1"),
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main([str(root), "--require-complete"])

            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
