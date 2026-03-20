"""
_core/watcher.py

File watcher for conflict resolution.
Monitors files opened in an external IDE and detects when conflict markers
are removed (resolved) or still present after a save.

Zero dependencies — uses os.stat() polling in a daemon thread.
Typical latency: ~300ms for 1-50 files.
"""
from __future__ import annotations

import os
import threading
from typing import Callable

CONFLICT_MARKER = b"<<<<<<< "


def has_conflict_markers(filepath: str) -> bool:
    """
    Return True if the file still contains git conflict markers.
    Reads in 8 KiB chunks for efficiency on large files.
    """
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                if CONFLICT_MARKER in chunk:
                    return True
    except (IOError, OSError):
        return False
    return False


def count_conflict_markers(filepath: str) -> int:
    """Count the number of <<<<<<< blocks in a file."""
    count = 0
    try:
        with open(filepath, "rb") as f:
            for line in f:
                if line.startswith(CONFLICT_MARKER):
                    count += 1
    except (IOError, OSError):
        pass
    return count


class ConflictWatcher:
    """
    Polls tracked files for mtime changes and checks conflict markers.

    Usage:
        watcher = ConflictWatcher()
        watcher.start(on_resolved=cb1, on_still_conflicted=cb2)
        watcher.add_file("/path/to/file.py")
        ...
        watcher.stop()

    Callbacks receive (filepath: str) and are called from the polling thread.
    The caller must handle thread-safety (e.g. via queue.Queue).
    """

    def __init__(self, poll_interval: float = 0.3):
        self._tracked: dict[str, float] = {}  # filepath -> last mtime
        self._lock = threading.Lock()
        self._running = False
        self._poll_interval = poll_interval
        self._on_resolved: Callable[[str], None] | None = None
        self._on_still_conflicted: Callable[[str], None] | None = None
        self._thread: threading.Thread | None = None

    def start(
        self,
        on_resolved: Callable[[str], None],
        on_still_conflicted: Callable[[str], None],
    ) -> None:
        self._on_resolved = on_resolved
        self._on_still_conflicted = on_still_conflicted
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        import time

        while self._running:
            with self._lock:
                snapshot = dict(self._tracked)

            for filepath, last_mtime in snapshot.items():
                try:
                    current_mtime = os.stat(filepath).st_mtime
                except OSError:
                    # File deleted — treat as resolved (git rm case)
                    with self._lock:
                        self._tracked.pop(filepath, None)
                    if self._on_resolved:
                        self._on_resolved(filepath)
                    continue

                if current_mtime != last_mtime:
                    with self._lock:
                        self._tracked[filepath] = current_mtime
                    if has_conflict_markers(filepath):
                        if self._on_still_conflicted:
                            self._on_still_conflicted(filepath)
                    else:
                        if self._on_resolved:
                            self._on_resolved(filepath)

            time.sleep(self._poll_interval)

    def add_file(self, filepath: str) -> None:
        """Start tracking a file. Call when user opens it in the IDE."""
        with self._lock:
            try:
                self._tracked[filepath] = os.stat(filepath).st_mtime
            except OSError:
                self._tracked[filepath] = 0.0

    def remove_file(self, filepath: str) -> None:
        """Stop tracking a file (e.g. user chose theirs/ours instead)."""
        with self._lock:
            self._tracked.pop(filepath, None)

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._tracked.clear()
