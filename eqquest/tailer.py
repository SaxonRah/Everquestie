from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable


class LogTailer:
    """Continuously follow one EverQuest log file.

    EQ normally appends to a stable log path, but Windows tools/launchers can also
    truncate or replace the file while EverQuestie is running. The follower therefore
    treats the pathname as authoritative and periodically verifies that the open handle
    still refers to the same file. It follows in binary mode so file positions are real
    byte offsets and EOF handling is independent of TextIOWrapper decoder state.
    """

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
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.poll_seconds * 5.0))

    @staticmethod
    def _same_file(handle_stat, path_stat) -> bool:
        """Return whether an open handle and pathname still identify the same file."""
        handle_ino = int(getattr(handle_stat, "st_ino", 0) or 0)
        path_ino = int(getattr(path_stat, "st_ino", 0) or 0)
        handle_dev = int(getattr(handle_stat, "st_dev", 0) or 0)
        path_dev = int(getattr(path_stat, "st_dev", 0) or 0)

        # Modern CPython exposes stable inode/file-index values on Windows and POSIX.
        # If a platform cannot provide them, size/truncation checks still preserve the
        # ordinary append path and we simply cannot distinguish same-sized replacement.
        if handle_ino and path_ino:
            return handle_ino == path_ino and handle_dev == path_dev
        return True

    def _run(self) -> None:
        first_open = True

        while not self._stop.is_set():
            try:
                with self.path.open("rb") as f:
                    if first_open and self.start_at_end:
                        f.seek(0, os.SEEK_END)
                    first_open = False
                    self.start_at_end = False

                    while not self._stop.is_set():
                        pos = f.tell()
                        raw_line = f.readline()

                        if raw_line:
                            self.on_line(raw_line.decode("utf-8", errors="replace"))
                            continue

                        # EQ or another tool may truncate or atomically replace the log.
                        # Compare the pathname with the open handle rather than assuming
                        # that a nonshrinking pathname still belongs to this handle.
                        try:
                            path_stat = self.path.stat()
                            handle_stat = os.fstat(f.fileno())
                        except FileNotFoundError:
                            # The pathname disappeared or is between atomic-replace
                            # steps. Reopen when it becomes available again.
                            break
                        except PermissionError:
                            # Keep following the already-open handle. A transient
                            # Windows metadata-sharing failure must not rewind/replay
                            # the whole log.
                            self._stop.wait(max(self.poll_seconds, 0.05))
                            continue
                        except OSError:
                            # The open handle itself may no longer be usable.
                            break

                        if not self._same_file(handle_stat, path_stat):
                            break

                        size = int(path_stat.st_size)
                        if size < pos:
                            # Truncated in place. Reopen from byte zero.
                            break

                        if size > pos:
                            # New bytes exist at the pathname. Re-seeking to the current
                            # byte offset clears any buffered EOF state before reading.
                            f.seek(pos, os.SEEK_SET)
                            continue

                        self._stop.wait(self.poll_seconds)

            except (FileNotFoundError, PermissionError, OSError):
                self._stop.wait(max(self.poll_seconds, 0.5))
