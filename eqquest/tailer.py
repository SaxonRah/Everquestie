from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable


class LogTailer:
    def __init__(
        self,
        path: str | Path,
        on_line: Callable[[str], None],
        poll_seconds: float = 0.20,
        start_at_end: bool = True,
    ) -> None:
        self.path = Path(path)
        self.on_line = on_line
        self.poll_seconds = poll_seconds
        self.start_at_end = start_at_end
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="eqquest-logtail",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        last_inode_size = -1

        while not self._stop.is_set():
            try:
                with self.path.open(
                    "r",
                    encoding="utf-8",
                    errors="replace",
                    newline="",
                ) as f:
                    if self.start_at_end:
                        f.seek(0, os.SEEK_END)
                    self.start_at_end = False

                    while not self._stop.is_set():
                        pos = f.tell()
                        line = f.readline()

                        if line:
                            self.on_line(line)
                            continue

                        # EQ or the user may truncate/replace a log. If the file shrank,
                        # reopen from the beginning rather than remaining past EOF.
                        try:
                            size = self.path.stat().st_size
                        except FileNotFoundError:
                            break

                        if size < pos:
                            break

                        time.sleep(self.poll_seconds)

            except (FileNotFoundError, PermissionError, OSError):
                time.sleep(max(self.poll_seconds, 0.5))
