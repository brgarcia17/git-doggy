"""
_core/git.py

All git subprocess calls go through this module.
Commands are logged in --verbose mode via ui.detail().
Failures raise GitError — never swallowed silently.
"""
from __future__ import annotations

import os
import subprocess
import sys
from . import ui


class GitError(Exception):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd        = cmd
        self.returncode = returncode
        self.stderr     = stderr
        super().__init__(f"git {' '.join(cmd[1:])} → exit {returncode}\n{stderr}")


def _run(
    args: list[str],
    *,
    capture: bool = True,
    allow_fail: bool = False,
) -> subprocess.CompletedProcess:
    ui.detail(f"$ {' '.join(args)}")
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
    if not allow_fail and result.returncode != 0:
        raise GitError(args, result.returncode, result.stderr or "")
    return result


# ── Read operations ───────────────────────────────────────────────────────────

def current_branch() -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()


def is_clean() -> bool:
    return _run(["git", "status", "--porcelain"]).stdout.strip() == ""


def dirty_files() -> list[str]:
    r = _run(["git", "status", "--porcelain"])
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def divergence(remote_ref: str, local_ref: str) -> tuple[int, int]:
    """Return (behind, ahead) of local vs remote_ref."""
    r = _run([
        "git", "rev-list", "--left-right", "--count",
        f"{remote_ref}...{local_ref}",
    ])
    parts = r.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0
    return int(parts[0]), int(parts[1])


def log_oneline(base: str, tip: str, max_count: int = 10) -> list[str]:
    r = _run([
        "git", "log", "--oneline",
        f"--max-count={max_count}",
        f"{base}..{tip}",
    ])
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


# ── Write operations ──────────────────────────────────────────────────────────

def fetch(remote: str) -> None:
    _run(["git", "fetch", remote], capture=False)


def checkout(branch: str) -> None:
    _run(["git", "checkout", branch], capture=False)


def pull_ff(remote: str, branch: str) -> None:
    _run(["git", "pull", "--ff-only", remote, branch], capture=False)


def rebase(onto: str) -> subprocess.CompletedProcess:
    """Rebase current branch onto `onto`. Caller checks returncode."""
    return _run(["git", "rebase", onto], allow_fail=True)


def rebase_abort() -> None:
    _run(["git", "rebase", "--abort"], allow_fail=True)


def merge_simulate(branch: str) -> subprocess.CompletedProcess:
    """Dry-run merge (--no-commit --no-ff). Caller must abort afterward."""
    return _run(["git", "merge", "--no-commit", "--no-ff", branch], allow_fail=True)


def merge_abort() -> None:
    _run(["git", "merge", "--abort"], allow_fail=True)


def merge_commit(branch: str, message: str) -> None:
    _run(["git", "merge", "--no-ff", branch, "-m", message], capture=False)


def push(remote: str, branch: str, *, force_with_lease: bool = False) -> None:
    cmd = ["git", "push", remote, branch]
    if force_with_lease:
        cmd.append("--force-with-lease")
    _run(cmd, capture=False)


# ── Conflict resolution ─────────────────────────────────────────────────────

def repo_root() -> str:
    """Return the absolute path to the repository root."""
    return _run(["git", "rev-parse", "--show-toplevel"]).stdout.strip()


def conflicted_files() -> list[dict]:
    """
    Return list of files with unmerged (conflicted) status.
    Each entry: {"path": <relative_path>, "conflicts": <int>}
    """
    from .watcher import count_conflict_markers

    r = _run(["git", "diff", "--name-only", "--diff-filter=U"], allow_fail=True)
    if r.returncode != 0 or not r.stdout.strip():
        return []

    root = repo_root()
    files = []
    for line in r.stdout.strip().splitlines():
        rel = line.strip()
        if not rel:
            continue
        abs_path = os.path.join(root, rel)
        conflicts = count_conflict_markers(abs_path)
        files.append({"path": rel, "abs_path": abs_path, "conflicts": conflicts})
    return files


def checkout_theirs(filepath: str) -> None:
    """Resolve a conflicted file by accepting the incoming (theirs) version."""
    _run(["git", "checkout", "--theirs", "--", filepath])


def checkout_ours(filepath: str) -> None:
    """Resolve a conflicted file by keeping our version."""
    _run(["git", "checkout", "--ours", "--", filepath])


def stage_file(filepath: str) -> None:
    """Stage a file (git add)."""
    _run(["git", "add", "--", filepath])


def remove_file(filepath: str) -> None:
    """Remove a file from the index (git rm)."""
    _run(["git", "rm", "--", filepath], allow_fail=True)


def rebase_continue() -> tuple[bool, str]:
    """
    Continue a rebase in progress.
    Returns (success, output_message).
    """
    r = _run(
        ["git", "-c", "core.editor=true", "rebase", "--continue"],
        allow_fail=True,
    )
    output = ((r.stdout or "") + (r.stderr or "")).strip()
    return r.returncode == 0, output


def is_rebase_in_progress() -> bool:
    """Check if there is a rebase currently in progress."""
    root = repo_root()
    return (
        os.path.isdir(os.path.join(root, ".git", "rebase-merge"))
        or os.path.isdir(os.path.join(root, ".git", "rebase-apply"))
    )


def detect_ide() -> str | None:
    """
    Detect the IDE hosting the current terminal session via environment variables.

    Returns the CLI command prefix to open a file in that IDE, or None if
    running in a plain terminal (fall back to platform default).

    Priority order reflects the most specific match first.
    """
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    terminal_emulator = os.environ.get("TERMINAL_EMULATOR", "").lower()

    if "jetbrains" in terminal_emulator or "jeditterm" in terminal_emulator:
        # JetBrains IDEs (IntelliJ, WebStorm, PyCharm, etc.)
        # Use the built-in 'idea' / 'webstorm' / etc. launcher if available,
        # otherwise fall back to platform open — JetBrains will pick it up.
        return None  # JetBrains opens files via platform default from its own terminal
    if term_program in ("vscode", "windsurf"):
        return "code"  # VS Code and Windsurf both use the 'code' CLI
    if term_program == "cursor":
        return "cursor"
    # Apple Terminal, iTerm2, plain terminals → no IDE-specific opener
    return None


def open_in_editor(filepath: str) -> None:
    """
    Open a file for editing, preferring the IDE that hosts this terminal.

    Detection priority:
      1. VS Code / Windsurf  → code <file>       (TERM_PROGRAM=vscode|Windsurf)
      2. Cursor              → cursor <file>      (TERM_PROGRAM=cursor)
      3. JetBrains           → platform default   (TERMINAL_EMULATOR=JetBrains-JediTerm)
      4. Fallback            → open / xdg-open / start
    """
    ide_cmd = detect_ide()
    if ide_cmd:
        cmd: list[str] = [ide_cmd, filepath]
        shell = False
    elif sys.platform == "darwin":
        cmd = ["open", filepath]
        shell = False
    elif sys.platform.startswith("linux"):
        cmd = ["xdg-open", filepath]
        shell = False
    else:
        cmd = ["start", "", filepath]
        shell = True

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=shell,
    )
