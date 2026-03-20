"""
_core/resolver.py

Interactive TUI for conflict resolution during gt sync.

Uses curses (stdlib) — zero external dependencies.
Supports: ↑↓ navigation, ←→ theirs/ours toggle, Enter to open in IDE,
          c to continue, a to abort.

The watcher runs in a background thread and updates file states
automatically when the user saves files in their IDE.
"""
from __future__ import annotations

import curses
import os
import queue
from dataclasses import dataclass, field
from enum import Enum

from . import git as g
from .watcher import ConflictWatcher, has_conflict_markers


# ── File states ──────────────────────────────────────────────────────────────

class FileState(Enum):
    PENDING           = "pending"
    THEIRS            = "theirs"
    OURS              = "ours"
    IDE_OPEN          = "ide_open"
    RESOLVED_MANUAL   = "resolved_manual"
    STILL_CONFLICTED  = "still_conflicted"


# States that count as "resolved" for the continue check
_RESOLVED_STATES = {FileState.THEIRS, FileState.OURS, FileState.RESOLVED_MANUAL}

# States that allow ←→ toggling
_TOGGLEABLE_STATES = {
    FileState.PENDING, FileState.THEIRS, FileState.OURS,
    FileState.STILL_CONFLICTED,
}


@dataclass
class ConflictFile:
    path: str          # relative path
    abs_path: str      # absolute path
    conflicts: int     # number of <<<<<<< blocks
    state: FileState = FileState.PENDING


# ── Watcher event bridge ────────────────────────────────────────────────────

class _WatcherEvent:
    """Thread-safe event from the watcher to the TUI."""
    def __init__(self, filepath: str, resolved: bool):
        self.filepath = filepath
        self.resolved = resolved


# ── Resolver result ──────────────────────────────────────────────────────────

class ResolverResult(Enum):
    CONTINUE = "continue"
    ABORT    = "abort"


@dataclass
class Resolution:
    result: ResolverResult
    files: list[ConflictFile] = field(default_factory=list)


# ── TUI Renderer ─────────────────────────────────────────────────────────────

class ConflictResolverTUI:
    """
    Curses-based interactive conflict resolver.

    Renders the file list with states, handles keyboard input,
    and integrates with the ConflictWatcher for IDE sync.
    """

    def __init__(self, files: list[ConflictFile], branch: str):
        self.files = files
        self.branch = branch
        self.cursor = 0
        self.message = ""
        self.message_is_error = False
        self._events: queue.Queue[_WatcherEvent] = queue.Queue()
        self._watcher = ConflictWatcher()
        self._result: Resolution | None = None

    # ── Public API ───────────────────────────────────────────────────────

    def run(self) -> Resolution:
        """Launch the TUI. Blocks until user confirms or aborts."""
        if not self.files:
            return Resolution(result=ResolverResult.CONTINUE, files=[])

        # Set all files to theirs by default (safest default per plan)
        for f in self.files:
            f.state = FileState.THEIRS

        self._watcher.start(
            on_resolved=self._on_watcher_resolved,
            on_still_conflicted=self._on_watcher_still_conflicted,
        )
        interrupted = False
        try:
            curses.wrapper(self._main)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            self._watcher.stop()

        if interrupted:
            raise KeyboardInterrupt

        if self._result is None:
            return Resolution(result=ResolverResult.ABORT, files=self.files)
        return self._result

    # ── Watcher callbacks (called from watcher thread) ───────────────────

    def _on_watcher_resolved(self, filepath: str) -> None:
        self._events.put(_WatcherEvent(filepath, resolved=True))

    def _on_watcher_still_conflicted(self, filepath: str) -> None:
        self._events.put(_WatcherEvent(filepath, resolved=False))

    # ── Main curses loop ─────────────────────────────────────────────────

    def _main(self, stdscr: curses.window) -> None:
        curses.curs_set(0)
        stdscr.timeout(200)  # 200ms — allows watcher events to update UI
        # Let KeyboardInterrupt (Ctrl+C) propagate out of curses naturally
        curses.raw()

        self._init_colors()

        while True:
            self._process_watcher_events()
            self._render(stdscr)

            key = stdscr.getch()
            if key == -1:
                continue
            # Ctrl+C (3) — treat as hard abort, propagate as KeyboardInterrupt
            if key == 3:
                raise KeyboardInterrupt

            action = self._handle_key(key)
            if action == "quit":
                break

    # ── Color pairs ──────────────────────────────────────────────────────

    def _init_colors(self) -> None:
        curses.start_color()
        curses.use_default_colors()
        # pair 1: yellow (pending)
        curses.init_pair(1, curses.COLOR_YELLOW, -1)
        # pair 2: blue/cyan (theirs)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        # pair 3: green (ours / resolved)
        curses.init_pair(3, curses.COLOR_GREEN, -1)
        # pair 4: magenta (ide_open)
        curses.init_pair(4, curses.COLOR_MAGENTA, -1)
        # pair 5: red (error / still_conflicted)
        curses.init_pair(5, curses.COLOR_RED, -1)
        # pair 6: white bold (header)
        curses.init_pair(6, curses.COLOR_WHITE, -1)
        # pair 7: cursor highlight
        curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)

    def _state_color(self, state: FileState) -> int:
        return {
            FileState.PENDING:          curses.color_pair(1),
            FileState.THEIRS:           curses.color_pair(2),
            FileState.OURS:             curses.color_pair(3),
            FileState.IDE_OPEN:         curses.color_pair(4),
            FileState.RESOLVED_MANUAL:  curses.color_pair(3) | curses.A_BOLD,
            FileState.STILL_CONFLICTED: curses.color_pair(5),
        }.get(state, curses.color_pair(0))

    def _state_label(self, state: FileState) -> str:
        return {
            FileState.PENDING:          "[pending]",
            FileState.THEIRS:           "[✓ theirs]",
            FileState.OURS:             "[✓ ours  ]",
            FileState.IDE_OPEN:         "[IDE →   ]",
            FileState.RESOLVED_MANUAL:  "[✓ manual]",
            FileState.STILL_CONFLICTED: "[⚠ markers]",
        }.get(state, "[?]")

    # ── Render ───────────────────────────────────────────────────────────

    def _render(self, stdscr: curses.window) -> None:
        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()
        row = 0

        def _addstr(y: int, x: int, text: str, attr: int = 0) -> None:
            if y >= max_y - 1:
                return
            try:
                stdscr.addnstr(y, x, text, max_x - x - 1, attr)
            except curses.error:
                pass

        # Header
        _addstr(row, 1, f"✖  Rebase conflict on branch {self.branch}.",
                curses.color_pair(5) | curses.A_BOLD)
        row += 2

        # Separator
        n = len(self.files)
        sep = f"── Resolve conflicts ─{'─' * 30}── {n} file{'s' if n != 1 else ''} ──"
        _addstr(row, 1, sep, curses.color_pair(6) | curses.A_BOLD)
        row += 2

        # File list
        max_path_len = max((len(f.path) for f in self.files), default=20)
        max_path_len = min(max_path_len, max_x - 40)  # cap for narrow terminals

        for i, f in enumerate(self.files):
            is_selected = i == self.cursor
            prefix = "  › " if is_selected else "    "

            conflict_info = f"({f.conflicts} conflict{'s' if f.conflicts != 1 else ''})"
            label = self._state_label(f.state)
            arrows = " ◀ ▶" if f.state in _TOGGLEABLE_STATES else ""

            line = f"{prefix}{f.path:<{max_path_len}}  {conflict_info:<16} {label}{arrows}"

            if is_selected:
                _addstr(row, 0, line, curses.A_BOLD)
            else:
                # Color just the state label
                _addstr(row, 0, f"{prefix}{f.path:<{max_path_len}}  {conflict_info:<16} ")
                label_col = len(prefix) + max_path_len + 2 + 16 + 1
                _addstr(row, label_col, f"{label}{arrows}", self._state_color(f.state))

            row += 1

            # Sub-message for still_conflicted
            if f.state == FileState.STILL_CONFLICTED:
                sub = "    ↳ Saved but still has unresolved conflicts. Keep editing or use ←→."
                _addstr(row, 0, sub, curses.color_pair(5))
                row += 1

        row += 1

        # Keybinds
        _addstr(row, 2, "↑↓ navigate  ·  ←→ theirs/ours  ·  ↵ open IDE  ·  c continue  ·  a abort",
                curses.A_DIM)
        row += 2

        # Progress
        resolved = sum(1 for f in self.files if f.state in _RESOLVED_STATES)
        in_ide = sum(1 for f in self.files if f.state == FileState.IDE_OPEN)
        pending = n - resolved - in_ide

        parts = [f"{resolved} resolved"]
        if in_ide > 0:
            parts.append(f"{in_ide} in IDE")
        if pending > 0:
            parts.append(f"{pending} pending")

        _addstr(row, 2, f"Progress: {'  ·  '.join(parts)}")
        row += 1

        # Progress bar
        pct = (resolved / n * 100) if n > 0 else 0
        bar_width = min(30, max_x - 8)
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        _addstr(row, 2, f"[{bar}] {int(pct)}%", curses.color_pair(3) if pct == 100 else 0)
        row += 2

        # Message
        if self.message:
            color = curses.color_pair(5) if self.message_is_error else curses.color_pair(3)
            _addstr(row, 2, self.message, color)

        stdscr.refresh()

    # ── Keyboard handling ────────────────────────────────────────────────

    def _handle_key(self, key: int) -> str | None:
        self.message = ""
        self.message_is_error = False

        # Navigation
        if key == curses.KEY_UP or key == ord("k"):
            self.cursor = max(0, self.cursor - 1)
        elif key == curses.KEY_DOWN or key == ord("j"):
            self.cursor = min(len(self.files) - 1, self.cursor + 1)

        # Toggle theirs (→)
        elif key == curses.KEY_RIGHT or key == ord("l"):
            f = self.files[self.cursor]
            if f.state in _TOGGLEABLE_STATES:
                if f.state == FileState.THEIRS:
                    f.state = FileState.OURS
                else:
                    f.state = FileState.THEIRS
                self._watcher.remove_file(f.abs_path)

        # Toggle ours (←)
        elif key == curses.KEY_LEFT or key == ord("h"):
            f = self.files[self.cursor]
            if f.state in _TOGGLEABLE_STATES:
                if f.state == FileState.OURS:
                    f.state = FileState.THEIRS
                else:
                    f.state = FileState.OURS
                self._watcher.remove_file(f.abs_path)

        # Open in IDE (Enter)
        elif key in (curses.KEY_ENTER, 10, 13):
            f = self.files[self.cursor]
            if f.state in (FileState.RESOLVED_MANUAL,):
                self.message = f"'{f.path}' already resolved manually."
            else:
                f.state = FileState.IDE_OPEN
                self._watcher.add_file(f.abs_path)
                g.open_in_editor(f.abs_path)
                self.message = f"Opened '{f.path}' in editor."

        # Continue (c)
        elif key == ord("c"):
            return self._try_continue()

        # Abort (a)
        elif key == ord("a"):
            return self._try_abort()

        # Quit with q too (alias for abort)
        elif key == ord("q"):
            return self._try_abort()

        return None

    def _try_continue(self) -> str | None:
        """Validate all files are resolved, then confirm."""
        unresolved = [f for f in self.files if f.state not in _RESOLVED_STATES]
        if unresolved:
            names = ", ".join(f.path for f in unresolved[:3])
            remaining = len(unresolved) - 3
            extra = f" (+{remaining} more)" if remaining > 0 else ""
            self.message = f"Cannot continue — unresolved: {names}{extra}"
            self.message_is_error = True
            return None

        self._result = Resolution(result=ResolverResult.CONTINUE, files=self.files)
        return "quit"

    def _try_abort(self) -> str | None:
        """Abort the resolution."""
        self._result = Resolution(result=ResolverResult.ABORT, files=self.files)
        return "quit"

    # ── Watcher event processing ─────────────────────────────────────────

    def _process_watcher_events(self) -> None:
        """Drain the event queue and update file states."""
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break

            for f in self.files:
                if f.abs_path == event.filepath:
                    if event.resolved:
                        f.state = FileState.RESOLVED_MANUAL
                        self._watcher.remove_file(f.abs_path)
                    else:
                        f.state = FileState.STILL_CONFLICTED
                    break


# ── Public entry point ───────────────────────────────────────────────────────

def resolve_conflicts(branch: str) -> Resolution:
    """
    Detect conflicted files and launch the interactive resolver TUI.
    Returns a Resolution with the user's decisions.
    """
    raw_files = g.conflicted_files()

    if not raw_files:
        return Resolution(result=ResolverResult.CONTINUE, files=[])

    files = [
        ConflictFile(
            path=f["path"],
            abs_path=f["abs_path"],
            conflicts=f["conflicts"],
        )
        for f in raw_files
    ]

    tui = ConflictResolverTUI(files, branch)
    return tui.run()


def apply_resolutions(resolution: Resolution) -> bool:
    """
    Apply the user's conflict resolution decisions.
    Executes git checkout --theirs/--ours + git add for each file,
    then runs git rebase --continue.
    Returns True if the rebase continued successfully.
    """
    from . import ui

    for f in resolution.files:
        if f.state == FileState.THEIRS:
            g.checkout_theirs(f.abs_path)
            g.stage_file(f.abs_path)
            ui.detail(f"  {f.path} → theirs")
        elif f.state == FileState.OURS:
            g.checkout_ours(f.abs_path)
            g.stage_file(f.abs_path)
            ui.detail(f"  {f.path} → ours")
        elif f.state == FileState.RESOLVED_MANUAL:
            if os.path.exists(f.abs_path):
                g.stage_file(f.abs_path)
            else:
                g.remove_file(f.abs_path)
            ui.detail(f"  {f.path} → manual")

    return True


def print_resolution_summary(resolution: Resolution) -> None:
    """Print a human-readable summary of what was resolved and how."""
    from . import ui

    theirs = [f for f in resolution.files if f.state == FileState.THEIRS]
    ours = [f for f in resolution.files if f.state == FileState.OURS]
    manual = [f for f in resolution.files if f.state == FileState.RESOLVED_MANUAL]

    ui.blank()
    if theirs:
        ui.info(f"  theirs ({len(theirs)}):  {' · '.join(f.path for f in theirs)}")
    if ours:
        ui.info(f"  ours   ({len(ours)}):  {' · '.join(f.path for f in ours)}")
    if manual:
        ui.info(f"  manual ({len(manual)}):  {' · '.join(f.path for f in manual)}")
    ui.blank()
