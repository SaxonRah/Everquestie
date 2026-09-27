from __future__ import annotations

from pathlib import Path
import os
import queue
import tempfile
import time
import unittest

from eqquest.tailer import LogTailer


class LogTailerTests(unittest.TestCase):
    def _get(self, q: queue.Queue[str], timeout: float = 3.0) -> str:
        return q.get(timeout=timeout)

    def test_continues_following_multiple_appends_after_start(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "eqlog_Test_server.txt"
            path.write_text("historical line\n", encoding="utf-8")

            seen: queue.Queue[str] = queue.Queue()
            tailer = LogTailer(path, seen.put, poll_seconds=0.02, start_at_end=True)
            tailer.start()
            try:
                time.sleep(0.05)
                with path.open("a", encoding="utf-8", newline="") as handle:
                    handle.write("first live line\n")
                    handle.flush()

                self.assertEqual(self._get(seen), "first live line\n")

                with path.open("a", encoding="utf-8", newline="") as handle:
                    handle.write("second live line\n")
                    handle.flush()

                self.assertEqual(self._get(seen), "second live line\n")
                self.assertTrue(tailer.running)
            finally:
                tailer.stop()

    @unittest.skipIf(os.name == "nt", "Windows does not allow replacing this open log handle")
    def test_reopens_when_log_path_is_replaced(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            path = root / "eqlog_Test_server.txt"
            path.write_text("historical line\n", encoding="utf-8")

            seen: queue.Queue[str] = queue.Queue()
            tailer = LogTailer(path, seen.put, poll_seconds=0.02, start_at_end=True)
            tailer.start()
            try:
                time.sleep(0.05)
                replacement = root / "replacement.txt"
                replacement.write_text("replacement live line\n", encoding="utf-8")
                replacement.replace(path)

                self.assertEqual(self._get(seen), "replacement live line\n")

                with path.open("a", encoding="utf-8", newline="") as handle:
                    handle.write("replacement second line\n")
                    handle.flush()

                self.assertEqual(self._get(seen), "replacement second line\n")
                self.assertTrue(tailer.running)
            finally:
                tailer.stop()


    def test_recovers_when_log_is_truncated_in_place(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "eqlog_Test_server.txt"
            path.write_text(
                "a deliberately long historical line that places EOF well past the rewrite\n",
                encoding="utf-8",
            )

            seen: queue.Queue[str] = queue.Queue()
            tailer = LogTailer(path, seen.put, poll_seconds=0.02, start_at_end=True)
            tailer.start()
            try:
                time.sleep(0.05)
                with path.open("w", encoding="utf-8", newline="") as handle:
                    handle.write("new live line\n")
                    handle.flush()

                self.assertEqual(self._get(seen), "new live line\n")
                self.assertTrue(tailer.running)
            finally:
                tailer.stop()


if __name__ == "__main__":
    unittest.main()
